# -*- coding: utf-8 -*-
"""External Identity Authentication Router — 模型A/模型B 入口（薄适配器）。

入站登录业务（查绑定 → 死绑定自愈 → 匹配已有账号 → 建号 → 写绑定 → 发 token
→ 审计）**只有一份**，在 :mod:`coapis.app.external_login_core`。本文件只负责
各入口特有的**验签**与**响应形态**：

    模型A（SSO 跳转）
        GET  /api/auth/external/login-state   签发一次性 state + login_url
        POST /api/auth/external/login         state 校验 + 防重放 + 验签 → 核心
    模型B（凭证直登）
        POST /api/auth/external/credential-login   调外部登录 API 验凭证 → 核心
    绑定管理
        POST /api/auth/users/identity/bind | /unbind
        POST /api/auth/external/auto-login          管理员代登

旧契约入口 ``/api/external/login``（生产主路径）见 ``app/external_login.py``，
同样调用本核心 —— 两个入口共用同一份登录业务，不再各写一套。

安全要点：
    - state 一次性（防 CSRF），文件原子写，TTL 10 分钟
    - timestamp 防重放（TTL 可配，默认 300 秒）
    - redirect 白名单：仅站内 / 开头、禁 //
    - secret 永不出现在 /systems 响应中
"""
import json
import logging
import secrets
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request

from .. import external_login_core as core
from ..external_login_core import (  # noqa: F401  (re-export：测试与旧调用方沿用)
    DEFAULT_CALLBACK_TTL,
    EXTERNAL_SSO_SECRET,
    MAPPINGS_FILE,
    STATE_FILE,
    STATE_TTL,
    _load_states,
    _render_template,
    _save_states,
    _state_cache,
    _state_lock,
    _validate_redirect,
    find_binding_by_external,
    load_bindings,
    resolve_secret,
    save_bindings_atomic,
    sign_hmac,
    verify_signature,
)

logger = logging.getLogger(__name__)

# 注意：前缀用短形式 /auth —— 顶层 api_router 已带 /api 前缀，最终 URL 为 /api/auth/...
router = APIRouter(prefix="/auth", tags=["external_auth"])

# ---------------------------------------------------------------------------
# 端点：登录页可见的外部系统（公开，无 secret）
# ---------------------------------------------------------------------------

@router.get("/external/systems")
async def list_external_systems():
    """List external systems visible on the login page.

    条件：show_on_login != False 且 login_type != none。
    按 display_order 升序。返回登录按钮所需字段，**绝不含 secret**。
    """
    from ..external_identity import _load_systems

    items = []
    for s in _load_systems():
        if s.get("show_on_login") is False:
            continue
        login_type = s.get("login_type", "")
        if login_type == "none":
            continue
        items.append({
            "provider_id": s.get("provider_id"),
            "name": s.get("name"),
            "icon": s.get("icon", ""),
            "login_type": login_type,
            "display_order": s.get("display_order", 100),
        })
    items.sort(key=lambda x: (x["display_order"], x["provider_id"] or ""))
    return {"success": True, "data": items}


# ---------------------------------------------------------------------------
# 端点：当前登录会话的外部系统（页面头部徽标用）
# ---------------------------------------------------------------------------

@router.get("/external/current-system")
async def get_current_external_system(request: Request):
    """返回当前登录会话所使用的外部系统（名称 + LOGO）。

    登录 token 携带 ext_provider 声明（外部系统登录时写入）。本端点解析
    token 中的 provider 并查系统配置，返回头部展示所需的 name/icon。

    - 未登录 / 普通账号密码登录（无 ext_provider）/ 系统已被删除 → data=null
    - 已登录外部系统 → data={provider_id, name, icon, login_type}

    注意：不限制 show_on_login（登录页隐藏的系统，其用户会话仍需展示来源）。
    """
    from ..auth import get_token_ext_provider
    from ..external_identity import get_system_by_id

    # 从 Authorization 头解析 token（middleware 已保证公共路径也尝试解析；
    # 这里直接取原始 token 读 ext_provider 声明）
    auth_header = request.headers.get("authorization", "")
    token = auth_header[7:] if auth_header.startswith("Bearer ") else ""
    if not token:
        return {"success": True, "data": None}

    provider = get_token_ext_provider(token)
    if not provider:
        return {"success": True, "data": None}

    system = get_system_by_id(provider)
    if system is None:
        return {"success": True, "data": None}

    return {"success": True, "data": {
        "provider_id": provider,
        "name": system.get("name") or provider,
        "icon": system.get("icon", ""),
        "login_type": system.get("login_type", ""),
    }}


# ---------------------------------------------------------------------------
# 端点：模型A — 签发一次性 state + 外部系统登录 URL
# ---------------------------------------------------------------------------

@router.get("/external/login-state")
async def get_external_login_state(request: Request, provider: str = ""):
    """模型A 第一步：生成一次性 state 并返回外部系统登录 URL。

    login_url 模板占位符：{client_id} {state} {redirect}
    redirect 渲染为**绝对**回调 URL（外部系统拿到的必须是可访问的完整地址）。
    """
    from ..external_identity import get_system_by_id

    if not provider:
        raise HTTPException(status_code=400, detail="provider is required")

    system = get_system_by_id(provider)
    if system is None:
        raise HTTPException(status_code=404, detail="External system not configured")
    if system.get("status", 1) != 1:
        raise HTTPException(status_code=403, detail="External system is disabled")
    if system.get("login_type") != "sso_redirect":
        raise HTTPException(status_code=400, detail="System does not use SSO redirect login")

    sso = system.get("sso") or {}
    login_url_tpl = sso.get("login_url", "")
    if not login_url_tpl:
        raise HTTPException(status_code=500, detail="External system has no login_url configured")

    state = secrets.token_urlsafe(24)
    now = time.time()
    with _state_lock:
        states = _load_states()
        states[state] = {
            "provider": provider,
            "exp": now + STATE_TTL,
            "created_at": now,
        }
        _save_states(states)

    # 绝对回调 URL：外部系统 302 回来时用，必须可访问（scheme+host+port 来自请求）
    callback_url = f"{str(request.base_url).rstrip('/')}/login/callback"
    login_url = _render_template(login_url_tpl, {
        "client_id": system.get("client_id", ""),
        "state": state,
        "redirect": callback_url,
    })

    return {"success": True, "data": {"state": state, "login_url": login_url}}


# ---------------------------------------------------------------------------
# 端点：模型A — SSO 回调验签 + 建用户 + 发真 token
# ---------------------------------------------------------------------------

@router.post("/external/login")
async def external_login(request: Request):
    """外部系统 SSO 回调登录（模型A 核心端点）—— 验签后交给入站登录核心。

    请求体：
        provider（可选，缺省时从 state 解析）, external_id, timestamp, signature, state,
        external_name（可选，用于显示名）, redirect（可选，站内路径）

    本端点只做四件事：state 校验 → 防重放 → 验签 → 消费 state；
    之后「查绑定/自愈/匹配/建号/写绑定/发 token/审计」全部由核心完成。
    """
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    external_id = data.get("external_id")
    state = data.get("state")
    signature = data.get("signature")
    provider = data.get("provider") or None

    try:
        timestamp = int(data.get("timestamp"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid timestamp")

    if not external_id or not state or not signature:
        raise HTTPException(
            status_code=400,
            detail="Missing required parameters: external_id, timestamp, signature, state",
        )

    from ..external_identity import get_system_by_id

    # 1. state 只读探测：provider 可由 state 还原（外部系统 302 回来只带 query 参数）
    states = _load_states()
    entry = states.get(state)
    if entry is None or entry.get("exp", 0) < time.time():
        raise HTTPException(status_code=403, detail="Invalid or expired login state")
    if not provider:
        provider = entry.get("provider")
    if not provider:
        raise HTTPException(status_code=400, detail="Missing provider and state carries none")
    if provider != entry.get("provider"):
        raise HTTPException(status_code=403, detail="State provider mismatch")

    system = get_system_by_id(provider)
    if system is None:
        raise HTTPException(status_code=404, detail="External system not configured")
    if system.get("status", 1) != 1:
        raise HTTPException(status_code=403, detail="External system is disabled")

    # 2. 防重放（TTL 可配，默认 300 秒）
    sso = system.get("sso") or {}
    callback_cfg = sso.get("callback") or {}
    try:
        ttl = int(callback_cfg.get("timestamp_ttl") or DEFAULT_CALLBACK_TTL)
    except (TypeError, ValueError):
        ttl = DEFAULT_CALLBACK_TTL
    if abs(int(time.time()) - timestamp) > ttl:
        raise HTTPException(status_code=401, detail="Request expired or timestamp invalid")

    # 3. 验签（签名串模板可配，默认固定格式保持旧配置兼容：
    #    provider=..&external_id=..&timestamp=..，HMAC-SHA256 hex）
    secret = resolve_secret(system)
    sign_string = callback_cfg.get("sign_string") or ""
    if not sign_string:
        sign_string = f"provider={provider}&external_id={external_id}&timestamp={timestamp}"
    else:
        sign_string = _render_template(sign_string, {
            "provider": provider,
            "external_id": external_id,
            "timestamp": str(timestamp),
        })
    if not verify_signature(secret, sign_string, signature):
        raise HTTPException(status_code=403, detail="Invalid signature")

    # 4. 消费 state（一次性，验签通过才消费）
    states.pop(state, None)
    _save_states(states)

    # 5. 身份解析 + 发 token（唯一真源：external_login_core）
    outcome = core.resolve_external_identity(
        provider=provider,
        system=system,
        external_id=external_id,
        external_name=str(data.get("external_name") or "").strip(),
        request=request,
    )
    issued = core.finish_login(
        username=outcome["username"],
        provider=provider,
        auto_created=outcome["auto_created"],
        redirect=data.get("redirect") or "/chat",
    )

    return {
        "success": True,
        "token": issued["token"],
        "username": issued["username"],
        "display_name": issued["display_name"],
        "first_login": outcome["first_login"],
        "default_agent_id": issued["default_agent_id"],
        "auto_created": outcome["auto_created"],
        "redirect": issued["redirect"],
    }


# ---------------------------------------------------------------------------
# 端点：模型B — 凭证直登（用户在 CoApis 输入外部系统的账号密码）
# ---------------------------------------------------------------------------

def _resolve_nested_field(data: Any, path: str) -> Any:
    """Resolve a dot-notation path like ``data.userId`` from a nested dict."""
    if not path:
        return None
    parts = path.split(".")
    current = data
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _values_equal(actual: Any, expected: Any) -> bool:
    """智能比较 success_value：兼容数字/字符串（0 == "0"，200 == "200"）。"""
    if actual is None or expected is None:
        return False
    if actual == expected:
        return True
    a = str(actual).strip()
    b = str(expected).strip()
    if a == b:
        return True
    try:
        return float(a) == float(b)
    except (ValueError, TypeError):
        return False


async def _call_external_login_api(
    system: Dict[str, Any],
    username: str,
    password: str,
) -> Dict[str, Any]:
    """调用外部系统登录 API 并解析响应（含 profile 补姓名）。

    Returns:
        {
            ok: bool,
            resp_data: dict (原始响应),
            external_id: str | None,
            external_name: str,
            error: str | None,
        }
    """
    import aiohttp

    cred = system.get("credential") or {}
    api_cfg = cred.get("api") or {}
    login_url = (api_cfg.get("url") or "").strip()
    if not login_url:
        return {"ok": False, "resp_data": None, "external_id": None,
                "external_name": "", "error": "外部系统未配置登录 API URL"}

    method = (api_cfg.get("method") or "POST").upper()
    content_type = (api_cfg.get("content_type") or "application/json").strip()
    is_form = content_type.startswith("application/x-www-form-urlencoded")

    # headers：可能是 dict，也可能是前端存的 JSON 字符串
    raw_headers = api_cfg.get("headers") or {}
    if isinstance(raw_headers, str):
        try:
            raw_headers = json.loads(raw_headers) if raw_headers.strip() else {}
        except json.JSONDecodeError as e:
            return {"ok": False, "resp_data": None, "external_id": None,
                    "external_name": "", "error": f"Headers 配置不是合法 JSON：{e}"}
    if not isinstance(raw_headers, dict):
        return {"ok": False, "resp_data": None, "external_id": None,
                "external_name": "", "error": "Headers 配置必须是 JSON 对象"}
    headers = {str(k): str(v) for k, v in raw_headers.items()}
    headers["Content-Type"] = content_type

    # body：可能是 dict，也可能是前端 TextArea 存的 JSON 字符串
    body_raw = api_cfg.get("body")
    body_dict: Dict[str, str] | None = None
    body_str: str | None = None
    tpl = {"username": username, "password": password}
    if isinstance(body_raw, dict):
        body_dict = {str(k): _render_template(str(v), tpl) for k, v in body_raw.items()}
    elif isinstance(body_raw, str) and body_raw.strip():
        try:
            parsed = json.loads(body_raw)
            if isinstance(parsed, dict):
                body_dict = {str(k): _render_template(str(v), tpl) for k, v in parsed.items()}
            else:
                body_str = _render_template(body_raw, tpl)
        except json.JSONDecodeError:
            body_str = _render_template(body_raw, tpl)

    # 调外部系统登录 API
    timeout = aiohttp.ClientTimeout(total=int(cred.get("timeout") or 15))
    resp_status: int | None = None
    resp_text = ""
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            req_kwargs: Dict[str, Any] = {}
            if is_form:
                if body_dict is not None:
                    req_kwargs["data"] = body_dict
                elif body_str is not None:
                    req_kwargs["data"] = body_str
            else:
                if body_dict is not None:
                    req_kwargs["json"] = body_dict
                elif body_str is not None:
                    req_kwargs["data"] = body_str
                else:
                    req_kwargs["json"] = {}
            async with session.request(method, login_url, headers=headers, **req_kwargs) as resp:
                resp_status = resp.status
                resp_text = await resp.text()
    except aiohttp.ClientError as e:
        logger.error("Credential login: external API request failed: %s", e)
        return {"ok": False, "resp_data": None, "external_id": None,
                "external_name": "", "error": f"外部系统不可达：{e}"}
    except Exception as e:
        logger.error("Credential login: external API error: %s", e)
        return {"ok": False, "resp_data": None, "external_id": None,
                "external_name": "", "error": f"调用外部系统失败：{e}"}

    # 解析响应：非 JSON 给明确提示
    try:
        resp_data = json.loads(resp_text) if resp_text.strip() else {}
    except json.JSONDecodeError:
        preview = (resp_text or "")[:200]
        return {"ok": False, "resp_data": None, "external_id": None,
                "external_name": "",
                "error": f"外部系统响应不是 JSON（HTTP {resp_status}）：{preview}"}

    # 解析响应
    resp_cfg = cred.get("response") or {}
    success_field = resp_cfg.get("success_field", "code")
    success_value = resp_cfg.get("success_value", 0)
    error_field = resp_cfg.get("error_field", "msg")
    openid_field = resp_cfg.get("openid_field", "")
    name_field = resp_cfg.get("name_field", "")

    actual_code = _resolve_nested_field(resp_data, success_field)
    if not _values_equal(actual_code, success_value):
        err_msg = _resolve_nested_field(resp_data, error_field) or str(resp_data)
        return {"ok": False, "resp_data": resp_data, "external_id": None,
                "external_name": "", "error": f"External system login failed: {err_msg}"}

    external_id = _resolve_nested_field(resp_data, openid_field)
    if external_id is None:
        return {"ok": False, "resp_data": resp_data, "external_id": None,
                "external_name": "", "error": "External system did not return an identifier (openid_field misconfigured?)"}
    external_id = str(external_id)

    external_name = str(_resolve_nested_field(resp_data, name_field) or "").strip()

    # 如果登录响应没返回姓名，且配置了 profile 接口，用 access token 调 profile 拿姓名
    if not external_name:
        profile_cfg = cred.get("profile") or {}
        profile_url = profile_cfg.get("url", "")
        if profile_url:
            try:
                token_field = profile_cfg.get("token_field", "data.accessToken")
                ext_token = _resolve_nested_field(resp_data, token_field)
                if ext_token:
                    p_method = (profile_cfg.get("method") or "GET").upper()
                    p_headers = dict(profile_cfg.get("headers") or {})
                    p_headers["Authorization"] = f"Bearer {ext_token}"
                    p_timeout = aiohttp.ClientTimeout(total=10)
                    async with aiohttp.ClientSession(timeout=p_timeout) as p_session:
                        async with p_session.request(p_method, profile_url, headers=p_headers) as p_resp:
                            p_data = await p_resp.json()
                    p_name_field = profile_cfg.get("name_field", "")
                    external_name = str(_resolve_nested_field(p_data, p_name_field) or "").strip()
                    logger.info("Credential login: fetched profile name '%s' for external_id=%s", external_name, external_id)
            except Exception as e:
                logger.warning("Credential login: profile fetch failed (non-fatal): %s", e)

    return {"ok": True, "resp_data": resp_data, "external_id": external_id,
            "external_name": external_name, "error": None}


@router.post("/external/credential-login")
async def credential_login(request: Request):
    """凭证直登（模型B）：CoApis 代用户调用外部系统登录 API。

    请求体：``{provider, username, password}``
    流程：查系统配置 → 调外部系统登录 API → 解析 external_id/name
    → 查绑定 / 自动建用户 → 发真 token。
    """
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    provider = data.get("provider")
    username = str(data.get("username") or "").strip()
    password = str(data.get("password") or "").strip()

    if not provider or not username or not password:
        raise HTTPException(
            status_code=400,
            detail="Missing required parameters: provider, username, password",
        )

    from ..external_identity import get_system_by_id
    from ..user_store import get_user, create_user, touch_last_login
    from ..auth import create_token

    system = get_system_by_id(provider)
    if system is None:
        raise HTTPException(status_code=404, detail="External system not configured")
    if system.get("status", 1) != 1:
        raise HTTPException(status_code=403, detail="External system is disabled")
    if system.get("login_type") != "credential":
        raise HTTPException(
            status_code=400,
            detail="System does not use credential-based login",
        )

    # 调用外部系统登录 API 并解析
    api_result = await _call_external_login_api(system, username, password)
    if not api_result["ok"]:
        status = 502 if "unreachable" in api_result["error"] else 401
        raise HTTPException(status_code=status, detail=api_result["error"])

    external_id = api_result["external_id"]
    external_name = api_result["external_name"]
    resp_data = api_result["resp_data"]

    # 身份解析（唯一真源：external_login_core）—— 与模型A/旧契约完全同一份逻辑
    outcome = core.resolve_external_identity(
        provider=provider,
        system=system,
        external_id=external_id,
        external_name=external_name,
        request=request,
    )
    local_username = outcome["username"]
    auto_created = outcome["auto_created"]
    first_login = outcome["first_login"]

    # 透传模式：把外部系统签发的 token 存进绑定记录（供出站透传）
    try:
        from ..external_token import extract_login_tokens, store_login_tokens
        ext_tokens = extract_login_tokens(system, resp_data)
        if ext_tokens:
            store_login_tokens(provider, external_id, ext_tokens)
    except Exception as e:
        logger.warning("Credential login: 存外部 token 失败（不影响登录）: %s", e)

    # 发真 token（ext_provider 记录登录来源外部系统）
    user_info = get_user(local_username)
    if user_info is None:
        raise HTTPException(status_code=404, detail="Local user no longer exists")

    token = create_token(local_username, ext_provider=provider)

    # 审计
    try:
        from .audit import _append_audit_entry
        _append_audit_entry({
            "timestamp": time.time(),
            "event_type": "auth",
            "action": "login_success",
            "user_id": local_username,
            "source": f"external:{provider}:credential",
            "detail": f"凭证直登成功 (auto_created={auto_created})",
        })
    except Exception:
        pass

    return {
        "success": True,
        "token": token,
        "username": local_username,
        "display_name": user_info.get("display_name") or local_username,
        "first_login": first_login,
        "default_agent_id": f"user:{local_username}",
        "auto_created": auto_created,
        "redirect": _validate_redirect(data.get("redirect") or "/chat"),
    }


# ---------------------------------------------------------------------------
# 端点：外部系统登录 API 测试（管理端）
# ---------------------------------------------------------------------------

@router.post("/external/credential-test")
async def credential_test(request: Request):
    """测试外部系统登录 API 连通性。

    用配置的凭证实际调一次登录 API（不建用户、不发 token），
    返回原始响应供管理员确认 field 映射是否正确。

    需要 admin 权限。
    """
    from ..auth import require_admin
    require_admin(request)

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    provider = data.get("provider")
    username = str(data.get("username") or "").strip()
    password = str(data.get("password") or "").strip()
    # 支持未保存的表单数据：前端把弹窗里正在编辑的 credential 直接传过来，
    # 不必先保存就能测试真实连通性。未提供时回退到查询已保存配置。
    inline_cred = data.get("credential")

    if not username or not password:
        raise HTTPException(
            status_code=400,
            detail="Missing required parameters: username, password",
        )

    if isinstance(inline_cred, dict) and inline_cred:
        # 直接用表单里的配置测试（覆盖未保存场景）
        system = {"provider_id": provider, "login_type": "credential",
                  "credential": inline_cred}
    else:
        if not provider:
            raise HTTPException(
                status_code=400,
                detail="Missing required parameter: provider",
            )
        from ..external_identity import get_system_by_id

        system = get_system_by_id(provider)
        if system is None:
            raise HTTPException(
                status_code=404,
                detail="External system not configured（请先保存配置，或确认 provider_id 正确）",
            )
        if system.get("login_type") != "credential":
            raise HTTPException(
                status_code=400,
                detail="System does not use credential-based login",
            )

    api_result = await _call_external_login_api(system, username, password)

    if not api_result["ok"]:
        return {
            "success": False,
            "error": api_result["error"],
            "raw_response": api_result["resp_data"],
        }

    return {
        "success": True,
        "external_id": api_result["external_id"],
        "external_name": api_result["external_name"],
        "raw_response": api_result["resp_data"],
    }


# ---------------------------------------------------------------------------
# 端点：手动绑定 / 解绑（保持原行为，增强字段）
# ---------------------------------------------------------------------------

@router.post("/users/identity/bind")
async def bind_external_identity(request: Request, current_user_id: str = None):
    """Manual binding endpoint for external identity"""
    if not current_user_id:
        raise HTTPException(status_code=401, detail="User not authenticated")

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    provider = data.get("provider")
    external_id = data.get("external_id")
    external_name = str(data.get("external_name") or "").strip() or None

    if not provider or not external_id:
        raise HTTPException(status_code=400, detail="Missing required parameters: provider, external_id")

    mappings = load_bindings()

    # Check if the same external ID is already bound
    for b in mappings.get("bindings", []):
        if b.get("provider") == provider and str(b.get("external_id")) == str(external_id):
            raise HTTPException(status_code=400, detail="External ID already bound to another account or exists.")

    # Add new binding record
    new_binding = {
        "user_id": current_user_id,
        "provider": provider,
        "external_id": external_id,
        "external_name": external_name,
        "source": "manual",
        "status": 1,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    }

    mappings.setdefault("bindings", []).append(new_binding)
    save_bindings_atomic(mappings)

    return {"success": True, "message": "Binding successful"}


@router.post("/users/identity/unbind")
async def unbind_external_identity(request: Request, current_user_id: str = None):
    """Manual unbinding endpoint for external identity"""
    if not current_user_id:
        raise HTTPException(status_code=401, detail="User not authenticated")

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    provider = data.get("provider")
    external_id = data.get("external_id")

    if not provider or not external_id:
        raise HTTPException(status_code=400, detail="Missing required parameters: provider, external_id")

    mappings = load_bindings()
    updated_bindings = []
    found = False

    for b in mappings.get("bindings", []):
        if (b.get("user_id") == current_user_id and b.get("provider") == provider
                and str(b.get("external_id")) == str(external_id)):
            found = True
            continue
        updated_bindings.append(b)

    if not found:
        raise HTTPException(status_code=404, detail="Binding record not found")

    mappings["bindings"] = updated_bindings
    save_bindings_atomic(mappings)

    return {"success": True, "message": "Unbinding successful"}


@router.post("/external/auto-login")
async def auto_login_by_identifier(request: Request):
    """Auto login endpoint for external systems using openid or other identifier.

    保留旧行为（兼容已有调用方），但 token 改为与账号密码登录兼容的真 token。
    """
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    provider = data.get("provider")
    openid = data.get("openid")

    if not provider:
        raise HTTPException(status_code=400, detail="Missing required parameter: provider")

    mappings_data = load_bindings()
    bindings = mappings_data.get("bindings", [])

    identifier = openid or data.get("identifier") or data.get("external_id")
    if not identifier:
        raise HTTPException(status_code=400, detail="Missing required parameter: openid or identifier")

    matched_binding = None
    for b in bindings:
        if (b.get("provider") == provider
                and str(b.get("external_id")) == str(identifier)
                and b.get("status", 0) == 1):
            matched_binding = b
            break

    if not matched_binding:
        raise HTTPException(status_code=401, detail="Identity binding not found or inactive. Please bind first.")

    user_id = matched_binding.get("user_id")

    from ..auth import create_token
    from ..user_store import get_user
    if get_user(user_id) is None:
        raise HTTPException(status_code=404, detail="Local user no longer exists")

    token = create_token(user_id, ext_provider=provider)

    return {
        "success": True,
        "message": "Auto-login successful",
        "data": {
            "token": token,
            "user_id": user_id,
            "provider": provider,
            "external_id": matched_binding.get("external_id")
        }
    }
