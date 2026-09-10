# -*- coding: utf-8 -*-
"""外部系统 Token 透传（pass_through）支持。

当外部系统不支持 CoApis 的签名断言（X-CoApis-* headers）时，采用"透传外部
token"方案：登录时把外部系统签发的 access/refresh token 存进用户绑定记录，
出站（MCP/HTTP）时把当前用户的 token 以 ``Authorization: Bearer <token>``
注入给外部系统——零改造外部系统。

核心机制：
    1. 登录时（凭证直登成功）：从登录响应按 external_token.access_field 等
       字段提取 token，写入绑定记录（明文）。
    2. 出站时：读绑定里的 token，判断是否"快过期"，必要时用 refresh_token
       调外部系统刷新端点换新 token 并写回绑定。
    3. 刷新时机：``该不该刷 = (expires_at - now) < max(refresh_margin_sec,
       refresh_ratio × token_lifetime)``（比例与绝对下限取较大者，提前刷）。
    4. 并发安全：同一 (provider, external_id) 的刷新用 asyncio.Lock 串行化，
       拿到锁后双检是否已被别的协程刷新。

配置（系统 credential.external_token）：
    {
        "mode": "pass_through",
        "access_field": "data.accessToken",
        "refresh_token_field": "data.refreshToken",
        "expires_in_field": "data.expiresTime",   # 毫秒/秒 epoch 或相对秒数或 ISO
        "refresh": {
            "url": ".../refresh-token",
            "method": "POST",
            "placement": "query",                 # "query" | "body"
            "token_param": "refreshToken"
        },
        "refresh_ratio": 0.05,                    # 提前刷新比例（默认 5%）
        "refresh_margin_sec": 60                  # 提前刷新绝对下限（默认 60s）
    }
"""
import asyncio
import json
import re
import time
import threading
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 纯工具（内联，避免懒导入 routers 包触发整包依赖链）
# ---------------------------------------------------------------------------

def _resolve_nested_field(data: Any, path: str) -> Any:
    """按点路径取嵌套字段，如 ``data.accessToken``。"""
    if not path:
        return None
    current = data
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _render_template(template: str, values: Dict[str, Any]) -> str:
    """填 ``{placeholder}``；未知占位符原样保留。"""
    if not template:
        return ""

    def _sub(m):
        key = m.group(1)
        return str(values.get(key, m.group(0)))

    return re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", _sub, template)


# ---------------------------------------------------------------------------
# 绑定记录读写（懒加载 external_auth 的绑定 IO，避免模块加载期循环导入）
# ---------------------------------------------------------------------------

def _bindings_io():
    """返回 (load_bindings, save_bindings_atomic, find_binding_by_external)。"""
    from .routers.external_auth import (
        load_bindings,
        save_bindings_atomic,
        find_binding_by_external,
    )
    return load_bindings, save_bindings_atomic, find_binding_by_external


# ---------------------------------------------------------------------------
# 时间解析
# ---------------------------------------------------------------------------

def _parse_iso_to_ts(iso: Optional[str]) -> Optional[float]:
    """UTC ISO 字符串 → epoch 秒；无法解析返回 None。"""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _parse_expires(field: str, resp_data: Dict[str, Any]) -> Optional[str]:
    """解析外部 token 过期时间为 UTC ISO 字符串；无法解析返回 None。

    兼容三种常见形态：
      - 毫秒 epoch（如 1788942875725）
      - 秒 epoch（如 1788942875）
      - 相对秒数（expires_in，如 43200）
    也兼容 ISO 字符串。
    """
    if not field:
        return None
    raw = _resolve_nested_field(resp_data, field)
    if raw is None or raw == "":
        return None
    # 先尝试 ISO 字符串
    if isinstance(raw, str):
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (ValueError, TypeError):
            pass
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    now = time.time()
    if val > 1e12:          # 毫秒 epoch
        ts = val / 1000.0
    elif val > 1e9:         # 秒 epoch
        ts = val
    elif val > 0:           # 相对秒数（expires_in）
        ts = now + val
    else:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _needs_refresh(expires_at: Optional[str], updated_at: Optional[str],
                   et: Dict[str, Any]) -> bool:
    """token 是否需要刷新。

    规则：``(expires_at - now) < max(refresh_margin_sec, refresh_ratio × lifetime)``
    其中 lifetime = expires_at - updated_at。
    """
    if not expires_at:
        return True  # 无过期信息 → 保守：视为需要刷新（若能刷新）
    ts = _parse_iso_to_ts(expires_at)
    if ts is None:
        return True
    remaining = ts - time.time()
    if remaining <= 0:
        return True  # 已过期
    ratio = float(et.get("refresh_ratio") or 0.05)
    try:
        margin = int(et.get("refresh_margin_sec") or 60)
    except (TypeError, ValueError):
        margin = 60
    threshold = margin
    up = _parse_iso_to_ts(updated_at)
    if up is not None:
        lifetime = ts - up
        if lifetime > 0:
            threshold = max(margin, ratio * lifetime)
    return remaining < threshold


# ---------------------------------------------------------------------------
# 登录时存 token
# ---------------------------------------------------------------------------

def extract_login_tokens(system: Dict[str, Any],
                         resp_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """从登录响应提取外部 token。

    仅当 mode=pass_through 且响应里确实拿到 access token 时返回
    {token, refresh_token, expires_at, token_updated_at}；否则返回 None。
    """
    cred = system.get("credential") or {}
    et = cred.get("external_token") or {}
    if et.get("mode") != "pass_through":
        return None
    access = _resolve_nested_field(resp_data, et.get("access_field", ""))
    if not access:
        logger.warning(
            "external_token pass_through: 登录响应未取到 access token (access_field=%s)",
            et.get("access_field"),
        )
        return None
    rt = _resolve_nested_field(resp_data, et.get("refresh_token_field", ""))
    return {
        "token": str(access),
        "refresh_token": str(rt or ""),
        "expires_at": _parse_expires(et.get("expires_in_field", ""), resp_data),
        "token_updated_at": _now_iso(),
    }


def store_login_tokens(provider: str, external_id: str,
                       tokens: Dict[str, Any]) -> bool:
    """把登录拿到的外部 token 写进 (provider, external_id) 的绑定记录。"""
    load, save, find = _bindings_io()
    mappings = load()
    binding = find(mappings, provider, external_id)
    if binding is None:
        logger.warning("store_login_tokens: 未找到绑定 provider=%s external_id=%s",
                       provider, external_id)
        return False
    binding.update(tokens)
    save(mappings)
    logger.info(
        "store_login_tokens: 已存外部 token provider=%s external_id=%s expires_at=%s",
        provider, external_id, tokens.get("expires_at"),
    )
    return True


# ---------------------------------------------------------------------------
# 刷新（per-(provider, external_id) 并发锁）
# ---------------------------------------------------------------------------

_refresh_locks: Dict[str, asyncio.Lock] = {}
_refresh_locks_guard = threading.Lock()

# 刷新冷却：key=(provider:external_id) -> 最近一次刷新尝试的 epoch 秒。
# 防止外部系统未返回过期时间（expires_at 为空 → 每次都被判定"需刷新"）时，
# 每个出站请求都打一次刷新端点。已知过期（ts<=now）时不套用冷却，确保真过期必刷。
REFRESH_COOLDOWN_SEC = 30.0
_last_refresh_attempt: Dict[str, float] = {}


def _get_refresh_lock(key: str) -> asyncio.Lock:
    with _refresh_locks_guard:
        lock = _refresh_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _refresh_locks[key] = lock
        return lock


async def _refresh_external_token(system: Dict[str, Any],
                                  refresh_token: str) -> Dict[str, Any]:
    """调外部系统刷新端点，返回新 token 字典；失败抛 Exception。"""
    import aiohttp
    cred = system.get("credential") or {}
    et = cred.get("external_token") or {}
    refresh_cfg = et.get("refresh") or {}
    url = (refresh_cfg.get("url") or "").strip()
    if not url:
        raise ValueError("未配置刷新端点 URL")
    method = (refresh_cfg.get("method") or "POST").upper()
    placement = (refresh_cfg.get("placement") or "query").strip().lower()
    token_param = (refresh_cfg.get("token_param") or "refreshToken").strip()

    params = None
    data = None
    if placement == "query":
        params = {token_param: refresh_token}
    else:
        # body 模式：支持模板 {refresh_token}；无模板则用 {token_param: rt}
        body_raw = refresh_cfg.get("body")
        if isinstance(body_raw, dict):
                data = {str(k): _render_template(str(v), {"refresh_token": refresh_token})
                    for k, v in body_raw.items()}
        else:
            data = {token_param: refresh_token}

    timeout = aiohttp.ClientTimeout(total=int(et.get("refresh_timeout") or 15))
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.request(method, url, params=params, json=data) as resp:
            text = await resp.text()
    try:
        resp_data = json.loads(text) if text.strip() else {}
    except json.JSONDecodeError as e:
        raise ValueError(f"刷新端点响应不是 JSON（HTTP {resp.status}）：{text[:200]}") from e

    access = _resolve_nested_field(resp_data, et.get("access_field", ""))
    if not access:
        raise ValueError(f"刷新端点未返回 access token (access_field={et.get('access_field')}): {text[:200]}")
    new_rt = _resolve_nested_field(resp_data, et.get("refresh_token_field", ""))
    return {
        "token": str(access),
        "refresh_token": str(new_rt or "") or refresh_token,  # 未换则沿用旧 rt
        "expires_at": _parse_expires(et.get("expires_in_field", ""), resp_data),
        "token_updated_at": _now_iso(),
    }


def _update_binding_tokens(provider: str, external_id: str,
                           tokens: Dict[str, Any]) -> None:
    load, save, find = _bindings_io()
    mappings = load()
    binding = find(mappings, provider, external_id)
    if binding is None:
        return
    binding.update(tokens)
    save(mappings)
    logger.info("刷新外部 token 成功 provider=%s external_id=%s expires_at=%s",
                provider, external_id, tokens.get("expires_at"))


# ---------------------------------------------------------------------------
# 出站：取有效 token（必要时刷新）
# ---------------------------------------------------------------------------

async def get_valid_passthrough_token(system: Dict[str, Any],
                                      username: str,
                                      binding: Dict[str, Any]) -> str:
    """返回当前有效的外部 token；必要时用 refresh_token 刷新并写回绑定。

    无 token 且无 refresh_token / 已过期且无法刷新时抛 IdentityError。
    """
    from .external_identity import IdentityError
    cred = system.get("credential") or {}
    et = cred.get("external_token") or {}
    refresh_cfg = et.get("refresh") or {}
    refresh_url = (refresh_cfg.get("url") or "").strip()
    system_name = system.get("name") or system.get("provider_id") or "?"

    token = str(binding.get("token") or "")
    rt = str(binding.get("refresh_token") or "")
    expires_at = binding.get("expires_at")
    updated_at = binding.get("token_updated_at")

    # 既无 token 又无 refresh token → 无法透传，提示重登
    if not token and not rt:
        raise IdentityError(
            "no_token",
            f"用户 {username} 未持有外部系统 [{system_name}] 的有效凭证，"
            f"请重新登录以获取 token。",
        )

    if not _needs_refresh(expires_at, updated_at, et):
        return token  # 还在有效期内

    # 需要刷新：无刷新端点 → 降级（还没过期就用旧 token，过期了拒绝）
    if not refresh_url:
        ts = _parse_iso_to_ts(expires_at)
        if token and ts is not None and ts > time.time():
            logger.warning("外部 token 快过期但无刷新端点，降级使用旧 token (provider=%s)",
                           system.get("provider_id"))
            return token
        raise IdentityError(
            "token_expired",
            f"外部系统 [{system_name}] 的凭证已过期且未配置刷新端点，请重新登录。",
        )

    # 加锁刷新（防并发），拿锁后双检
    lock_key = f"{system.get('provider_id')}:{binding.get('external_id')}"
    async with _get_refresh_lock(lock_key):
        # 双检：重新读绑定，可能已被别的协程刷新
        load, _, find = _bindings_io()
        fresh = find(load(), system.get("provider_id"), binding.get("external_id"))
        if fresh:
            token = str(fresh.get("token") or "")
            rt = str(fresh.get("refresh_token") or "")
            expires_at = fresh.get("expires_at")
            updated_at = fresh.get("token_updated_at")
        if token and not _needs_refresh(expires_at, updated_at, et):
            return token  # 已被刷新，直接用

        if not rt:
            ts = _parse_iso_to_ts(expires_at)
            if token and ts is not None and ts > time.time():
                return token
            raise IdentityError(
                "no_token",
                f"外部系统 [{system_name}] 的凭证已过期且无可用刷新令牌，请重新登录。",
            )

        # 刷新冷却：最近刚尝试过刷新、且当前 token 并未"已知过期" → 不重复刷新，
        # 直接复用当前 token。防止外部系统未返回过期时间（expires_at 为空 → 每次
        # 都被判定"需刷新"）时每个出站请求都打一次刷新端点。已知过期（ts<=now）
        # 不套用冷却，确保真过期必刷。
        now = time.time()
        ts = _parse_iso_to_ts(expires_at)
        known_expired = ts is not None and ts <= now
        last_attempt = _last_refresh_attempt.get(lock_key, 0.0)
        if (not known_expired) and token and (now - last_attempt) < REFRESH_COOLDOWN_SEC:
            logger.debug(
                "refresh cooldown active for %s (last=%.0fs ago), reusing current token",
                lock_key, now - last_attempt,
            )
            return token

        _last_refresh_attempt[lock_key] = time.time()
        try:
            new_tokens = await _refresh_external_token(system, rt)
        except Exception as e:
            # 刷新失败：若旧 token 还没真正过期（ts 在将来），降级用它；否则拒绝
            if token and ts is not None and ts > time.time():
                logger.warning("刷新外部 token 失败，降级使用旧 token: %s", e)
                return token
            raise IdentityError(
                "token_refresh_failed",
                f"外部系统 [{system_name}] 的 token 刷新失败且旧 token 已过期：{e}",
            )
        _update_binding_tokens(system.get("provider_id"), binding.get("external_id"), new_tokens)
        return new_tokens["token"]


async def passthrough_headers(url: str, system: Dict[str, Any],
                              source: str = "mcp") -> Dict[str, str]:
    """透传模式出站头：校验绑定后返回 ``Authorization: Bearer <token>``。"""
    from .external_identity import IdentityError, get_identity_username, find_binding
    provider_id = system.get("provider_id", "")
    username = get_identity_username()
    if not username:
        raise IdentityError("no_user", f"无法确定当前用户，外部系统出站调用已拒绝 (URL={url})")
    binding = find_binding(username, provider_id)
    if not binding:
        raise IdentityError(
            "unbound",
            f"用户 {username} 未绑定外部系统 [{system.get('name', provider_id)}]，"
            f"出站调用已拒绝。",
        )
    token = await get_valid_passthrough_token(system, username, binding)
    return {"Authorization": f"Bearer {token}"}
