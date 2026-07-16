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
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head><title>SSO Login</title></head>
    <body>
    <script>
        // 存储 token 到 localStorage
        localStorage.setItem('coapis_token', '{coapis_token}');
        localStorage.setItem('coapis_username', '{username}');
        // 跳转到目标页面
        window.location.href = '{redirect or "/"}';
    </script>
    <p>登录中...</p>
    </body>
    </html>
    """
    
    return HTMLResponse(content=html)
