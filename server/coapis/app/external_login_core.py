# -*- coding: utf-8 -*-
"""入站外部登录核心 —— 同一能力的唯一真源（Single Source of Truth）。

背景（tech_docs/外部登录双实现审计.md）：
入站外部登录曾有两套并行实现 —— ``app/external_login.py``（旧，生产在用）
与 ``app/routers/external_auth.py``（新，功能更全）。两份各写了密钥解析、
验签、建用户、发 token，导致：

* 维护只流向新实现，生产在用的旧实现冻结在 2026-08-07；
* 两条建号路径产出字段不同的用户记录（旧路径有 muga_key，新路径没有）；
* 同一真人分裂成两个账号（生产实证：刘良旭 = zrsz_154 与 oa_0001）。

本模块是**唯一**的入站登录实现：验签之后的
「查绑定 → 死绑定自愈 → 匹配已有账号 → 建号 → 写绑定 → 发 token → 审计」
全部只在这里有一份。两个入口（旧 ``/api/external/login`` 与新
``/api/auth/external/login``）都只是**薄适配器**：负责各自的验签与响应形态
（HTML / JSON），业务逻辑一律调用本模块。

调用约定::

    # 新流程（模型A SSO 回调）：外部身份 → 本地账号（可匹配、可生成用户名）
    core.resolve_external_identity(
        provider=..., system=..., external_id=..., external_name=...,
        request=request, fixed_username=None, allow_match=True)

    # 旧流程（门户直投）：外部系统直接给出本地登录名，用户名逐字使用
    core.resolve_external_identity(
        provider=..., system=..., external_id=..., external_name=...,
        request=request, fixed_username=username, allow_match=False)

安全要点（与迁移前一致）：
    - state 一次性（防 CSRF），原子写，TTL 600 秒
    - timestamp 防重放（TTL 可配，默认 300 秒）
    - redirect 白名单：仅站内 / 开头、禁协议相对 //
    - secret 永不出现在 /systems 响应中
    - 匹配歧义（同名 ≥2 未绑定）→ 拒绝，绝不猜测
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import shutil
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

from ..constant import SYSTEM_DIR

# ---------------------------------------------------------------------------
# 常量与运行时路径
# ---------------------------------------------------------------------------

MAPPINGS_FILE = str(SYSTEM_DIR / "external_identity_mappings.json")
STATE_FILE = str(SYSTEM_DIR / "external_login_states.json")

# 与 external_identity.py 出站断言同一个 secret：外部系统验签零新依赖
EXTERNAL_SSO_SECRET = (
    os.getenv("COAPIS_JWT_SECRET_KEY")
    or os.getenv("EXTERNAL_SSO_SECRET")
    or "default_secret_key_community"
)

# 旧契约（门户直投）专用密钥环境变量与开发默认值
LEGACY_SSO_SECRET_ENV = "COAPIS_SSO_SECRET"
LEGACY_SSO_DEV_DEFAULT = "dev-sso-secret-change-in-production"

# state 有效期（秒）：10 分钟足够完成一次人工登录跳转
STATE_TTL = 600
# 回调 timestamp 默认防重放窗口（秒），可被系统配置 sso.callback.timestamp_ttl 覆盖
DEFAULT_CALLBACK_TTL = 300
# 登录 token 有效期（秒）：7 天
LOGIN_TOKEN_TTL = 86400 * 7

_state_cache: Dict[str, Any] = {"mtime": -1.0, "data": {}}
_state_lock = threading.RLock()  # 可重入：_load_states 在端点持锁区间内会被再次调用


# ---------------------------------------------------------------------------
# 文件 IO（原子写，防并发覆盖）
# ---------------------------------------------------------------------------

def atomic_write_json(path: str, data: Dict[str, Any]) -> None:
    """Atomically write a JSON file (temp file + rename)."""
    dir_name = os.path.dirname(path) or "."
    os.makedirs(dir_name, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=dir_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        shutil.move(temp_path, path)
    except Exception:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise


# 迁移期别名（旧代码/测试沿用下划线名）
_atomic_write_json = atomic_write_json


def get_ext_store():
    """Return the enterprise external identity store, or None (community JSON)."""
    try:
        from ..foundation.repository_factory import RepositoryFactory
        if RepositoryFactory.is_initialized():
            return RepositoryFactory.get_external_identity_store()
    except Exception:  # pragma: no cover - 企业版未启用时正常路径
        pass
    return None


_get_ext_store = get_ext_store


def load_bindings() -> Dict[str, Any]:
    """Safely read the binding store (enterprise store, else local JSON)."""
    store = get_ext_store()
    if store:
        return {"bindings": store.load_bindings()}
    if not os.path.exists(MAPPINGS_FILE):
        return {"bindings": []}
    with open(MAPPINGS_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {"bindings": []}


def save_bindings_atomic(mappings_data: Dict[str, Any]) -> None:
    """Persist bindings atomically to prevent concurrent overwrite."""
    store = get_ext_store()
    if store:
        store.save_bindings(mappings_data.get("bindings", []))
        return
    atomic_write_json(MAPPINGS_FILE, mappings_data)


def load_states() -> Dict[str, Any]:
    """Load login states (with mtime cache)."""
    with _state_lock:
        try:
            mtime = os.path.getmtime(STATE_FILE)
        except OSError:
            return {}
        if mtime != _state_cache["mtime"]:
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    _state_cache["data"] = json.load(f)
                _state_cache["mtime"] = mtime
            except (OSError, json.JSONDecodeError):
                return {}
        return _state_cache["data"]


def save_states(states: Dict[str, Any]) -> None:
    """Persist states, dropping expired entries, atomically."""
    now = time.time()
    clean = {
        k: v for k, v in states.items()
        if isinstance(v, dict) and v.get("exp", 0) > now
    }
    atomic_write_json(STATE_FILE, clean)


_load_states = load_states
_save_states = save_states


def find_binding_by_external(
    mappings_data: Dict[str, Any], provider: str, external_id: Any,
) -> Optional[Dict[str, Any]]:
    """Find the active binding for an external identity."""
    for b in mappings_data.get("bindings", []):
        if (b.get("provider") == provider
                and str(b.get("external_id")) == str(external_id)
                and str(b.get("status", 1)) == "1"):
            return b
    return None


# ---------------------------------------------------------------------------
# 密钥 / 模板 / 校验工具
# ---------------------------------------------------------------------------

def resolve_login_secret(
    system: Optional[Dict[str, Any]] = None,
    scheme: str = "model_a",
) -> Tuple[str, str]:
    """入站登录验签密钥的**唯一**解析入口（返回 ``(secret, source)``）。

    两套外部签名契约各有密钥来源， precedence 只在这里定义一次：

    ``scheme="model_a"``（新契约：``provider=..&external_id=..&timestamp=..``）
        系统配置 ``shared_secret`` → 全局 ``EXTERNAL_SSO_SECRET``

    ``scheme="legacy"``（旧契约：``HMAC(secret, username)``，生产主登录路径）
        系统配置 ``shared_secret`` → 环境变量 ``COAPIS_SSO_SECRET``
        → 全局 ``EXTERNAL_SSO_SECRET`` → 开发默认值（告警）

    返回 source 供调用方记日志：密钥来源不一致是排障第一线索。
    """
    if system and system.get("shared_secret"):
        return system["shared_secret"], "system_shared_secret"

    if scheme == "legacy":
        env_secret = os.getenv("COAPIS_SSO_SECRET", "")
        if env_secret:
            return env_secret, "env_COAPIS_SSO_SECRET"
        if EXTERNAL_SSO_SECRET != "default_secret_key_community":
            return EXTERNAL_SSO_SECRET, "env_global"
        logger.warning(
            "使用开发默认 SSO 密钥验签外部登录 —— 生产环境必须设置 COAPIS_SSO_SECRET"
        )
        return LEGACY_SSO_DEV_DEFAULT, "dev_default"

    return EXTERNAL_SSO_SECRET, "env_global"


def resolve_secret(system: Optional[Dict[str, Any]]) -> str:
    """Per-system secret if configured, else the global shared secret (模型A 契约)。"""
    return resolve_login_secret(system, "model_a")[0]


def sign_hmac(secret: str, payload: str) -> str:
    """HMAC-SHA256 hex digest — the one signature primitive for inbound login."""
    return hmac.new(
        secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256,
    ).hexdigest()


def verify_signature(secret: str, payload: str, signature: Any) -> bool:
    """Constant-time signature comparison."""
    if not signature:
        return False
    return hmac.compare_digest(sign_hmac(secret, payload), str(signature))


def render_template(template: str, values: Dict[str, Any]) -> str:
    """Fill ``{placeholder}`` tokens in *template* from *values*.

    Unknown placeholders are left as-is (so misconfigured templates are
    visible rather than silently emptied).
    """
    if not template:
        return ""

    def _sub(m):
        return str(values.get(m.group(1), m.group(0)))

    return re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", _sub, template)


def validate_redirect(redirect: Any) -> str:
    """Redirect 白名单：仅站内 / 开头，禁协议相对 //（防开放重定向）。"""
    if not redirect:
        return "/chat"
    if redirect.startswith("/") and not redirect.startswith("//"):
        return redirect
    return "/chat"


def sanitize_external_id(external_id: Any) -> Optional[str]:
    """从外部 ID 提取可用作用户名片段的标识。

    保留字母/数字/下划线/CJK/连字符，其余替换为 ``_``。
    不可用（清洗后为空）时返回 None → 调用方回退旧序号规则。

    统一规则：所有建号路径都用"前缀 + 外部ID"命名，保证同一外部系统同一人
    在任何入口进来都是同一个 AI 账号（binding 命中复用）。
    """
    v = str(external_id or "").strip()
    if not v:
        return None
    out = re.sub(r"[^\w-]", "_", v).strip("_")[:64].rstrip("_")
    return out or None


_sanitize_external_id = sanitize_external_id
_render_template = render_template
_validate_redirect = validate_redirect
_resolve_system_secret = resolve_secret


def norm_display_name(name: Any) -> str:
    """显示名归一化：NFKC + 去首尾空白 + 小写 + 压缩内部空白。"""
    import unicodedata

    if not name:
        return ""
    s = unicodedata.normalize("NFKC", str(name)).strip().lower()
    return " ".join(s.split())


_norm_display_name = norm_display_name


# ---------------------------------------------------------------------------
# 账号匹配（治分身账号）
# ---------------------------------------------------------------------------

def find_local_user_by_username(candidates: List[str]) -> Optional[str]:
    """大小写不敏感：在本地用户中查找用户名匹配任一 *candidates* 的用户。"""
    from .user_store import list_users

    norm = {str(c).strip().lower() for c in candidates if c and str(c).strip()}
    if not norm:
        return None
    for u in list_users():
        key = u.get("username")
        if key and str(key).strip().lower() in norm:
            return str(u["username"])
    return None


def try_match_existing_local_user(
    um: Dict[str, Any], external_id: Any, provider: str,
) -> Optional[str]:
    """自动建用户前，按确定性身份查找已有本地用户（大小写不敏感）。

    治本规则：外部身份的本地账号映射只认 **前缀_外部ID** 这一个确定性键
    （与自动建用户命名同源：同一系统同一人恒得同账号）。
    不使用输入登录名/姓名做主匹配——输入是易变值，用登录名匹配会让同一
    外部身份在不同输入下落到不同本地账号（分身账号）。

    match_existing 默认 True（未配置 = 开）；False 时跳过匹配直接建用户。
    旧配置 match_by 已废弃（无论配什么都只按 前缀_外部ID 匹配）。
    """
    if um.get("match_existing", True) is False:
        return None
    prefix = (str(um.get("username_prefix") or "")).strip() or provider
    ext = sanitize_external_id(external_id)
    if not prefix or not ext:
        return None
    return find_local_user_by_username([f"{prefix}_{ext}"])


def try_match_by_display_name(
    um: Dict[str, Any], external_name: str,
) -> Tuple[Optional[str], bool]:
    """自动建用户前，按"显示名"收养已有本地账号（治分身账号之根）。

    external_name 必须由已认证的外部系统签发（SSO 回调直送 / 模型B 登录 API
    返回值），可信方可收养；用户表单输入的登录名永不参与匹配。

    严格防歧义规则：
    - 只考虑**尚未绑定任何外部系统**的本地账号（绝不抢占已绑定账号）；
    - 恰好 1 个命中 → ``(username, False)``，收养之；
    - 0 个命中 → ``(None, False)``，照常走自动建用户；
    - ≥2 个命中 → ``(None, True)``，调用方必须拒绝（403），绝不猜测。
    """
    if um.get("match_existing", True) is False:
        return None, False
    if um.get("match_display_name", True) is False:
        return None, False
    target = norm_display_name(external_name)
    if not target:
        return None, False

    from .user_store import list_users

    bound_users = {
        str(b.get("user_id"))
        for b in load_bindings().get("bindings", [])
        if str(b.get("status", 1)) == "1"
    }
    hits = [
        str(u["username"])
        for u in list_users()
        if norm_display_name(u.get("display_name")) == target
        and str(u.get("username")) not in bound_users
    ]
    if len(hits) == 1:
        return hits[0], False
    if len(hits) > 1:
        return None, True
    return None, False


def detect_account_split(
    provider: str, username: str, display_name: str,
) -> Optional[str]:
    """只读探测：同一 provider 下是否存在同名的**其他**已绑定账号。

    生产实证存在分身（刘良旭 = zrsz_154 与 oa_0001）。本函数**不改任何数据**，
    只把分裂暴露到日志/响应，供数据治理决策。

    返回分身账号的用户名；无分身返回 None。
    """
    target = norm_display_name(display_name)
    if not target:
        return None
    for b in load_bindings().get("bindings", []):
        if str(b.get("status", 1)) != "1":
            continue
        if b.get("provider") != provider:
            continue
        other = str(b.get("user_id") or "")
        if not other or other == str(username):
            continue
        if norm_display_name(b.get("external_name") or b.get("display_name")) == target:
            return other
    return None


# ---------------------------------------------------------------------------
# 建号（唯一建号入口）
# ---------------------------------------------------------------------------

def create_local_user(
    username: str,
    display_name: str,
    role: str = "user",
    request: Any = None,
) -> bool:
    """建号唯一入口。

    统一走 ``user_system.service.create_user`` —— 它是唯一会写入
    ``token_quota_monthly`` 与 ``muga_key``（用户隔离文件空间租户键）的路径。
    旧实现走 ``user_store.create_user`` 会漏掉这两个字段（生产实证：12 个
    新流程建的账号 muga_key 为 NULL）。

    已存在 → True（幂等）。工作区初始化 best-effort。
    """
    from .user_store import get_user

    if get_user(username) is not None:
        return True

    dn = display_name or username
    random_password = secrets.token_urlsafe(16)

    from ..user_system.service import create_user as create_user_in_db
    from ..user_system.models import UserCreate

    try:
        create_user_in_db(UserCreate(
            username=username,
            password=random_password,
            display_name=dn,
            role=role,
        ))
    except ValueError as e:
        # 并发下已存在 → 视为成功；其余为真失败
        if "already exists" in str(e):
            return get_user(username) is not None
        logger.error("create_local_user failed for %s: %s", username, e)
        return False
    except Exception as e:
        logger.error("create_local_user failed for %s: %s", username, e, exc_info=True)
        return False

    _init_workspace_best_effort(username, dn, request)
    logger.info("Created local user %s via inbound login core (role=%s)", username, role)
    return get_user(username) is not None


def _init_workspace_best_effort(username: str, display_name: str, request: Any) -> None:
    try:
        from .user_provisioning import init_user_workspace
        init_user_workspace(username, display_name=display_name, request=request)
    except Exception as e:
        logger.warning("Workspace init skipped for %s: %s", username, e)


def provision_local_user(
    username: str, display_name: str, role: str, request: Any,
) -> bool:
    """死绑定自愈：绑定在但本地用户丢了 → 按原用户名重建（幂等）。

    场景：绑定存在（binding.user_id → 本地用户名），但本地用户记录已不存在
    （如历史命名迁移/清理时删了用户但没更新绑定）。此时不应让用户永远登不进来。
    """
    if create_local_user(username, display_name or username, role, request):
        logger.info(
            "Re-provisioned local user %s (dead binding self-heal, display_name=%s)",
            username, display_name or username,
        )
        return True
    return False


_provision_local_user = provision_local_user


def bind_matched_existing_user(
    username: str,
    provider: str,
    external_id: Any,
    external_name: str,
    mappings: Dict[str, Any],
    request: Any,
    source: str = "auto_matched",
) -> bool:
    """匹配到已有本地用户：写绑定 + 补工作区（best-effort）。

    不重复建用户、不改密码；仅补全外部系统用户授权中的绑定数据。
    """
    from .user_store import get_user as _get_user, update_user as _update_user

    existing_user = _get_user(username)
    if existing_user is None:
        return False

    now_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    mappings.setdefault("bindings", []).append({
        "user_id": username,
        "provider": provider,
        "external_id": external_id,
        "external_name": external_name or None,
        "source": source,
        "status": 1,
        "created_at": now_str,
        "last_login_at": now_str,
        "login_count": 1,
    })
    save_bindings_atomic(mappings)

    # display_name 还是默认值（=username）时，用外部姓名更新
    if external_name and existing_user.get("display_name") in (None, "", username):
        try:
            _update_user(username, display_name=external_name)
            logger.info("Auto-matched: updated display_name for %s to '%s'",
                        username, external_name)
        except Exception as e:
            logger.warning("Auto-matched: failed to update display_name: %s", e)

    _init_workspace_best_effort(
        username, external_name or existing_user.get("display_name"), request)
    return True


_bind_matched_existing_user = bind_matched_existing_user
_find_local_user_by_username = find_local_user_by_username
_try_match_existing_local_user = try_match_existing_local_user
_try_match_by_display_name = try_match_by_display_name


def generate_username(
    prefix: str, padding: int, seq_start: int, external_id: Any = None,
) -> str:
    """Generate the next auto username.

    优先：``{prefix}_{外部ID}`` —— 同一系统同一个人恒得同名；碰撞时尾部追加
    ``_01/_02…`` 直到唯一。回退（无可用外部ID）：旧规则 ``<prefix>_<seq>``（零填充）。

    序号 = 现有用户名中匹配 ``<prefix>_<数字>`` 的最大序号 + 1 —— 单一事实源，
    永不漂移，无需计数器字段。
    """
    from .user_store import get_user

    ext = sanitize_external_id(external_id)
    if prefix and ext:
        base = f"{prefix}_{ext}"
        candidate, n = base, 0
        while get_user(candidate) is not None:
            n += 1
            candidate = f"{base}_{n:02d}"
        return candidate

    seq = max(seq_start, 1)
    candidate = f"{prefix}_{seq:0{max(padding, 1)}d}"
    while get_user(candidate) is not None:
        seq += 1
        candidate = f"{prefix}_{seq:0{max(padding, 1)}d}"
    return candidate


_generate_username = generate_username


# ---------------------------------------------------------------------------
# 核心：外部身份 → 本地账号（唯一一份）
# ---------------------------------------------------------------------------

def resolve_external_identity(
    *,
    provider: str,
    system: Dict[str, Any],
    external_id: Any,
    external_name: str = "",
    request: Any = None,
    fixed_username: Optional[str] = None,
    allow_match: bool = True,
) -> Dict[str, Any]:
    """把一次已验签的外部登录落到本地账号上：查绑定 → 自愈 → 匹配 → 建号 → 写绑定。

    参数
    ----
    provider, system
        已解析的外部系统及其 ID。
    external_id, external_name
        外部系统身份（由已认证的外部系统签发，可信）。
    fixed_username
        旧契约（门户直投）：外部系统直接给出本地登录名 → **逐字使用**，
        不做前缀生成、不改名。新流程传 None。
    allow_match
        新流程 True（A1 确定性键 + 显示名收养）；旧契约传 False（用户名已定）。

    返回
    ----
    ``{username, auto_created, first_login, source, split_with}``

    失败以 HTTPException 抛出（403 拒绝猜测 / 500 建号失败）。
    """
    from .user_store import get_user, touch_last_login

    um = (system or {}).get("user_mapping") or {}

    # provider 为 None = 绑定能力关闭（旧部署未配置任何外部系统时的兼容路径）：
    # 只做"用户名逐字登录/建号"，不查绑定、不写绑定。
    if not provider:
        if not fixed_username:
            raise _http(400, "Missing provider")
        username = fixed_username
        auto_created = False
        existing = get_user(username)
        if existing is None:
            if not um.get("auto_create", True):
                raise _http(
                    403,
                    "未绑定该外部系统账号，且系统未开启自动创建用户。请联系管理员绑定。",
                )
            if not create_local_user(username, external_name or username,
                                     um.get("default_role") or "user", request):
                raise _http(500, "Failed to create user")
            auto_created = True
        first_login = True if auto_created else (existing or {}).get("last_login") is None
        touch_last_login(username)
        logger.warning(
            "Inbound login without provider (no external system configured): "
            "user=%s — 未写入绑定，账号无法与外部身份对账", username,
        )
        return {
            "username": username,
            "auto_created": auto_created,
            "first_login": first_login,
            "source": "no_provider",
            "split_with": None,
        }

    mappings = load_bindings()
    binding = find_binding_by_external(mappings, provider, external_id)

    # ── 1. 已有绑定：复用绑定账号（含死绑定自愈） ─────────────────
    if binding:
        username = binding["user_id"]
        existing = get_user(username)
        if existing is None:
            if not provision_local_user(username, external_name, "user", request):
                raise _http(500, "本地用户已丢失且自动恢复失败，请联系管理员检查用户数据")
            existing = get_user(username)
        # 首次登录判定必须在 touch_last_login 之前（与主登录一致）
        first_login = existing.get("last_login") is None
        binding["last_login_at"] = _now_str()
        binding["login_count"] = int(binding.get("login_count") or 0) + 1
        if external_name and not binding.get("external_name"):
            binding["external_name"] = external_name
        save_bindings_atomic(mappings)
        touch_last_login(username)
        # display_name 仍是自动值（=username）时，用外部姓名刷新（与建号路径一致）
        if external_name and existing.get("display_name") == username:
            try:
                from .user_store import update_user
                update_user(username, display_name=external_name)
                logger.info("Inbound login: refreshed display_name for %s to '%s'",
                            username, external_name)
            except Exception as e:
                logger.warning("Inbound login: failed to refresh display_name: %s", e)
        return {
            "username": username,
            "auto_created": False,
            "first_login": first_login,
            "source": str(binding.get("source") or "binding"),
            "split_with": detect_account_split(
                provider, username, external_name or existing.get("display_name") or ""),
        }

    # ── 2. 旧契约：用户名逐字使用（不生成、不改名） ───────────────
    if fixed_username:
        username = fixed_username
        auto_created = False
        existing = get_user(username)
        if existing is None:
            # 旧契约从不以 auto_create 门控登录（用户名由外部系统给定），默认放行
            if not um.get("auto_create", True):
                raise _http(
                    403,
                    "未绑定该外部系统账号，且系统未开启自动创建用户。请联系管理员绑定。",
                )
            display_name = external_name or username
            if not create_local_user(username, display_name,
                                     um.get("default_role") or "user", request):
                raise _http(500, "Failed to create user")
            auto_created = True
            first_login = True
        else:
            first_login = existing.get("last_login") is None

        bind_matched_existing_user(
            username, provider, external_id, external_name, mappings, request,
            source="legacy_sso")
        touch_last_login(username)
        logger.info(
            "Legacy inbound login: user=%s provider=%s external_id=%s auto_created=%s",
            username, provider, external_id, auto_created,
        )
        return {
            "username": username,
            "auto_created": auto_created,
            "first_login": first_login,
            "source": "legacy_sso",
            "split_with": detect_account_split(provider, username, external_name),
        }

    # ── 3. 新流程：确定性键匹配 → 显示名收养 → 自动建号 ───────────
    ext_login = sanitize_external_id(external_id)
    matched = None
    if allow_match:
        matched = try_match_existing_local_user(um, external_id, provider)
        if matched is None:
            matched, ambiguous = try_match_by_display_name(um, external_name)
            if ambiguous:
                raise _http(
                    403,
                    f"存在多个名为'{external_name}'的未绑定本地账号，"
                    "无法安全自动绑定。请联系管理员手动绑定。",
                )

    if matched is not None and bind_matched_existing_user(
            matched, provider, external_id, external_name, mappings, request):
        from .user_store import touch_last_login as _touch
        user = get_user(matched)
        touch_last_login(matched)
        logger.info(
            "SSO: auto-matched external identity to existing user %s "
            "(provider=%s, external_id=%s)", matched, provider, external_id,
        )
        return {
            "username": matched,
            "auto_created": False,
            "first_login": (user or {}).get("last_login") is None,
            "source": "auto_matched",
            "split_with": None,
        }

    if not um.get("auto_create"):
        raise _http(
            403,
            "未绑定该外部系统账号，且系统未开启自动创建用户。请联系管理员绑定。",
        )

    prefix = (str(um.get("username_prefix") or "")).strip() or provider
    padding = _int(um.get("seq_padding"), 4)
    seq_start = _int(um.get("seq_start"), 1)
    username = generate_username(prefix, padding, seq_start, ext_login)

    source = um.get("display_name_source", "external_name")
    if source == "external_name":
        display_name = external_name or username
    elif source == "external_id":
        display_name = str(external_id)
    else:
        display_name = username

    if not create_local_user(username, display_name,
                             um.get("default_role") or "user", request):
        raise _http(500, "Failed to create user")

    now_str = _now_str()
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
    from .user_store import touch_last_login as _touch
    _touch(username)
    logger.info(
        "Auto-created external user %s (provider=%s, external_id=%s, "
        "display_name=%s, role=%s)",
        username, provider, external_id, display_name,
        um.get("default_role") or "user",
    )
    return {
        "username": username,
        "auto_created": True,
        "first_login": True,
        "source": "auto",
        "split_with": None,
    }


# ---------------------------------------------------------------------------
# 核心：发 token + 审计（唯一一份）
# ---------------------------------------------------------------------------

def finish_login(
    *,
    username: str,
    provider: Optional[str],
    auto_created: bool,
    redirect: Any = "/chat",
    action: str = "login_success",
) -> Dict[str, Any]:
    """发真 token（与账号密码登录完全兼容）+ 审计。

    ``ext_provider`` 记录登录来源外部系统，供前端头部展示；旧 token 无该字段，
    向后兼容。
    """
    from .user_store import get_user
    from .auth import create_token

    user_info = get_user(username)
    if user_info is None:
        raise _http(404, "Local user no longer exists")

    token = create_token(username, expiry_seconds=LOGIN_TOKEN_TTL, ext_provider=provider)

    try:
        from .routers.audit import _append_audit_entry
        _append_audit_entry({
            "timestamp": time.time(),
            "event_type": "auth",
            "action": action,
            "user_id": username,
            "source": f"external:{provider}" if provider else "external",
            "detail": f"外部系统登录成功 (auto_created={auto_created})",
        })
    except Exception:
        pass

    return {
        "token": token,
        "username": username,
        "display_name": user_info.get("display_name") or username,
        "default_agent_id": f"user:{username}",
        "redirect": validate_redirect(redirect),
    }


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def _now_str() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _http(status: int, detail: str):
    from fastapi import HTTPException
    return HTTPException(status_code=status, detail=detail)
