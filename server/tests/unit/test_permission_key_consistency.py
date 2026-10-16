"""权限键名一致性回归测试（2026-10 修掉的三类静默失效）。

背景：后端 has_permission() 对不存在的模块名**直接拒绝且不报错**，
前端映射表写错一个字符 = 该菜单对非管理员静默消失，且无人发现。
本测试锁死四条不变量：

  1. 权威模块清单三处一致（pack / defaults fallback / 前端映射引用）
  2. 所有角色矩阵的键 ⊆ 权威清单（不许有幽灵模块）
  3. 矩阵位值必须是真布尔（不许 1/0 整数污染）
  4. 侧栏与设置页共用同一个判定函数（不许各自实现一套）
"""
import json
import re
from pathlib import Path

import pytest

from coapis.system.defaults import (
    PERMISSION_MODULE_KEYS,
    DEFAULT_PERMISSIONS,
    DEFAULT_ROLES,
    _DEFAULT_PERMISSIONS_FALLBACK,
    _DEFAULT_ROLES_FALLBACK,
)

BITS = ("read", "create", "update", "delete")

REPO = Path(__file__).resolve().parents[3]
# 两种运行布局：宿主机仓库（.../coapis-agent/server/tests/unit → 仓库根）
# 与容器内（/app/tests/unit → /app，server 侧代码挂在 /app/coapis）。
_PACK_CANDIDATES = [
    REPO / "server/coapis/data/packs/base/auth/permissions.json",
    Path(__file__).resolve().parents[2] / "coapis/data/packs/base/auth/permissions.json",
]
_ROLE_PACK_CANDIDATES = [
    REPO / "server/coapis/data/packs/base/auth/roles.json",
    Path(__file__).resolve().parents[2] / "coapis/data/packs/base/auth/roles.json",
]


def _first_existing(cands, label):
    for p in cands:
        if p.exists():
            return p
    pytest.skip(f"{label} 不在本环境（容器沙箱只挂载 server 侧源码）")


PACK = _first_existing(_PACK_CANDIDATES, "权限出厂包")
ROLES_PACK = _first_existing(_ROLE_PACK_CANDIDATES, "角色出厂包")
MAPPING_TS = REPO / "client/src/config/permissionMapping.ts"
SIDEBAR_TS = REPO / "client/src/layouts/Sidebar.tsx"
SETTINGS_TSX = REPO / "client/src/pages/Settings/index.tsx"

AUTH = set(PERMISSION_MODULE_KEYS)


def _pack_modules():
    return json.loads(PACK.read_text(encoding="utf-8"))


def _mapping():
    if not MAPPING_TS.exists():
        pytest.skip("前端源码不在本环境（容器沙箱只挂载 server 侧）")
    src = MAPPING_TS.read_text(encoding="utf-8")
    block = src.split("MENU_TO_PERMISSION_MODULE: Record<string, string> = {", 1)[1]
    block = block.split("};", 1)[0]
    return {m.group(1): m.group(2)
            for m in re.finditer(r"^\s*'([^']+)'\s*:\s*'([^']+)',", block, re.M)}


def _role_matrices(doc, nested):
    """yield (role, matrix) —— 兼容 {role:{modules:{...}}} 与 {role:{...}} 两种形态"""
    roles = doc.get("roles", doc)
    for role, cfg in roles.items():
        mx = cfg.get("modules") if nested and isinstance(cfg, dict) else cfg
        if isinstance(mx, dict):
            yield role, mx


# ── 1. 权威清单三处一致 ──────────────────────────────────────────────
def test_authoritative_keys_stable():
    """pack 模块注册表必须与 defaults 里的权威清单逐字一致。"""
    pack = _pack_modules()
    assert set(pack["modules"]) == AUTH, (
        f"pack 模块注册表与权威清单不一致: "
        f"pack-only={set(pack['modules']) - AUTH}, keys-only={AUTH - set(pack['modules'])}"
    )
    assert set(DEFAULT_PERMISSIONS["modules"]) == AUTH
    assert set(_DEFAULT_PERMISSIONS_FALLBACK["modules"]) == AUTH


def test_roles_pack_keys_match_authoritative():
    r = json.loads(ROLES_PACK.read_text(encoding="utf-8"))
    for role, mx in _role_matrices(r, nested=True):
        if mx == "*":
            continue
        assert set(mx) == AUTH, f"roles.json/{role} 键与权威清单不一致: {set(mx) ^ AUTH}"


# ── 2. 不许有幽灵模块 ───────────────────────────────────────────────
@pytest.mark.parametrize("name,doc,nested", [
    ("pack", _pack_modules(), True),
    ("roles_pack", json.loads(ROLES_PACK.read_text(encoding="utf-8")), True),
    ("fallback", _DEFAULT_PERMISSIONS_FALLBACK, False),
])
def test_no_ghost_modules(name, doc, nested):
    for role, mx in _role_matrices(doc, nested):
        ghost = set(mx) - AUTH
        assert not ghost, (
            f"{name}/{role} 声明了后端不存在的模块 {sorted(ghost)} —— "
            f"has_permission 会静默拒绝，这些权限永远不生效"
        )


def test_frontend_mapping_has_no_ghost_module():
    """前端映射引用的模块名必须都在后端注册表里（历史上 cron/token_usage 是幽灵名）。"""
    mapping = _mapping()
    ghost = {v for v in mapping.values()} - AUTH
    assert not ghost, (
        f"前端映射引用了后端不存在的模块 {sorted(ghost)} —— "
        f"对应菜单会对非管理员永久隐藏"
    )


def test_frontend_mapping_covers_settings_cards():
    """设置页每张受门控的卡片都必须有映射，否则等于不受控。"""
    if not SETTINGS_TSX.exists():
        pytest.skip("前端源码不在本环境（容器沙箱只挂载 server 侧）")
    mapping = _mapping()
    src = SETTINGS_TSX.read_text(encoding="utf-8")
    cards = set(re.findall(r"key:\s*'([a-z-]+)'", src))
    cards = {c for c in cards if c not in ("settings", "user", "logout")}
    missing = sorted(c for c in cards if c not in mapping)
    assert not missing, f"设置页卡片未纳入权限映射: {missing}"


# ── 3. 位值必须是真布尔 ─────────────────────────────────────────────
@pytest.mark.parametrize("name,doc,nested", [
    ("pack", _pack_modules(), True),
    ("roles_pack", json.loads(ROLES_PACK.read_text(encoding="utf-8")), True),
    ("fallback", _DEFAULT_PERMISSIONS_FALLBACK, False),
])
def test_matrix_bits_are_bool(name, doc, nested):
    for role, mx in _role_matrices(doc, nested):
        for mod, bits in mx.items():
            for b in BITS:
                v = bits.get(b)
                assert isinstance(v, bool), (
                    f"{name}/{role}/{mod}.{b} = {v!r}（{type(v).__name__}）—— "
                    f"必须是 bool，整数 1/0 会让 `is True` 判定失效"
                )


# ── 4. 两处门控共用同一实现 ─────────────────────────────────────────
def test_sidebar_and_settings_share_one_gate():
    if not (SIDEBAR_TS.exists() and SETTINGS_TSX.exists()):
        pytest.skip("前端源码不在本环境（容器沙箱只挂载 server 侧）")
    side = SIDEBAR_TS.read_text(encoding="utf-8")
    setting = SETTINGS_TSX.read_text(encoding="utf-8")
    for name, src in (("Sidebar", side), ("Settings", setting)):
        assert "isMenuKeyAllowed" in src, f"{name} 未使用统一判定函数 isMenuKeyAllowed"
        assert "MENU_TO_PERMISSION_MODULE" not in src, (
            f"{name} 直接消费映射表 = 自行实现了一套判定逻辑"
        )
    # 侧栏历史上用菜单 key 兜底，正是这个兜底把映射名错的问题掩盖掉
    assert "allowedModules.includes(menuKey)" not in side, "侧栏仍在用菜单 key 兜底"


def test_admin_matrix_is_open_or_wildcard():
    for name, roles in (("pack", DEFAULT_ROLES), ("fallback", _DEFAULT_ROLES_FALLBACK)):
        admin = roles["admin"]["modules"]
        assert admin == "*" or all(all(v.values()) for v in admin.values()), \
            f"{name}/admin 不是全权"


def test_user_cannot_write_mcp_configs():
    """策略：admin 配置一次全员可用 —— 普通用户可读可用，不可增删改配置。"""
    for name, roles in (("pack", DEFAULT_ROLES), ("fallback", _DEFAULT_ROLES_FALLBACK)):
        mx = roles["user"]["modules"]
        assert mx["mcp"]["read"] is True, f"{name}/user 无 mcp:read（普通用户调用 MCP 会 403）"
        for b in ("create", "update", "delete"):
            assert mx["mcp"][b] is False, f"{name}/user 有 mcp:{b}（普通用户可改 MCP 配置）"
