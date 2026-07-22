# -*- coding: utf-8 -*-
"""SSO 单点登录 - 外部系统自动接入"""
import hmac
import hashlib
import logging
import secrets
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Optional

from .auth import create_token
from .user_store import create_user, get_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/external", tags=["external-login"])
external_login_router = router  # 别名，供 routers/__init__.py 导入


class SSOLoginRequest(BaseModel):
    """SSO 登录请求"""
    token: str           # 外部系统签名
    username: str        # 用户名
    display_name: Optional[str] = None  # 显示名称


class SSOLoginResponse(BaseModel):
    """SSO 登录响应"""
    token: str           # CoApis token
    username: str        # 用户名
    display_name: str    # 显示名称
    is_new_user: bool    # 是否新用户


def _get_sso_secret() -> str:
    """获取 SSO 密钥"""
    import os
    secret = os.environ.get("COAPIS_SSO_SECRET", "")
    if not secret:
        # 开发环境默认值（生产环境必须设置）
        secret = "dev-sso-secret-change-in-production"
        logger.warning("Using default SSO secret. Set COAPIS_SSO_SECRET for production!")
    return secret


def _verify_sso_token(token: str, username: str) -> bool:
    """验证 SSO 签名
    
    签名算法: HMAC-SHA256(SECRET, username)
    """
    if not token or not username:
        return False
    
    secret = _get_sso_secret()
    expected = hmac.new(
        secret.encode(),
        username.encode(),
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(token, expected)


@router.post("/login", response_model=SSOLoginResponse)
async def sso_login(request: Request, body: SSOLoginRequest):
    """SSO 登录
    
    外部系统调用流程：
    1. 用户在外部系统登录成功
    2. 外部系统生成签名: HMAC-SHA256(SECRET, username)
    3. 调用此接口，传入签名和用户信息
    4. 获取 CoApis token，跳转到 CoApis 前端
    """
    # 1. 验证签名
    if not _verify_sso_token(body.token, body.username):
        raise HTTPException(status_code=401, detail="Invalid SSO token")
    
    # 2. 检查/创建用户
    user = get_user(body.username)
    is_new_user = False
    
    if not user:
        # 自动创建用户（随机密码，用户通过 SSO 登录）
        random_password = secrets.token_urlsafe(32)
        created = create_user(
            username=body.username,
            password=random_password,
            display_name=body.display_name or body.username,
            role="user",
        )
        
        if not created:
            raise HTTPException(status_code=500, detail="Failed to create user")
        
        user = get_user(body.username)
        is_new_user = True
        logger.info(f"SSO auto-created user: {body.username}")
    
    # 3. 更新登录时间（如果函数存在）
    try:
        from .user_store import update_last_login
        update_last_login(body.username)
    except ImportError:
        pass  # 旧版本可能没有此函数
    
    # 4. 生成 CoApis token (7天有效)
    coapis_token = create_token(body.username, expiry_seconds=86400 * 7)
    
    return SSOLoginResponse(
        token=coapis_token,
        username=body.username,
        display_name=user["display_name"],
        is_new_user=is_new_user,
    )


@router.get("/login")
async def sso_login_get(
    request: Request,
    token: str,
    username: str,
    display_name: Optional[str] = None,
    redirect: Optional[str] = None,
):
    """SSO 登录 (GET 方式，用于浏览器跳转)
    
    使用示例：
    https://coapis.example.com/api/sso/login?token=签名&username=zhangsan&display_name=张三&redirect=/
    
    外部系统跳转流程：
    1. 用户在外部系统登录成功
    2. 外部系统生成签名和URL
    3. 浏览器跳转到此URL
    4. 自动设置登录状态并跳转到 redirect 页面
    """
    # 1. 验证签名
    if not _verify_sso_token(token, username):
        raise HTTPException(status_code=401, detail="Invalid SSO token")
    
    # 2. 检查/创建用户
    user = get_user(username)
    is_new_user = False
    
    if not user:
        random_password = secrets.token_urlsafe(32)
        created = create_user(
            username=username,
            password=random_password,
            display_name=display_name or username,
            role="user",
        )
        
        if not created:
            raise HTTPException(status_code=500, detail="Failed to create user")
        
        user = get_user(username)
        is_new_user = True
        logger.info(f"SSO auto-created user: {username}")
    
    # 3. 更新登录时间（如果函数存在）
    try:
        from .user_store import update_last_login
        update_last_login(username)
    except ImportError:
        pass
    
    # 4. 生成 token
    coapis_token = create_token(username, expiry_seconds=86400 * 7)
    
    # 5. 构建响应（设置 cookie 或返回 HTML）
    from fastapi.responses import HTMLResponse
    
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
                
                // 始终保存到 sessionStorage（当前标签页）
                sessionStorage.setItem('coapis_auth_token', token);
                sessionStorage.setItem('coapis_current_username', username);
                
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
            display_name: '{display_name or username}'
        }});
        
        // 3. 强制刷新并跳转（使用 replace 避免回退）
        const redirect = '{redirect}' || '/chat';
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
