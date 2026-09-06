# -*- coding: utf-8 -*-
"""External Identity Authentication Router - Community Version (JSON File Storage)

Provides API endpoints for external system SSO callback, identity binding, and unbinding.

模型A（SSO 跳转）完整链路：
    登录页按钮 → GET /external/login-state（签发一次性 state + login_url）
    → 浏览器 302 到外部系统登录页 → 外部系统签名回调
    → 前端 /login/callback 落地页 → POST /external/login
    → 验签 → 验 state（一次性）→ 查绑定 / 自动建用户 → 发真 token

安全要点：
    - state 一次性（防 CSRF），文件原子写，TTL 10 分钟
    - timestamp 防重放（TTL 可配，默认 300 秒）
    - redirect 白名单：仅站内 / 开头、禁 //
    - secret 永不出现在 /systems 响应中
"""
import json
import hmac
import hashlib
import time
import os
import re
import secrets
import tempfile
import shutil
import threading
import logging
from fastapi import APIRouter, Request, HTTPException
from typing import Dict, Any

logger = logging.getLogger(__name__)

# Mapping file path and shared secret (from environment variable)
from ...constant import SYSTEM_DIR

# 与 users.json/auth.json 同一运行时数据目录（避免相对路径受 CWD 影响）
MAPPINGS_FILE = str(SYSTEM_DIR / "external_identity_mappings.json")
STATE_FILE = str(SYSTEM_DIR / "external_login_states.json")

# 与 external_identity.py 出站断言同一个 secret：外部系统验签零新依赖
EXTERNAL_SSO_SECRET = os.getenv("COAPIS_JWT_SECRET_KEY") or os.getenv("EXTERNAL_SSO_SECRET") or "default_secret_key_community"

# state 有效期（秒）：10 分钟足够完成一次人工登录跳转
STATE_TTL = 600
# 回调 timestamp 默认防重放窗口（秒），可被系统配置 sso.callback.timestamp_ttl 覆盖
DEFAULT_CALLBACK_TTL = 300

# 注意：前缀用短形式 /auth —— 顶层 api_router 已带 /api 前缀，最终 URL 为 /api/auth/...
router = APIRouter(prefix="/auth", tags=["external_auth"])

# state 内存缓存（mtime 失效），避免高频登录时反复读文件
_state_cache: Dict[str, Any] = {"mtime": -1.0, "data": {}}
_state_lock = threading.RLock()  # 可重入：_load_states 在端点持锁区间内会被再次调用


# ---------------------------------------------------------------------------
# 文件 IO（原子写，防并发覆盖）
# ---------------------------------------------------------------------------

def _atomic_write_json(path: str, data: Dict[str, Any]) -> None:
    """Atomically write a JSON file (temp file + rename)."""
    dir_name = os.path.dirname(path) or "."
    os.makedirs(dir_name, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=dir_name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        shutil.move(temp_path, path)
    except Exception:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise


def load_bindings() -> Dict[str, Any]:
    """Safely read local JSON mapping file"""
    if not os.path.exists(MAPPINGS_FILE):
        return {"bindings": []}
    with open(MAPPINGS_FILE, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {"bindings": []}


def save_bindings_atomic(mappings_data: Dict[str, Any]):
    """Atomically write back JSON file to prevent concurrent overwrite"""
    _atomic_write_json(MAPPINGS_FILE, mappings_data)


def _load_states() -> Dict[str, Any]:
    """Load login states (with mtime cache)."""
    with _state_lock:
        try:
            mtime = os.path.getmtime(STATE_FILE)
        except OSError:
            return {}
        if mtime != _state_cache["mtime"]:
            try:
                with open(STATE_FILE, 'r', encoding='utf-8') as f:
                    _state_cache["data"] = json.load(f)
                _state_cache["mtime"] = mtime
            except (OSError, json.JSONDecodeError):
                return {}
        return _state_cache["data"]


def _save_states(states: Dict[str, Any]) -> None:
    """Persist states, dropping expired entries, atomically."""
    now = time.time()
    clean = {k: v for k, v in states.items()
             if isinstance(v, dict) and v.get("exp", 0) > now}
    _atomic_write_json(STATE_FILE, clean)


def find_binding_by_external(mappings_data: Dict[str, Any], provider: str, external_id: str) -> Dict[str, Any]:
    """Find matching binding record in memory"""
    for b in mappings_data.get("bindings", []):
        if (b.get("provider") == provider
                and str(b.get("external_id")) == str(external_id)
                and b.get("status") == 1):
            return b
    return None


# ---------------------------------------------------------------------------
# 签名 / state 工具
# ---------------------------------------------------------------------------

def _resolve_system_secret(system: Dict[str, Any]) -> str:
    """Per-system secret if configured, else the global shared secret."""
    if system.get("shared_secret"):
        return system["shared_secret"]
    return EXTERNAL_SSO_SECRET


def _render_template(template: str, values: Dict[str, Any]) -> str:
    """Fill ``{placeholder}`` tokens in *template* from *values*.

    Unknown placeholders are left as-is (so misconfigured templates are
    visible rather than silently emptied).
    """
    if not template:
        return ""

    def _sub(m):
        key = m.group(1)
        return str(values.get(key, m.group(0)))

    return re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", _sub, template)


def _validate_redirect(redirect: str) -> str:
    """Redirect 白名单：仅站内 / 开头，禁协议相对 //（防开放重定向）。"""
    if not redirect:
        return "/chat"
    if redirect.startswith("/") and not redirect.startswith("//"):
        return redirect
    return "/chat"


def _generate_username(prefix: str, padding: int, seq_start: int) -> str:
    """Generate the next auto username: ``<prefix>_<seq>``（零填充）。

    序号 = 现有用户名中匹配 ``<prefix>_<数字>`` 的最大序号 + 1 —— 单一事实源，
    永不漂移，无需计数器字段。碰撞时继续递增直到唯一。
    """
    from ..user_store import get_user

    seq = max(seq_start, 1)
    candidate = f"{prefix}_{seq:0{max(padding, 1)}d}"
    while get_user(candidate) is not None:
        seq += 1
        candidate = f"{prefix}_{seq:0{max(padding, 1)}d}"
    return candidate


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
    """外部系统 SSO 回调登录（模型A 核心端点）。

    请求体：
        provider（可选，缺省时从 state 解析）, external_id, timestamp, signature, state,
        external_name（可选，用于显示名）, redirect（可选，站内路径）

    流程：state 只读探测（解析 provider）→ 防重放 → 验签 → 消费 state
    （一次性）→ 查绑定 →（未绑定 + auto_create → 自动建用户 + 写绑定）
    → 发真 token（与账号密码登录完全兼容）。
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
    from ..user_store import get_user, create_user, touch_last_login
    from ..auth import create_token

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
    secret = _resolve_system_secret(system)
    sign_string = callback_cfg.get("sign_string") or ""
    if not sign_string:
        sign_string = f"provider={provider}&external_id={external_id}&timestamp={timestamp}"
    else:
        sign_string = _render_template(sign_string, {
            "provider": provider,
            "external_id": external_id,
            "timestamp": str(timestamp),
        })
    expected_signature = hmac.new(
        secret.encode('utf-8'),
        sign_string.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_signature, signature):
        raise HTTPException(status_code=403, detail="Invalid signature")

    # 4. 消费 state（一次性，验签通过才消费）
    states.pop(state, None)
    _save_states(states)

    # 5. 查绑定 / 自动建用户
    external_name = str(data.get("external_name") or "").strip()
    mappings = load_bindings()
    binding = find_binding_by_external(mappings, provider, external_id)

    auto_created = False
    first_login = False

    if binding:
        username = binding["user_id"]
        existing_user = get_user(username)
        if existing_user is None:
            raise HTTPException(status_code=404, detail="Local user no longer exists")
        # 首次登录判定必须在 touch_last_login 之前（与主登录一致）
        first_login = existing_user.get("last_login") is None
        # 记录本次登录（审计字段）
        binding["last_login_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        binding["login_count"] = int(binding.get("login_count") or 0) + 1
        if external_name and not binding.get("external_name"):
            binding["external_name"] = external_name
        save_bindings_atomic(mappings)
        touch_last_login(username)
    else:
        um = system.get("user_mapping") or {}
        if not um.get("auto_create"):
            raise HTTPException(
                status_code=403,
                detail="未绑定该外部系统账号，且系统未开启自动创建用户。请联系管理员绑定。",
            )
        prefix = um.get("username_prefix") or provider
        try:
            padding = int(um.get("seq_padding") or 4)
        except (TypeError, ValueError):
            padding = 4
        try:
            seq_start = int(um.get("seq_start") or 1)
        except (TypeError, ValueError):
            seq_start = 1

        username = _generate_username(prefix, padding, seq_start)

        # 显示名来源
        source = um.get("display_name_source", "external_name")
        if source == "external_name":
            display_name = external_name or username
        elif source == "external_id":
            display_name = str(external_id)
        else:
            display_name = username

        default_role = um.get("default_role") or "user"
        random_password = secrets.token_urlsafe(16)

        if not create_user(username, random_password,
                           display_name=display_name, role=default_role):
            raise HTTPException(status_code=500, detail="Failed to create user")

        # SQLite user_system 同步（与 register 一致，best-effort；密码由 service 侧散列）
        try:
            from ...user_system.database import get_db
            from ...user_system.service import create_user as create_user_sql
            from ...user_system.models import UserCreate
            get_db()  # 初始化 DB（lazy 建表）
            create_user_sql(UserCreate(
                username=username,
                password=random_password,
                display_name=display_name,
                role=default_role,
            ))
        except Exception as e:
            logger.warning("Failed to sync auto-created user %s to SQLite: %s", username, e)

        # 初始化用户工作区（agent/skills/workflows）— best-effort
        default_agent_id = f"user:{username}"
        try:
            from ..user_provisioning import init_user_workspace
            agent_id = init_user_workspace(username, display_name=display_name, request=request)
            if agent_id:
                default_agent_id = agent_id
        except Exception as e:
            logger.error("Failed to init workspace for auto-created user %s: %s", username, e)

        # 写绑定
        now_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        mappings.setdefault("bindings", []).append({
            "user_id": username,
            "provider": provider,
            "external_id": external_id,
            "external_name": external_name or None,
            "source": "auto",
            "status": 1,
            "created_at": now_str,
            "last_login_at": now_str,
            "login_count": 1,
        })
        save_bindings_atomic(mappings)

        touch_last_login(username)
        auto_created = True
        first_login = True
        logger.info(
            "Auto-created external user %s (provider=%s, external_id=%s, display_name=%s, role=%s)",
            username, provider, external_id, display_name, default_role,
        )

    # 6. 发真 token（与账号密码登录完全兼容）
    user_info = get_user(username)
    if user_info is None:
        raise HTTPException(status_code=404, detail="Local user no longer exists")

    token = create_token(username)

    # 审计
    try:
        from .audit import _append_audit_entry
        _append_audit_entry({
            "timestamp": time.time(),
            "event_type": "auth",
            "action": "login_success",
            "user_id": username,
            "source": f"external:{provider}",
            "detail": f"外部系统登录成功 (auto_created={auto_created})",
        })
    except Exception:
        pass

    display_name = user_info.get("display_name") or username
    default_agent_id = f"user:{username}"

    return {
        "success": True,
        "token": token,
        "username": username,
        "display_name": display_name,
        "first_login": first_login,
        "default_agent_id": default_agent_id,
        "auto_created": auto_created,
        "redirect": _validate_redirect(data.get("redirect") or "/chat"),
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

    cred = system.get("credential") or {}
    api_cfg = cred.get("api") or {}
    login_url = api_cfg.get("url", "")
    if not login_url:
        raise HTTPException(status_code=500, detail="External system has no login API URL configured")

    method = (api_cfg.get("method") or "POST").upper()
    content_type = api_cfg.get("content_type") or "application/json"
    headers = dict(api_cfg.get("headers") or {})
    headers["Content-Type"] = content_type

    # 渲染 body 模板（{username} {password}）
    body_tpl = api_cfg.get("body") or {}
    body = {k: _render_template(str(v), {"username": username, "password": password})
            for k, v in body_tpl.items()}

    # 调外部系统登录 API
    import aiohttp
    timeout = aiohttp.ClientTimeout(total=int(cred.get("timeout") or 15))
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.request(method, login_url, headers=headers, json=body) as resp:
                resp_data = await resp.json()
    except aiohttp.ClientError as e:
        logger.error("Credential login: external API request failed: %s", e)
        raise HTTPException(status_code=502, detail=f"External system unreachable: {e}")
    except Exception as e:
        logger.error("Credential login: external API error: %s", e)
        raise HTTPException(status_code=502, detail=f"External system request failed: {e}")

    # 解析响应
    resp_cfg = cred.get("response") or {}
    success_field = resp_cfg.get("success_field", "code")
    success_value = resp_cfg.get("success_value", 0)
    error_field = resp_cfg.get("error_field", "msg")
    openid_field = resp_cfg.get("openid_field", "")
    name_field = resp_cfg.get("name_field", "")

    actual_code = _resolve_nested_field(resp_data, success_field)
    if actual_code != success_value:
        err_msg = _resolve_nested_field(resp_data, error_field) or str(resp_data)
        raise HTTPException(status_code=401, detail=f"External system login failed: {err_msg}")

    external_id = _resolve_nested_field(resp_data, openid_field)
    if external_id is None:
        raise HTTPException(status_code=500, detail="External system did not return an identifier")
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

    # 查绑定 / 自动建用户（逻辑与 SSO 登录一致）
    mappings = load_bindings()
    binding = find_binding_by_external(mappings, provider, external_id)

    auto_created = False
    first_login = False

    if binding:
        local_username = binding["user_id"]
        existing_user = get_user(local_username)
        if existing_user is None:
            raise HTTPException(status_code=404, detail="Local user no longer exists")
        first_login = existing_user.get("last_login") is None
        binding["last_login_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        binding["login_count"] = int(binding.get("login_count") or 0) + 1
        if external_name and not binding.get("external_name"):
            binding["external_name"] = external_name
        save_bindings_atomic(mappings)
        touch_last_login(local_username)
        # 如果 display_name 还是自动设的（等于 username），用 external_name 更新
        if external_name and existing_user.get("display_name") == local_username:
            try:
                from ..user_store import update_user
                update_user(local_username, display_name=external_name)
                logger.info("Credential login: updated display_name for %s to '%s'", local_username, external_name)
            except Exception as e:
                logger.warning("Credential login: failed to update display_name: %s", e)
    else:
        um = system.get("user_mapping") or {}
        if not um.get("auto_create"):
            raise HTTPException(
                status_code=403,
                detail="未绑定该外部系统账号，且系统未开启自动创建用户。请联系管理员绑定。",
            )
        prefix = um.get("username_prefix") or provider
        try:
            padding = int(um.get("seq_padding") or 4)
        except (TypeError, ValueError):
            padding = 4
        try:
            seq_start = int(um.get("seq_start") or 1)
        except (TypeError, ValueError):
            seq_start = 1

        local_username = _generate_username(prefix, padding, seq_start)

        source = um.get("display_name_source", "external_name")
        if source == "external_name":
            display_name = external_name or local_username
        elif source == "external_id":
            display_name = external_id
        else:
            display_name = local_username

        default_role = um.get("default_role") or "user"
        random_password = secrets.token_urlsafe(16)

        if not create_user(local_username, random_password,
                           display_name=display_name, role=default_role):
            raise HTTPException(status_code=500, detail="Failed to create user")

        # SQLite user_system 同步
        try:
            from ...user_system.database import get_db
            from ...user_system.service import create_user as create_user_sql
            from ...user_system.models import UserCreate
            get_db()
            create_user_sql(UserCreate(
                username=local_username,
                password=random_password,
                display_name=display_name,
                role=default_role,
            ))
        except Exception as e:
            logger.warning("Failed to sync auto-created user %s to SQLite: %s", local_username, e)

        # 初始化用户工作区
        try:
            from ..user_provisioning import init_user_workspace
            init_user_workspace(local_username, display_name=display_name, request=request)
        except Exception as e:
            logger.error("Failed to init workspace for auto-created user %s: %s", local_username, e)

        now_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        mappings.setdefault("bindings", []).append({
            "user_id": local_username,
            "provider": provider,
            "external_id": external_id,
            "external_name": external_name or None,
            "source": "auto",
            "status": 1,
            "created_at": now_str,
            "last_login_at": now_str,
            "login_count": 1,
        })
        save_bindings_atomic(mappings)

        touch_last_login(local_username)
        auto_created = True
        first_login = True
        logger.info(
            "Credential login: auto-created user %s (provider=%s, external_id=%s)",
            local_username, provider, external_id,
        )

    # 发真 token
    user_info = get_user(local_username)
    if user_info is None:
        raise HTTPException(status_code=404, detail="Local user no longer exists")

    token = create_token(local_username)

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

    token = create_token(user_id)

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
