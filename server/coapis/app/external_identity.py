# -*- coding: utf-8 -*-
"""Outbound identity assertion — the single decision layer.

任何 CoApis 出站访问外部系统（MCP 工具调用 / C2A 链接跳转）时，身份断言的
**唯一决策点**都在这里：

- URL 匹配：出站 URL 命中哪个已配置外部系统（provider.base_urls 前缀匹配）
- 绑定查询：当前用户是否绑定了该外部系统的账号（openid）
- 签名生成：HMAC-SHA256 身份断言（与入站登录回调同一算法/同一 secret）

两个载体：
- 服务端（MCP）→ HTTP 头：X-CoApis-Identity / X-CoApis-OpenId /
  X-CoApis-Timestamp / X-CoApis-Sign
- 浏览器（C2A 链接）→ URL 签名参数：?caid=<username>&cas=<ts>.<sig>

不命中任何已配置外部系统的 URL → 原样放行，不注入任何东西。
命中但用户未绑定 → 明确拒绝（IdentityError），安全默认。

身份通过 ContextVar（任务级，无竞态）传递，入口只需 set 一次：
- runner.query_handler（覆盖 web/企微/cron 所有 agent 执行）
- routers/mcp.py（MCP API 直调）
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
import time
from contextvars import ContextVar
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# 身份上下文（ContextVar，asyncio 任务级隔离）
# ──────────────────────────────────────────────────────────────────────

_CURRENT_IDENTITY_USER: ContextVar[Optional[str]] = ContextVar(
    "coapis_identity_user", default=None
)


def set_identity_username(username: Optional[str]) -> None:
    """Set the identity username for the current async task.

    Call once at the request/agent entry point; every MCP call made
    within this task tree will carry this identity.
    """
    _CURRENT_IDENTITY_USER.set(username)


def get_identity_username() -> Optional[str]:
    """Resolve the current identity username.

    Priority: this module's ContextVar → session_context fallback
    (console channel sets that one) → None.
    """
    username = _CURRENT_IDENTITY_USER.get()
    if username:
        return username
    try:
        from ...config.session_context import get_current_user_id

        return get_current_user_id()
    except Exception:  # pragma: no cover - defensive
        return None


# ──────────────────────────────────────────────────────────────────────
# 配置与数据
# ──────────────────────────────────────────────────────────────────────

from ..constant import SYSTEM_DIR

# 与 users.json/auth.json 同一运行时数据目录（避免相对路径受 CWD 影响）
SYSTEMS_CONFIG_FILE = str(SYSTEM_DIR / "external_systems_config.json")
MAPPINGS_FILE = str(SYSTEM_DIR / "external_identity_mappings.json")

# 与 external_auth.py 入站验签同一个 secret：外部系统验签零新依赖
EXTERNAL_SSO_SECRET = (
    os.getenv("COAPIS_JWT_SECRET_KEY")
    or os.getenv("EXTERNAL_SSO_SECRET")
    or "default_secret_key_community"
)

# 身份断言有效期（秒）。默认 60 分钟，可按系统覆盖（identity_token_ttl）。
# 外部系统验签中间件用同样的 TTL 校验 timestamp。
DEFAULT_TOKEN_TTL = 3600

HEAD_IDENTITY = "X-CoApis-Identity"
HEAD_OPENID = "X-CoApis-OpenId"
HEAD_TIMESTAMP = "X-CoApis-Timestamp"
HEAD_SIGN = "X-CoApis-Sign"

PARAM_IDENTITY = "caid"  # 浏览器载体：CoApis AIDe
PARAM_SIGN = "cas"       # 浏览器载体：CoApis AiSign


class IdentityError(Exception):
    """出站身份断言失败（带明确可转告用户的 message）。

    code 取值：
    - "no_user"   无法确定当前用户身份
    - "unbound"   用户未绑定该外部系统账号
    - "no_secret" 外部系统未配置签名密钥
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# ──────────────────────────────────────────────────────────────────────
# 配置读取（mtime 缓存，文件变更自动失效）
# ──────────────────────────────────────────────────────────────────────

class _ConfigCache:
    """Tiny mtime-based JSON file cache (thread-safe)."""

    _lock = threading.Lock()

    def __init__(self):
        self._path: Optional[str] = None
        self._mtime: float = -1.0
        self._data: Dict[str, Any] = {}

    def get(self, path: str, default: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                return default
            if self._path != path or mtime != self._mtime:
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        self._data = json.load(f)
                    self._path = path
                    self._mtime = mtime
                except (OSError, json.JSONDecodeError):
                    return default
            return self._data


_systems_cache = _ConfigCache()
_bindings_cache = _ConfigCache()


def _get_ext_store():
    """Return the enterprise external identity store, or None (community JSON)."""
    try:
        from ..foundation.repository_factory import RepositoryFactory
        if RepositoryFactory.is_initialized():
            return RepositoryFactory.get_external_identity_store()
    except (RuntimeError, ImportError, Exception):
        pass
    return None


def _load_systems() -> List[Dict[str, Any]]:
    store = _get_ext_store()
    if store:
        return [s for s in store.load_systems() if s.get("status", 1) == 1]
    data = _systems_cache.get(SYSTEMS_CONFIG_FILE, {"systems": []})
    systems = data.get("systems", [])
    return [s for s in systems if s.get("status", 1) == 1]


def _load_bindings() -> List[Dict[str, Any]]:
    store = _get_ext_store()
    if store:
        return store.load_bindings()
    data = _bindings_cache.get(MAPPINGS_FILE, {"bindings": []})
    return data.get("bindings", [])


# ──────────────────────────────────────────────────────────────────────
# URL 匹配 / 绑定查询 / secret 解析
# ──────────────────────────────────────────────────────────────────────

def find_external_system(url: str) -> Optional[Dict[str, Any]]:
    """Match an outbound URL against configured external systems.

    **Longest-prefix match**: among all (system, base_url) pairs whose base
    is a prefix of the URL, the one with the *longest* base wins.  This
    prevents a shorter base (e.g. ``https://oa.corp.com``) from shadowing a
    more specific one (e.g. ``https://oa.corp.com/finance``) when both
    belong to different systems.

    Returns the system dict, or None if the URL belongs to no configured
    system (internal / public — pass through untouched).
    """
    if not url:
        return None
    try:
        url_no_frag = url.split("#", 1)[0]
    except Exception:
        return None

    best_system: Optional[Dict[str, Any]] = None
    best_len = -1

    for system in _load_systems():
        base_urls: List[str] = system.get("base_urls") or []
        for base in base_urls:
            base = (base or "").rstrip("/")
            if not base:
                continue
            if url_no_frag == base or url_no_frag.startswith(base + "/"):
                if len(base) > best_len:
                    best_len = len(base)
                    best_system = system
    return best_system


def get_system_by_id(provider_id: str) -> Optional[Dict[str, Any]]:
    """Look up a system by provider_id (any status).

    入站登录校验用：需要区分"未配置"(None) 和 "已禁用"(status=0)。
    """
    if not provider_id:
        return None
    store = _get_ext_store()
    if store:
        return store.get_system_by_id(provider_id)
    data = _systems_cache.get(SYSTEMS_CONFIG_FILE, {"systems": []})
    for s in data.get("systems", []):
        if s.get("provider_id") == provider_id:
            return s
    return None


def find_binding(username: str, provider_id: str) -> Optional[Dict[str, Any]]:
    """Find an active binding for (username, provider)."""
    for b in _load_bindings():
        if (
            b.get("user_id") == username
            and b.get("provider") == provider_id
            and b.get("status", 0) == 1
        ):
            return b
    return None


def resolve_secret(system: Dict[str, Any]) -> str:
    """Resolve the shared secret for a system (per-system or global)."""
    if system.get("shared_secret"):
        return system["shared_secret"]
    return EXTERNAL_SSO_SECRET


def get_token_ttl(system: Optional[Dict[str, Any]]) -> int:
    if system:
        try:
            ttl = int(system.get("identity_token_ttl") or DEFAULT_TOKEN_TTL)
            return max(ttl, 60)
        except (TypeError, ValueError):
            pass
    return DEFAULT_TOKEN_TTL


# ──────────────────────────────────────────────────────────────────────
# 签名（与入站登录同一算法：HMAC-SHA256 hex）
# ──────────────────────────────────────────────────────────────────────

def build_sign_string(
    provider: str,
    external_id: str,
    username: str,
    source: str,
    timestamp: int,
) -> str:
    return (
        f"provider={provider}"
        f"&external_id={external_id}"
        f"&username={username}"
        f"&source={source}"
        f"&timestamp={timestamp}"
    )


def compute_signature(sign_string: str, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        sign_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


# ──────────────────────────────────────────────────────────────────────
# 统一决策入口
# ──────────────────────────────────────────────────────────────────────

def resolve_identity(url: str, source: str = "mcp") -> Dict[str, str]:
    """Decide + sign the identity assertion for an outbound URL.

    Returns:
        - {}                          URL 不属于任何已配置外部系统（放行）
        - {"identity": ..., "external_id": ..., "timestamp": ...,
           "signature": ..., "system": <system dict>}   需要携带身份

    Raises:
        IdentityError: 属于已配置外部系统但无法断言身份（未登录/未绑定/无密钥）
    """
    system = find_external_system(url)
    if system is None:
        return {}

    username = get_identity_username()
    if not username:
        raise IdentityError(
            "no_user",
            f"无法确定当前用户身份，不能访问外部系统 [{system.get('name', system.get('provider_id'))}]",
        )

    provider_id = system.get("provider_id", "")
    binding = find_binding(username, provider_id)
    if not binding:
        raise IdentityError(
            "unbound",
            f"用户 {username} 未绑定外部系统 [{system.get('name', provider_id)}] 的账号，"
            f"无法调用。请先在 CoApis 中绑定该外部系统账号。",
        )

    secret = resolve_secret(system)
    if not secret:
        raise IdentityError("no_secret", "外部系统未配置签名密钥")

    timestamp = int(time.time())
    external_id = str(binding.get("external_id", ""))
    signature = compute_signature(
        build_sign_string(provider_id, external_id, username, source, timestamp),
        secret,
    )

    return {
        "identity": username,
        "external_id": external_id,
        "timestamp": str(timestamp),
        "signature": signature,
        "system": system,
    }


def identity_headers(url: str, source: str = "mcp") -> Dict[str, str]:
    """HTTP 头载体（MCP 出站）。非外部系统返回 {}。"""
    identity = resolve_identity(url, source)
    if not identity:
        return {}
    return {
        HEAD_IDENTITY: identity["identity"],
        HEAD_OPENID: identity["external_id"],
        HEAD_TIMESTAMP: identity["timestamp"],
        HEAD_SIGN: f'{identity["timestamp"]}.{identity["signature"]}',
    }


def sign_url(target_url: str, source: str = "c2a_link") -> str:
    """浏览器载体（C2A 链接跳转）。

    非外部系统 URL 原样返回；外部系统 URL 追加 ?caid=..&cas=..
    （每次调用实时签名，点击即签，TTL 默认 60 分钟）。
    """
    identity = resolve_identity(target_url, source)
    if not identity:
        return target_url
    sep = "&" if "?" in target_url else "?"
    return (
        f"{target_url}{sep}{PARAM_IDENTITY}={identity['identity']}"
        f"&{PARAM_SIGN}={identity['timestamp']}.{identity['signature']}"
    )


# ──────────────────────────────────────────────────────────────────────
# httpx 层注入（MCP 出站统一拦截点）
# ──────────────────────────────────────────────────────────────────────

async def _httpx_identity_hook(request) -> None:
    """httpx request event hook: inject identity headers per request.

    非外部系统 URL → 无操作。未绑定/无身份 → 抛错阻断（安全默认），
    错误信息会一路传到工具调用结果，agent 可原样转告用户。
    """
    try:
        headers = identity_headers(str(request.url), source="mcp")
    except IdentityError as e:
        raise RuntimeError(f"外部系统身份验证失败: {e.message}") from e
    except Exception as e:  # 注入失败不应让内部流量崩溃
        logger.debug("identity injection skipped: %s", e)
        return
    for key, value in headers.items():
        request.headers[key] = value


def create_identity_httpx_client_factory():
    """MCP SDK ``httpx_client_factory``：创建的 client 自动挂身份注入 hook。

    用于 sse_client（streamable_http 在 stateful_client 里直接构造
    AsyncClient，单独加 event_hooks）。
    """
    def factory(
        headers: Optional[Dict[str, str]] = None,
        timeout: Any = None,
        auth: Any = None,
    ):
        import httpx  # local import — keep module import-light

        client_kwargs: Dict[str, Any] = {"follow_redirects": True}
        if headers is not None:
            client_kwargs["headers"] = headers
        if timeout is not None:
            client_kwargs["timeout"] = timeout
        else:
            client_kwargs["timeout"] = httpx.Timeout(
                30.0, read=60 * 5
            )
        if auth is not None:
            client_kwargs["auth"] = auth
        client_kwargs["event_hooks"] = {"request": [_httpx_identity_hook]}
        return httpx.AsyncClient(**client_kwargs)

    return factory
