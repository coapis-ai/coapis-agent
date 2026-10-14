# -*- coding: utf-8 -*-
"""普通用户 MCP 可用性 —— 权限位单元测试。

背景与策略：
全局 MCP 池由 admin 配置，合并进每个用户 workspace（见
``get_global_mcp_pool_agent_id`` + ``service_factories.create_mcp_service``），
策略是「admin 配了，所有登录用户都可用」。

历史缺陷：调用路由 ``POST /mcp/gateway/call`` 挂的是 ``mcp:write``
（= create|update），而 role=user 的 mcp 矩阵只有 ``read=True`` →
普通用户一调用就 403（工具列表看得见、点就拒）。

本测试锁死三件事，防止权限位再被挂错：
1. 调用/查看类路由 = ``mcp:read``
2. 配置增删改类路由 = ``mcp:write``（普通用户不可越权改配置）
3. 默认权限定义里 user 角色有 ``mcp:read``、没有 ``mcp:write``
"""

import pytest

from coapis.app.permissions.manager import PermissionManager
from coapis.app.routers import mcp as mcp_router
from coapis.system.defaults import DEFAULT_PERMISSIONS, DEFAULT_ROLES


# ── 1. 调用/查看类路由必须把守在 read ──────────────────────────────
@pytest.mark.parametrize(
    "handler",
    [
        "call_mcp_gateway_tool",      # 本次修复：write → read
        "list_mcp_clients",
        "list_global_mcp_clients",
        "list_mcp_gateway_tools",
        "get_mcp_client",
        "list_mcp_tools",
    ],
)
def test_use_routes_gated_by_read(handler):
    fn = getattr(mcp_router, handler)
    assert getattr(fn, "_required_permission", None) == "mcp:read", (
        f"{handler} 应把守在 mcp:read（普通用户可用），"
        f"实际={getattr(fn, '_required_permission', None)!r}"
    )


# ── 2. 配置类路由必须把守在 write（越权防线）──────────────────────
@pytest.mark.parametrize(
    "handler",
    [
        "create_mcp_client",
        "update_mcp_client",
        "toggle_mcp_client",
        "delete_mcp_client",
        "create_global_mcp_client",
        "delete_global_mcp_client",
        "install_mcp_package",
    ],
)
def test_config_routes_gated_by_write(handler):
    fn = getattr(mcp_router, handler)
    assert getattr(fn, "_required_permission", None) == "mcp:write", (
        f"{handler} 是配置写操作，必须把守在 mcp:write，"
        f"实际={getattr(fn, '_required_permission', None)!r}"
    )


# ── 3. 默认矩阵：user 能用 MCP，不能改 MCP 配置 ───────────────────
def test_default_matrix_user_can_read_mcp_not_write(monkeypatch):
    cfg = {
        "version": "2.0",
        "roles": {"user": {"modules": dict(DEFAULT_ROLES["user"]["modules"])}},
        "user_overrides": {},
        "modules": dict(DEFAULT_PERMISSIONS["modules"]),
    }
    monkeypatch.setattr(PermissionManager, "_config", cfg)
    pm = PermissionManager()

    assert pm.has_permission("alice", "mcp:read", "user") is True
    assert pm.has_permission("alice", "mcp:write", "user") is False
    assert pm.has_permission("alice", "mcp:create", "user") is False
    assert pm.has_permission("alice", "mcp:delete", "user") is False
    # admin 全权
    assert pm.has_permission("admin", "mcp:write", "admin") is True


def test_default_registry_declares_mcp_module():
    """fallback 注册表缺 mcp 时，管理员权限矩阵里根本没有 MCP 行可配。

    权威定义在 data packs；pack 加载失败会退到 defaults.py 里的
    ``_DEFAULT_*_FALLBACK``，两边都必须登记 mcp，否则 MCP 权限不可配、
    且 ``mcp:read`` 恒 False（人人 403）。
    """
    from coapis.system.defaults import (
        _DEFAULT_PERMISSIONS_FALLBACK,
        _DEFAULT_ROLES_FALLBACK,
    )

    for name, mods, roles in (
        ("pack", DEFAULT_PERMISSIONS["modules"], DEFAULT_ROLES),
        ("fallback", _DEFAULT_PERMISSIONS_FALLBACK["modules"], _DEFAULT_ROLES_FALLBACK),
    ):
        assert "mcp" in mods, f"{name} 的模块注册表缺 mcp"
        assert "mcp" in roles["user"]["modules"], f"{name} 的 user 角色缺 mcp 行"
        assert roles["user"]["modules"]["mcp"]["read"] is True, f"{name} 的 user 无 mcp:read"
        assert roles["user"]["modules"]["mcp"]["create"] is False, f"{name} 的 user 越权有 mcp:create"

