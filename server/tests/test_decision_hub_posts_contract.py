# -*- coding: utf-8 -*-
"""A0：中枢岗位开关的写读契约（嵌套 ``posts`` 段 ↔ 平铺别名）。

实锤缺陷（2026-11-16 实测）：写盘侧 ``full_view()`` 出的是嵌套 ``posts`` 段，
读侧 ``from_dict`` 只认平铺 ``{post}_enabled`` —— 管理台保存岗位开关后，
下一轮读盘全部回落默认值，页面开关等于空操作；平铺键还不在路由白名单里，
连落盘都进不去（被当未知键拒收）。

本文件锁四件事：
1. 嵌套段读得到（写读同名，落盘再读回不丢值）；
2. 平铺别名读得到（手改配置、老配置文件的形状）；
3. 两者冲突时平铺压过嵌套（快照不许压过新指令）；
4. 管理台 PUT 岗位开关 → ``get_hub_config().post_enabled()`` 立刻反映。
"""

from __future__ import annotations

import json
import types

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from coapis.app.routers import decisions as decisions_mod
from coapis.decision import config as hub_cfg_mod
from coapis.decision.config import (
    POSTS,
    DecisionHubConfig,
    get_hub_config,
    normalize_hub_keys,
    reset_hub_config,
)


def _saved_file() -> dict:
    """读落盘文件。必须经模块属性动态取路径：``hub_config_path`` 被
    monkeypatch 换掉了，测试里 if 提前 import 成局部名字就会读到真实部署目录。
    """
    path = hub_cfg_mod.hub_config_path()
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


# --------------------------------------------------------------------- #
# 纯契约层（不启 app）
# --------------------------------------------------------------------- #


def test_nested_posts_segment_is_honored():
    """写盘侧出的嵌套段，读侧必须认（读写同名 = 闭环）。"""
    cfg = DecisionHubConfig.from_dict({"posts": {p: False for p in POSTS}})
    assert all(cfg.post_enabled(p) is False for p in POSTS), "嵌套 posts 段必须生效"


def test_flat_post_aliases_are_honored():
    """平铺 ``{post}_enabled``（手改配置/历史文件的形状）必须生效。"""
    cfg = DecisionHubConfig.from_dict(
        {"plan_gate_enabled": False, "acceptance_enabled": False},
    )
    assert cfg.post_enabled("plan_gate") is False
    assert cfg.post_enabled("acceptance") is False
    assert cfg.post_enabled("verify") is True, "没点的岗位保持默认"


def test_flat_alias_beats_nested_snapshot():
    """冲突时平铺压过嵌套：落盘段是上次保存的快照，不能压过这次的新指令。"""
    cfg = DecisionHubConfig.from_dict(
        {"posts": {"acceptance": True}, "acceptance_enabled": False},
    )
    assert cfg.post_enabled("acceptance") is False, "平铺显式指定必须赢"


def test_master_switch_overrides_post_defaults():
    """总开关关掉时，未显式指定的岗位一律关（缺省跟随 enabled 的语义）。"""
    cfg = DecisionHubConfig.from_dict({"enabled": False, "posts": {"verify": True}})
    assert cfg.post_enabled("verify") is False, "总开关压过岗位开关"
    cfg2 = DecisionHubConfig.from_dict({"enabled": False})
    assert all(cfg2.post_enabled(p) is False for p in POSTS)


def test_save_read_roundtrip_keeps_posts():
    """落盘 → 读回必须逐岗一致（full_view 出的那一份能被 from_dict 读回）。"""
    first = DecisionHubConfig.from_dict(
        {"posts": {"plan_gate": False, "advisor": False, "acceptance": False}},
    )
    back = DecisionHubConfig.from_dict(first.full_view())
    assert back.posts == first.posts, "写读必须闭环"


def test_normalize_folds_aliases_and_drops_flat_keys():
    out = normalize_hub_keys({"plan_gate_enabled": False, "posts": {"verify": False}})
    assert "plan_gate_enabled" not in out, "别名折完即删，落盘只留一份键名"
    assert out["posts"]["plan_gate"] is False
    assert out["posts"]["verify"] is False, "嵌套段原有项不许被冲掉"


def test_unknown_post_name_in_segment_is_ignored():
    cfg = DecisionHubConfig.from_dict({"posts": {"nosuchpost": False}})
    assert "nosuchpost" not in cfg.posts
    assert all(cfg.post_enabled(p) is True for p in POSTS)


# --------------------------------------------------------------------- #
# 管理台契约层（真路由 + 真落盘路径，临时目录）
# --------------------------------------------------------------------- #


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """admin 身份可写中枢配置的最小 app；落盘指向临时目录。"""
    from coapis.app.permissions.manager import PermissionManager

    app = FastAPI()

    @app.middleware("http")
    async def _identity(request: Request, call_next):
        request.state.username = "root"
        request.state.role = "admin"
        return await call_next(request)

    api = FastAPI().router
    api.include_router(decisions_mod.router, prefix="/decisions")
    app.include_router(api, prefix="/api")

    hub_file = tmp_path / "hub" / "decision_hub.json"
    hub_file.parent.mkdir()
    monkeypatch.setattr("coapis.decision.config.hub_config_path", lambda: hub_file)
    reset_hub_config()

    monkeypatch.setattr(
        PermissionManager, "_instance",
        types.SimpleNamespace(
            has_permission=lambda username, permission, role="user": True,
        ),
    )
    yield TestClient(app)
    reset_hub_config()


def test_admin_post_switch_reaches_runtime(client):
    """页面点一下岗位开关 → 运行时立刻生效（A0 的验收口径）。"""
    before = get_hub_config().post_enabled("acceptance")
    res = client.put(
        "/api/decisions/config?agent_id=a1",
        json={"acceptance_enabled": not before},
    )
    assert res.status_code == 200
    assert get_hub_config().post_enabled("acceptance") is (not before), (
        "管理台保存岗位开关必须真的生效（实锤缺陷：嵌套段读不回）"
    )
    saved = _saved_file()
    assert "acceptance_enabled" not in saved, "落盘只认一份键名（嵌套段）"
    assert saved["posts"]["acceptance"] is (not before)


def test_admin_nested_posts_switch_reaches_runtime(client):
    """API 直接发嵌套段也要生效（写读同名）。"""
    res = client.put(
        "/api/decisions/config?agent_id=a1",
        json={"posts": {"plan_gate": False}},
    )
    assert res.status_code == 200
    cfg = get_hub_config()
    assert cfg.post_enabled("plan_gate") is False
    assert cfg.post_enabled("verify") is True


def test_admin_switch_survives_config_restart(client):
    """落盘的值必须扛得住重启（读盘，不靠进程内状态）。"""
    client.put(
        "/api/decisions/config?agent_id=a1",
        json={"plan_gate_enabled": False},
    )
    reset_hub_config()
    cfg = get_hub_config()
    assert cfg.post_enabled("plan_gate") is False, "重启后岗位开关必须仍生效"
