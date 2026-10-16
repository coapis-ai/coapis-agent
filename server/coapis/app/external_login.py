# -*- coding: utf-8 -*-
"""外部系统直接跳转登录（旧契约 · 薄适配器）。

契约（外部门户 302 直投，OA 侧零改造）::

    GET  /api/external/login?token=<HMAC>&username=<本地登录名>&display_name=<姓名>&redirect=/chat
    POST /api/external/login   {token, username, display_name}

本文件**只**负责旧契约特有的两件事：

1. 验签 ``token = HMAC-SHA256(secret, username)``（密钥来源由核心统一解析）；
2. 按请求方法返回 HTML（注入前端 AuthStorage 所需的登录态）或 JSON。

登录业务 —— 查绑定 → 死绑定自愈 → 建号 → 写绑定 → 发 token → 审计 ——
**只有一份**，在 :mod:`coapis.app.external_login_core`；模型A（SSO 回调）与
模型B（凭证直登）调用的是同一份代码，本入口不再自写一套。

⚠️ 本端点在生产是主登录路径（近 7 天 56 次命中，2026-10-15 仍在用），不可下线。
   新流程见 ``routers/external_auth.py`` 的 ``/api/auth/external/login``。

与迁移前的行为差异（均为收敛到唯一真源的结果，已记录于
tech_docs/外部登录双实现审计.md）：
    - 建号统一走核心：密码由随机值生成（旧实现写死 ``SSO_DEFAULT_PASSWORD``），
      ``password_set_by_user=0`` 不变 → 用户可走"首次设置密码"；
    - 建号统一带 ``muga_key``（用户隔离文件空间租户键）与月度配额；
    - 登录会更新 ``last_login_at``（旧实现的 ``update_last_login`` 导入恒失败，
      实际从未更新过登录时间）；
    - 新增：登录成功写入/刷新外部身份绑定（旧实现完全不写绑定，导致外部身份
      与本地账号无法对账）；
    - token 带 ``ext_provider``（前端头部显示登录来源；旧 token 无该字段，兼容）。
"""
import logging
import time
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from . import external_login_core as core

logger = logging.getLogger(__name__)

# 前缀用短形式 /external —— 顶层 api_router 已带 /api 前缀，最终 URL 为 /api/external/...
router = APIRouter(prefix="/external", tags=["external-login"])
external_login_router = router  # 别名，供 routers/__init__.py 导入


class SSOLoginRequest(BaseModel):
    """SSO 登录请求"""
    token: str           # 外部系统签名
    username: str        # 用户名
    display_name: Optional[str] = None  # 显示名称
    provider: Optional[str] = None      # 外部系统 ID（可选，见 _resolve_system）
    external_id: Optional[str] = None   # 外部系统人员 ID（可选，缺省用 username）
    redirect: Optional[str] = None      # 站内跳转路径


class SSOLoginResponse(BaseModel):
    """SSO 登录响应"""
    token: str           # CoApis token
    username: str        # 用户名
    display_name: str    # 显示名称
    is_new_user: bool    # 是否新用户
    default_agent_id: str = ""  # 默认智能体ID
    redirect: str = "/chat"


# ---------------------------------------------------------------------------
# 外部系统解析（旧契约通常不传 provider，需要确定性回退）
# ---------------------------------------------------------------------------

def resolve_system(
    provider_param: Optional[str],
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """把旧契约入参解析成 ``(provider_id, system)``。

    规则（确定性，不猜测）：
    1. 显式传 ``provider`` → 查该系统；查不到直接报错（不静默降级）。
    2. 未传 provider 且**恰好配置 1 个启用系统** → 用它（生产实况）。
    3. 未传 provider 且配置 0 个或多个 → ``(None, None)``：登录照常可用，
       但**不写绑定**（外部身份无法与本地账号对账），记 warning 提示门户加参。
    """
    from .external_identity import get_system_by_id

    if provider_param:
        system = get_system_by_id(provider_param)
        if system is None:
            raise HTTPException(
                status_code=404,
                detail=f"External system '{provider_param}' not configured",
            )
        if system.get("status", 1) != 1:
            raise HTTPException(status_code=403, detail="External system is disabled")
        return provider_param, system

    try:
        from .external_identity import _load_systems
        enabled = _load_systems()
    except Exception as exc:  # pragma: no cover - 配置读取异常时按无配置处理
        logger.warning("resolve_system: 读取外部系统配置失败: %s", exc)
        return None, None

    if len(enabled) == 1:
        return str(enabled[0].get("provider_id")), enabled[0]
    if len(enabled) > 1:
        logger.warning(
            "resolve_system: 配置了 %d 个外部系统且请求未带 provider，本次登录不写绑定"
            "（请外部门户在跳转链接中加 &provider=<ID> 以启用身份绑定）", len(enabled),
        )
    return None, None


# ---------------------------------------------------------------------------
# 登录主流程（GET / POST 共用一份）
# ---------------------------------------------------------------------------

async def perform_login(
    request: Request,
    *,
    token: str,
    username: str,
    display_name: str = "",
    redirect: str = "",
    provider: Optional[str] = None,
    external_id: Optional[str] = None,
    action: str = "legacy_login_success",
) -> Dict[str, Any]:
    """验签 → 核心解析身份 → 发 token。

    验签失败 401；缺参数由调用方（query/body 校验）负责。
    业务失败（未绑定且禁止建号 / 建号失败）由核心抛 HTTPException。
    """
    username = (username or "").strip()
    token = (token or "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username is required")
    if not token:
        raise HTTPException(status_code=401, detail="Invalid SSO token")

    provider_id, system = resolve_system(provider)

    secret, secret_source = core.resolve_login_secret(system, "legacy")
    if system is None:
        logger.info(
            "legacy login: 未解析到外部系统，密钥来源=%s user=%s", secret_source, username,
        )

    if not core.verify_signature(secret, username, token):
        logger.warning(
            "Invalid SSO token for user: %s (secret source=%s)", username, secret_source,
        )
        raise HTTPException(status_code=401, detail="Invalid SSO token")

    _note_replay(username, token)

    outcome = core.resolve_external_identity(
        provider=provider_id,
        system=system,
        external_id=external_id or username,
        external_name=(display_name or "").strip(),
        request=request,
        fixed_username=username,
        allow_match=False,
    )

    issued = core.finish_login(
        username=outcome["username"],
        provider=provider_id,
        auto_created=outcome["auto_created"],
        redirect=redirect or "/chat",
        action=action,
    )

    if outcome.get("split_with"):
        logger.warning(
            "账号分裂检测：user=%s 与 user=%s 在 provider=%s 下同名（%s）——"
            "同一真人存在两个账号，需数据治理合并（本次登录未改动任何数据）",
            outcome["username"], outcome["split_with"], provider_id, display_name,
        )

    return {
        **issued,
        "is_new_user": outcome["auto_created"],
        "first_login": outcome["first_login"],
        "binding_source": outcome["source"],
        "split_with": outcome.get("split_with"),
    }


# 轻量重放观测：旧契约无 timestamp，不能硬拦，只告警
_recent_tokens: Dict[str, Tuple[str, float]] = {}
_REPLAY_WINDOW = 60


def _note_replay(username: str, token: str) -> None:
    now = time.time()
    prev = _recent_tokens.get(username)
    if prev and prev[0] == token and (now - prev[1]) < _REPLAY_WINDOW:
        logger.warning(
            "疑似重放：user=%s 在 %.0fs 内使用同一 token 登录（旧契约无 timestamp，仅告警"
            "不拦截；建议外部门户跳转链接加 &timestamp= 与 &provider=）",
            username, now - prev[1],
        )
    _recent_tokens[username] = (token, now)


# ---------------------------------------------------------------------------
# GET：浏览器 302 直投（生产主路径）
# ---------------------------------------------------------------------------

@router.get("/login")
async def sso_login_get(
    request: Request,
    token: str,
    username: str,
    display_name: Optional[str] = None,
    redirect: Optional[str] = None,
    provider: Optional[str] = None,
    external_id: Optional[str] = None,
):
    """SSO 登录 (GET 方式，用于浏览器跳转)

    使用示例：
    https://coapis.example.com/api/external/login?token=签名&username=zhangsan&display_name=张三&redirect=/

    外部系统跳转流程：
    1. 用户在外部系统登录成功
    2. 外部系统生成签名和URL
    3. 浏览器跳转到此URL
    4. 自动设置登录状态并跳转到 redirect 页面
    """
    result = await perform_login(
        request,
        token=token,
        username=username,
        display_name=display_name or "",
        redirect=redirect or "",
        provider=provider,
        external_id=external_id,
    )

    coapis_token = result["token"]
    username = result["username"]
    default_agent_id = result["default_agent_id"]
    display_name = result["display_name"]
    # 用核心校验过的站内跳转路径（旧实现直接嵌入原始 query 值，未传时会得到
    # 字符串 "None" 并跳转 /None —— 顺带修掉）
    redirect_url = result["redirect"]

    # 使用 AuthStorage 统一管理登录状态
    # 外部登录默认不"记住我"，只保存到 sessionStorage
    html = f"""
    <!DOCTYPE html>
    <html>
    <head><title>SSO Login</title></head>
    <body>
    <script>
        // 动态加载 AuthStorage 模块（如果存在）
        // 如果不存在，使用简化版本
        const AuthStorage = {{
            login: function(token, username, options) {{
                options = options || {{}};
                const remember = options.remember || false;
                const defaultAgentId = options.default_agent_id || ('user:' + username);
                
                // 始终保存到 sessionStorage（当前标签页）
                sessionStorage.setItem('coapis_auth_token', token);
                sessionStorage.setItem('coapis_current_username', username);

                // 保存用户作用域的 agent 存储（user:username）
                const agentStorageKey = 'coapis-agent-storage-' + username;
                const lastUsedAgentKey = 'coapis-last-used-agent-' + username;
                const agentState = JSON.stringify({{
                    state: {{ selectedAgent: defaultAgentId }},
                    version: 0
                }});
                sessionStorage.setItem(agentStorageKey, agentState);
                localStorage.setItem(agentStorageKey, agentState);
                localStorage.setItem(lastUsedAgentKey, defaultAgentId);

                // 如果勾选"记住我"，同时保存到 localStorage
                if (remember) {{
                    localStorage.setItem('coapis_auth_token', token);
                    localStorage.setItem('coapis_current_username', username);
                    
                    // 保存到账号列表
                    const accounts = JSON.parse(localStorage.getItem('coapis_saved_accounts') || '[]');
                    const account = {{
                        username: username,
                        token: token,
                        display_name: options.display_name || username,
                        last_login: new Date().toISOString()
                    }};
                    const index = accounts.findIndex(a => a.username === username);
                    if (index >= 0) {{
                        accounts[index] = account;
                    }} else {{
                        accounts.push(account);
                    }}
                    localStorage.setItem('coapis_saved_accounts', JSON.stringify(accounts));
                }}
                
                // 同时更新全局标识
                localStorage.setItem('coapis-current-username', username);
                
                // 设置全局变量
                window.currentUserId = username;
                window.currentChannel = '';
            }},
            
            logout: function(clearAll) {{
                sessionStorage.removeItem('coapis_auth_token');
                sessionStorage.removeItem('coapis_current_username');
                
                if (clearAll) {{
                    localStorage.removeItem('coapis_auth_token');
                    localStorage.removeItem('coapis_current_username');
                    localStorage.removeItem('coapis-current-username');
                    localStorage.removeItem('coapis_saved_accounts');
                }}
                
                // 清除所有 session 相关数据
                Object.keys(sessionStorage).forEach(key => {{
                    if (key.startsWith('chat_') || key.startsWith('session_') || key.startsWith('agent_')) {{
                        sessionStorage.removeItem(key);
                    }}
                }});
            }}
        }};
        
        // 1. 清除旧的登录状态（不清除记住的账号）
        AuthStorage.logout(false);
        
        // 2. 使用 AuthStorage 登录（默认不记住）
        AuthStorage.login('{coapis_token}', '{username}', {{
            remember: false,
            display_name: '{display_name}',
            default_agent_id: '{default_agent_id}'
        }});
        
        // 2.1 通知父窗口（SSO 弹窗模式）
        try {{
            if (window.opener && !window.opener.closed) {{
                window.opener.postMessage({{
                    type: 'coapis-sso-login',
                    token: '{coapis_token}',
                    username: '{username}',
                    display_name: '{display_name}',
                    redirect: '{redirect_url}'
                }}, '*');
                setTimeout(function() {{ window.close(); }}, 300);
            }}
        }} catch (e) {{}}
        
        // 3. 强制刷新并跳转（使用 replace 避免回退）
        const redirect = '{redirect_url}' || '/chat';
        if (redirect && redirect !== '/') {{
            window.location.replace(redirect);
        }} else {{
            window.location.replace('/chat');
        }}
    </script>
    <p>登录中，请稍候...</p>
    </body>
    </html>
    """

    return HTMLResponse(content=html)


# ---------------------------------------------------------------------------
# POST：JSON 契约（服务端/前端调用）
# ---------------------------------------------------------------------------

@router.post("/login", response_model=SSOLoginResponse)
async def sso_login(request: Request, body: SSOLoginRequest):
    """SSO 登录

    外部系统调用流程：
    1. 用户在外部系统登录成功
    2. 外部系统生成签名: HMAC-SHA256(SECRET, username)
    3. 调用此接口，传入签名和用户信息
    4. 获取 CoApis token，跳转到 CoApis 前端
    """
    result = await perform_login(
        request,
        token=body.token,
        username=body.username,
        display_name=body.display_name or "",
        redirect=body.redirect or "",
        provider=body.provider,
        external_id=body.external_id,
        action="legacy_login_success_json",
    )

    return SSOLoginResponse(
        token=result["token"],
        username=result["username"],
        display_name=result["display_name"],
        is_new_user=result["is_new_user"],
        default_agent_id=result["default_agent_id"],
        redirect=result["redirect"],
    )
