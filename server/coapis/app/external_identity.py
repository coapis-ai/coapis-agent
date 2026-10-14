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

MCP 出站的身份**按请求携带**（见 RequestIdentityRegistry）：MCP 的 HTTP
发送任务是连接期创建、跨用户共享的常驻任务，不继承调用方的 ContextVar；
共享连接上并发多用户时，把身份存在 client 实例上必然串号。因此发送侧按
JSON-RPC 请求 id 登记调用方，注入侧按同一 id 反查——隔离单位是"请求"。
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
from typing import Any, Callable, Dict, List, Optional, Tuple

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

# 出站认证模式（系统级 auth_mode）二态：
# - optional（默认）：有身份就注入，无身份 → 裸放行（容错，让业务系统自行判定）
# - none          ：不注入任何身份头，裸放行（纯公开）
#
# 设计取舍：不做"无身份硬阻断"——是否放行由外部业务系统自行决定（它才是
# 业务规则的权威）。CoApis 的职责是"有身份就尽力注入"，注入不了就降级放行。
AUTH_MODES = ("optional", "none")
DEFAULT_AUTH_MODE = "optional"

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


def resolve_auth_mode(system: Optional[Dict[str, Any]]) -> str:
    """系统的出站认证模式（optional/none），默认 optional。

    非法值或旧值 ``required`` 回退 optional（降级放行）；旧配置无 ``auth_mode``
    字段 → optional，零破坏、无需迁移。
    """
    if not system:
        return DEFAULT_AUTH_MODE
    mode = str(system.get("auth_mode") or DEFAULT_AUTH_MODE).lower()
    return mode if mode in AUTH_MODES else DEFAULT_AUTH_MODE


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


async def outbound_headers(url: str, source: str = "mcp") -> Dict[str, str]:
    """统一的出站身份头（异步）。两层分流：

    1. 系统级 ``auth_mode``（optional/none）决定是否注入与容错：
       - ``none``     → 不注入、不阻断（返回 {}）；
       - ``optional``（默认）→ 有身份就注入，注入失败（IdentityError）→ 降级裸放行（返回 {}）。
    2. 注入方式按系统 ``credential.external_token.mode`` 分流：
       - ``pass_through`` → 透传外部 token（必要时异步刷新），
         返回 ``Authorization: Bearer <token>``（外部系统零改造）；
       - 其他（``signature`` / 未配置）→ 签名断言（原同步逻辑）。

    非外部系统 URL 返回 {}。
    """
    system = find_external_system(url)
    if system is None:
        return {}

    auth_mode = resolve_auth_mode(system)
    if auth_mode == "none":
        return {}

    async def _inject() -> Dict[str, str]:
        et = (system.get("credential") or {}).get("external_token") or {}
        if et.get("mode") == "pass_through":
            from .external_token import passthrough_headers
            return await passthrough_headers(url, system, source)
        return identity_headers(url, source)

    # optional（唯一非 non-none 模式）：有身份就注入，注入失败（无用户/未绑定/无密钥/
    # token 失效）→ 降级裸放行（是否放行由外部业务系统自行判定，CoApis 不硬拦）。
    # passthrough 无 token 时返回 None，统一归一为 {}。
    try:
        headers = await _inject()
        return headers or {}
    except IdentityError:
        # 容错降级：无身份/未绑定/token 失效 → 裸放行（由外部系统自行决定）
        return {}


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

async def _httpx_identity_core(request) -> None:
    """身份注入钩子核心逻辑（依据当前上下文身份解析，按 mode 分流）。

    非外部系统 URL → 无操作。

    降级放行策略（不做硬阻断）：
    - ``outbound_headers`` 在 optional 模式下已内部降级——任何身份注入失败
      （无用户 / 未绑定 / 无密钥 / token 失效）都返回 ``{}``，请求裸发，由
      外部业务系统自行判定是否放行。CoApis 只负责"有身份就尽力注入"。
    - 正常路径下不会抛异常；此处 except 仅作防御性兜底，任何注入异常一律
      降级放行，绝不让内部流量（如 MCP 连接握手）因身份问题崩溃。

    透传模式（external_token.mode=pass_through）会走异步刷新逻辑，故此处用
    ``outbound_headers``（按 mode 分流）。
    """
    try:
        headers = await outbound_headers(str(request.url), source="mcp")
    except Exception as e:  # 注入失败一律降级放行，不阻断业务请求
        logger.warning("[IDENTITY_DEBUG] core inject FAILED url=%s err=%s",
                       getattr(request, "url", ""), e)
        return
    logger.warning("[IDENTITY_DEBUG] core inject url=%s headers=%s",
                   getattr(request, "url", ""),
                   {k: (v[:12] + "..." if isinstance(v, str) and len(v) > 16 else v)
                    for k, v in headers.items()})
    for key, value in headers.items():
        request.headers[key] = value


async def _httpx_identity_hook(request) -> None:
    """全局 httpx 请求钩子（兼容旧入口，等价于核心逻辑）。"""
    await _httpx_identity_core(request)




# ──────────────────────────────────────────────────────────────────────
# 请求级身份登记（B2：身份随请求走，不随连接走）
# ──────────────────────────────────────────────────────────────────────


class RequestIdentityRegistry:
    """JSON-RPC 请求 id → 调用方用户名 的短寿命登记表。

    为什么需要它：MCP 的 HTTP 发送任务（streamable_http 的 post_writer、
    sse 的 post_writer）是**连接期创建的常驻任务**，不继承触发调用的业务
    任务里的 ContextVar；而共享连接上同时可能有多个用户的请求在飞。把身份
    存在 client 实例属性上 = 单格子竞态（后写者赢）。

    正确单位是**请求**：
      - 发送侧（业务任务，ContextVar 可用）：`ClientSession.send_request`
        在调用方任务里把 SessionMessage 投进 write_stream → 我们的代理流
        按 JSON-RPC id 登记调用方身份；
      - 注入侧（每请求独立任务）：httpx 请求钩子从请求体里取回同一个 id，
        反查身份，在本任务内置入 ContextVar 后注入头，随即释放。

    于是身份与请求一一对应，没有任何跨用户共享的可变格子；连接仍是共享的
    （1 条连接多路复用），并发不受影响。
    """

    def __init__(self, max_age: float = 900.0, max_entries: int = 4096) -> None:
        self._owners: Dict[Any, Tuple[Optional[str], float]] = {}
        self._max_age = max_age
        self._max_entries = max_entries

    def tag(self, request_id: Any, username: Optional[str]) -> None:
        """登记（在调用方任务里调用）。username 为 None 表示无归属（如握手）。"""
        now = time.monotonic()
        self._owners[request_id] = (username, now)
        self._sweep(now)

    def lookup(self, request_id: Any) -> Optional[str]:
        rec = self._owners.get(request_id)
        if rec is None:
            return None
        if time.monotonic() - rec[1] > self._max_age:
            self._owners.pop(request_id, None)
            return None
        return rec[0]

    def release(self, request_id: Any) -> None:
        self._owners.pop(request_id, None)

    def clear(self) -> None:
        self._owners.clear()

    def _sweep(self, now: float) -> None:
        owners = self._owners
        if len(owners) <= self._max_entries:
            if len(owners) > 64:
                for rid, (_, ts) in list(owners.items()):
                    if now - ts > self._max_age:
                        owners.pop(rid, None)
            return
        for rid, (_, ts) in list(owners.items()):
            if now - ts > self._max_age:
                owners.pop(rid, None)
        while len(owners) > self._max_entries:
            oldest = min(owners.items(), key=lambda kv: kv[1][1])[0]
            owners.pop(oldest, None)

    def __len__(self) -> int:
        return len(self._owners)


def jsonrpc_id_of_request(request: Any) -> Optional[Any]:
    """从 httpx 请求体里取 JSON-RPC 请求 id（取不到返回 None）。

    通知类消息（notifications/initialized 等）没有 id → None。
    """
    try:
        if getattr(request, "method", "") != "POST":
            return None
        content = request.content
        if not content or b'"id"' not in content:
            return None
        payload = json.loads(content)
        if not isinstance(payload, dict):
            return None
        rid = payload.get("id")
        if isinstance(rid, bool) or not isinstance(rid, (int, str)):
            return None
        return rid
    except Exception:  # pragma: no cover - 防御
        return None


def make_request_identity_hook(
    registry: RequestIdentityRegistry,
) -> Callable[..., Any]:
    """按请求隔离身份的 httpx 请求钩子（MCP 出站唯一注入点）。

    运行在发送任务里（每请求一个独立任务），ContextVar 天然隔离；身份从
    registry 按请求 id 反查得到，不读任何共享格子。

    非外部系统 URL → 直接返回（内网 MCP 流量的零成本快路径，连 body 都不解析）。
    """

    async def hook(request: Any) -> None:
        url = str(getattr(request, "url", ""))
        if find_external_system(url) is None:
            return  # 不属于任何已配置外部系统：原样放行
        rid = jsonrpc_id_of_request(request)
        if rid is None:
            logger.debug(
                "[IDENTITY] 无 JSON-RPC id 的外部请求（通知类）→ 裸放行 url=%s",
                url,
            )
            return
        username = registry.lookup(rid)
        if not username:
            # 握手/无用户上下文：由外部业务系统自行判定（与 optional 模式一致）
            logger.warning(
                "[IDENTITY] 请求 id=%s 无调用方身份（握手期/无用户上下文）"
                "→ 裸放行 url=%s",
                rid,
                url,
            )
            return
        token = _CURRENT_IDENTITY_USER.set(username)
        try:
            await _httpx_identity_core(request)
        finally:
            _CURRENT_IDENTITY_USER.reset(token)
            registry.release(rid)

    return hook


def create_identity_httpx_client_factory(
    *extra_request_hooks,
    identity_registry: Optional[RequestIdentityRegistry] = None,
):
    """MCP SDK ``httpx_client_factory``：创建的 client 自动挂身份注入 hook。

    用于 sse_client（streamable_http 在 stateful_client 里直接构造
    AsyncClient，单独加 event_hooks）。

    ``extra_request_hooks``：附加的请求钩子（如 MCP 访问日志钩子），
    排在身份注入之后，保证身份头先就位。

    ``identity_registry``：该连接的请求级身份登记表（B2 正路）；为 None 时
    退回全局钩子（按当前任务 ContextVar 注入，仅适用于无共享连接的调用）。
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
        identity_hook = (
            make_request_identity_hook(identity_registry)
            if identity_registry is not None
            else _httpx_identity_hook
        )
        client_kwargs["event_hooks"] = {
            "request": [identity_hook, *extra_request_hooks]
        }
        return httpx.AsyncClient(**client_kwargs)

    return factory
