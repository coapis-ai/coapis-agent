# -*- coding: utf-8 -*-
"""External SSO inbound login (Model A) + auto user creation tests.

Covers: signature verification, state one-time consumption, replay TTL,
provider resolution from state, auto user creation with username sequence,
real token issuance, and redirect whitelist.
"""

import hashlib
import hmac as hmac_mod
import json
import time

import pytest
from fastapi import FastAPI
from starlette.responses import Response
from starlette.testclient import TestClient

from coapis.app import auth as auth_mod
from coapis.app import external_identity
from coapis.app import external_login_core
from coapis.app import user_store
from coapis.app.routers import external_auth
from coapis.foundation.repository_factory import RepositoryFactory
from pathlib import Path


SECRET = "test_secret_for_unit_tests"
PROVIDER = "test_oa"
OA_URL = "https://oa.example.com"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Minimal app with only the external_auth router, data files redirected."""
    systems_file = tmp_path / "systems.json"
    mappings_file = tmp_path / "mappings.json"
    state_file = tmp_path / "states.json"
    auth_file = tmp_path / "auth.json"
    db_path = tmp_path / "test_coapis.db"

    system = {
        "provider_id": PROVIDER,
        "name": "Test OA",
        "login_type": "sso_redirect",
        "sso": {
            "login_url": "https://oa.example.com/sso/login?client_id=coapis&state={state}&redirect={redirect}",
            "callback": {
                "sign_string": "provider={provider}&external_id={external_id}&timestamp={timestamp}",
                "timestamp_ttl": 300,
            },
        },
        "user_mapping": {
            "auto_create": True,
            "username_prefix": "oa",
            "seq_start": 1,
            "seq_padding": 4,
            "display_name_source": "external_name",
            "default_role": "user",
        },
        "shared_secret_use_global": False,
        "shared_secret": SECRET,
        "base_urls": [OA_URL],
        "status": 1,
        "client_id": "coapis",
    }
    systems_file.write_text(json.dumps({"systems": [system]}, ensure_ascii=False))
    mappings_file.write_text(json.dumps({"bindings": []}))

    monkeypatch.setattr(external_login_core, "MAPPINGS_FILE", str(mappings_file))
    monkeypatch.setattr(external_login_core, "STATE_FILE", str(state_file))
    monkeypatch.setattr(external_identity, "SYSTEMS_CONFIG_FILE", str(systems_file))
    # AUTH_FILE 仍是 JSON（JWT 黑名单），保持 Path 类型
    monkeypatch.setattr(auth_mod, "AUTH_FILE", auth_file)
    # 初始化 SQLite 用户存储（临时 DB）— Phase 1: SQLAlchemy 仓储
    from coapis.foundation.user_repository_impl import SqlaUserRepository
    from coapis.foundation.db.base import Base
    from coapis.foundation.db.engine import get_engine, init_engine, reset_engine
    init_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(get_engine())
    user_repo = SqlaUserRepository()
    RepositoryFactory.reset()
    RepositoryFactory._user_repo = user_repo
    RepositoryFactory._initialized = True
    RepositoryFactory._edition = "community"
    # reset state cache
    external_auth._state_cache["data"] = {}
    external_auth._state_cache["mtime"] = -1

    # 与真实 app 一致的挂载方式：api_router 带 /api 前缀
    from fastapi import APIRouter
    app = FastAPI()
    api_router = APIRouter()
    api_router.include_router(external_auth.router)
    app.include_router(api_router, prefix="/api")
    yield TestClient(app)
    # teardown
    RepositoryFactory.reset()
    try:
        from coapis.foundation.db.engine import reset_engine
        reset_engine()
    except ImportError:
        pass


def _sign(provider, external_id, ts, secret=SECRET):
    s = f"provider={provider}&external_id={external_id}&timestamp={ts}"
    return hmac_mod.new(secret.encode(), s.encode(), hashlib.sha256).hexdigest()


def _get_state(client, provider=PROVIDER):
    r = client.get(f"/api/auth/external/login-state?provider={provider}")
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _login(client, provider=PROVIDER, external_id="u1001", name="张三",
           ts=None, state=None, sign=None, include_provider=True, **kw):
    if state is None:
        state = _get_state(client, provider)["state"]
    if ts is None:
        ts = int(time.time())
    if sign is None:
        sign = _sign(provider, external_id, ts)
    payload = {
        "external_id": external_id,
        "external_name": name,
        "timestamp": ts,
        "signature": sign,
        "state": state,
    }
    if include_provider:
        payload["provider"] = provider
    payload.update(kw)
    return client.post("/api/auth/external/login", json=payload)


# ---------------------------------------------------------------------------
# login-state
# ---------------------------------------------------------------------------

class TestLoginState:
    def test_returns_state_and_login_url(self, client):
        data = _get_state(client)
        assert data["state"]
        assert f"{OA_URL}/sso/login" in data["login_url"]
        # redirect 必须渲染为绝对 URL
        assert "redirect=" in data["login_url"]
        # state 已落盘且带 provider
        states = external_auth._load_states()
        entry = states[data["state"]]
        assert entry["provider"] == PROVIDER

    def test_unknown_provider(self, client):
        r = client.get("/api/auth/external/login-state?provider=ghost")
        assert r.status_code == 404

    def test_disabled_system(self, client):
        # 把系统置为禁用
        r = client.get("/api/auth/external/systems")
        assert r.status_code == 200
        # 直接改配置文件的系统状态
        import os
        cfg_path = external_identity.SYSTEMS_CONFIG_FILE
        data = json.loads(open(cfg_path).read())
        data["systems"][0]["status"] = 0
        open(cfg_path, "w").write(json.dumps(data))
        r = client.get(f"/api/auth/external/login-state?provider={PROVIDER}")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# 验签 / 防重放 / state 一次性
# ---------------------------------------------------------------------------

class TestSecurity:
    def test_bad_signature(self, client):
        r = _login(client, sign="deadbeef" * 8)
        assert r.status_code == 403
        assert "signature" in r.json()["detail"].lower()

    def test_wrong_secret(self, client):
        r = _login(client, sign=_sign(PROVIDER, "u1001", int(time.time()), "wrong_secret"))
        assert r.status_code == 403

    def test_expired_timestamp(self, client):
        ts = int(time.time()) - 1000  # 超出 300s TTL
        r = _login(client, ts=ts)
        assert r.status_code == 401

    def test_state_reuse_rejected(self, client):
        state = _get_state(client)["state"]
        r1 = _login(client, state=state)
        assert r1.status_code == 200
        r2 = _login(client, state=state)
        assert r2.status_code == 403
        assert "state" in r2.json()["detail"].lower()

    def test_state_provider_mismatch(self, client):
        state = _get_state(client)["state"]
        # 拿 test_oa 的 state，却声明 provider=ghost（ghost 没配置 → 404 也合理；
        # 这里用存在的 provider 场景验证：只有一个系统，所以直接验 403/404）
        r = _login(client, state=state, include_provider=True, provider="ghost")
        assert r.status_code in (403, 404)

    def test_missing_params(self, client):
        r = client.post("/api/auth/external/login", json={"external_id": "x"})
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# 自动建用户 + 真 token
# ---------------------------------------------------------------------------

class TestAutoCreate:
    def test_auto_create_first_user(self, client):
        r = _login(client, external_id="u1001", name="张三")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["auto_created"] is True
        assert body["username"] == "oa_u1001"
        assert body["display_name"] == "张三"
        assert body["first_login"] is True
        assert body["token"]

        # 真 token：可被 verify_token 验证
        assert auth_mod.verify_token(body["token"]) == "oa_u1001"

        # 绑定记录已写入（source=auto）
        mappings = external_auth.load_bindings()
        b = mappings["bindings"][0]
        assert b["user_id"] == "oa_u1001"
        assert b["provider"] == PROVIDER
        assert b["external_id"] == "u1001"
        assert b["external_name"] == "张三"
        assert b["source"] == "auto"
        assert b["login_count"] == 1

    def test_username_prefix_plus_external_id(self, client):
        """v2 命名规则：前缀 + 外部ID，同一系统同一人恒同名。"""
        r1 = _login(client, external_id="u1001", name="张三")
        r2 = _login(client, external_id="u1002", name="李四")
        assert r1.json()["username"] == "oa_u1001"
        assert r2.json()["username"] == "oa_u1002"

    def test_username_sequence_fallback_when_id_unusable(self, client):
        """外部ID清洗后为空 → 回退旧序号规则（递增不漂移）。"""
        r1 = _login(client, external_id="@@", name="甲")
        r2 = _login(client, external_id="%%", name="乙")
        assert r1.json()["username"] == "oa_0001"
        assert r2.json()["username"] == "oa_0002"

    def test_second_login_no_autocreate_first_login_false(self, client):
        r1 = _login(client, external_id="u1001", name="张三")
        r2 = _login(client, external_id="u1001", name="张三")
        assert r1.json()["auto_created"] is True
        assert r2.json()["auto_created"] is False
        assert r2.json()["first_login"] is False
        assert r2.json()["username"] == "oa_u1001"

    def test_provider_resolved_from_state(self, client):
        # 回调不传 provider，后端从 state 还原
        r = _login(client, external_id="u2001", name="王五", include_provider=False)
        assert r.status_code == 200, r.text
        assert r.json()["username"] == "oa_u2001"

    def test_auto_create_disabled_no_binding(self, client):
        import os
        cfg_path = external_identity.SYSTEMS_CONFIG_FILE
        data = json.loads(open(cfg_path).read())
        data["systems"][0]["user_mapping"]["auto_create"] = False
        open(cfg_path, "w").write(json.dumps(data))
        r = _login(client, external_id="u9999", name="无绑定")
        assert r.status_code == 403
        assert "绑定" in r.json()["detail"]

    def test_display_name_fallback_to_username(self, client):
        # external_name 为空 → 显示名回退为用户名
        r = _login(client, external_id="u3001", name="")
        assert r.status_code == 200
        assert r.json()["display_name"] == r.json()["username"]


# ---------------------------------------------------------------------------
# 补全绑定关系：未绑定时先匹配已有本地用户（match_existing 默认开）
# ---------------------------------------------------------------------------

class TestMatchExisting:
    def test_typed_username_not_used_for_matching(self, client):
        """A1 治本：表单输入的登录名永不参与匹配。

        种子本地账号 liuliangxu（显示名同为 liuliangxu）；输入 username=liuliangxu，
        但 external_name="陌生人甲"（无对应本地账号）→ 必须按 前缀_外部ID 新建，
        证明输入登录名未被用作匹配候选（王静分身的教训）。
        """
        user_store.create_user("liuliangxu", "somepw", display_name="liuliangxu")
        before = {u["username"] for u in user_store.list_users()}

        r = _login(client, external_id="u2001", name="陌生人甲", username="liuliangxu")
        assert r.status_code == 200, r.text
        body = r.json()
        # 不再绑到 liuliangxu，而是按确定性身份键新建
        assert body["auto_created"] is True
        assert body["username"] == "oa_u2001"
        assert "liuliangxu" in before  # 老账号原样保留

        # 绑定记录：source=auto_created，指向新账号
        mappings = external_auth.load_bindings()
        b = mappings["bindings"][0]
        assert b["user_id"] == "oa_u2001"
        assert b["source"] == "auto"
        assert b["provider"] == PROVIDER
        assert b["external_id"] == "u2001"

    def test_match_prefix_external_id_case_insensitive(self, client):
        """前缀_外部ID 大小写不敏感匹配存量账号 → 补绑定，不新建。"""
        user_store.create_user("OA_U2002", "somepw")
        before = {u["username"] for u in user_store.list_users()}

        r = _login(client, external_id="u2002", name="随便什么", username="whatever_input")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["auto_created"] is False
        assert body["username"] == "OA_U2002"
        assert {u["username"] for u in user_store.list_users()} == before
        b = external_auth.load_bindings()["bindings"][0]
        assert b["user_id"] == "OA_U2002"
        assert b["source"] == "auto_matched"

    def test_deprecated_match_by_setting_is_ignored(self, client):
        """旧配置 match_by=external_name 已废弃 → 姓名不再参与匹配。"""
        user_store.create_user("liuliangxu", "somepw", display_name="刘流绪")
        cfg_path = external_identity.SYSTEMS_CONFIG_FILE
        data = json.loads(open(cfg_path).read())
        data["systems"][0]["user_mapping"].update({
            "match_by": "external_name",
            "match_display_name": False,
        })
        open(cfg_path, "w").write(json.dumps(data))

        r = _login(client, external_id="u2005", name="刘流绪")
        assert r.status_code == 200, r.text
        # 不匹配 liuliangxu，按确定性身份键新建
        assert r.json()["auto_created"] is True
        assert r.json()["username"] == "oa_u2005"
        assert external_auth.load_bindings()["bindings"][0]["source"] == "auto"

    def test_match_no_match_falls_through_to_autocreate(self, client):
        """匹配不到 → 回落到原自动建用户流程（v2 命名：前缀+外部ID）。"""
        r = _login(client, external_id="u2003", name="陌生人", username="nobody")
        assert r.status_code == 200, r.text
        assert r.json()["auto_created"] is True
        assert r.json()["username"] == "oa_u2003"

    def test_match_prefix_external_id_absorbs_legacy(self, client):
        """本地已有"前缀_外部ID"命名的存量账号（老通道产物）→ 匹配吸收，不新建。"""
        user_store.create_user("oa_u2006", "somepw", display_name="老账号")
        before = {u["username"] for u in user_store.list_users()}

        r = _login(client, external_id="u2006", name="老账号", username="别的登录名")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["auto_created"] is False
        assert body["username"] == "oa_u2006"
        assert {u["username"] for u in user_store.list_users()} == before
        b = external_auth.load_bindings()["bindings"][0]
        assert b["user_id"] == "oa_u2006"
        assert b["source"] == "auto_matched"

    def test_match_existing_disabled(self, client):
        """match_existing=False → 即使本地有同名用户也走自动建用户。"""
        user_store.create_user("liuliangxu", "somepw")
        cfg_path = external_identity.SYSTEMS_CONFIG_FILE
        data = json.loads(open(cfg_path).read())
        data["systems"][0]["user_mapping"]["match_existing"] = False
        open(cfg_path, "w").write(json.dumps(data))

        r = _login(client, external_id="u2004", name="liuliangxu", username="liuliangxu")
        assert r.status_code == 200, r.text
        assert r.json()["auto_created"] is True
        assert r.json()["username"] == "oa_u2004"




# ---------------------------------------------------------------------------
# 系统列表（登录页"其他登录方式"）
# ---------------------------------------------------------------------------

class TestSystemsList:
    def test_list_filters_and_sorts(self, client):
        r = client.get("/api/auth/external/systems")
        assert r.status_code == 200
        systems = r.json()["data"]
        assert len(systems) == 1
        s = systems[0]
        assert s["provider_id"] == PROVIDER
        assert s["name"] == "Test OA"
        # 不应泄露密钥
        assert "shared_secret" not in s or not s.get("shared_secret")

    def test_login_type_none_hidden(self, client):
        cfg_path = external_identity.SYSTEMS_CONFIG_FILE
        data = json.loads(open(cfg_path).read())
        data["systems"][0]["login_type"] = "none"
        data["systems"][0]["show_on_login"] = False
        open(cfg_path, "w").write(json.dumps(data))
        r = client.get("/api/auth/external/systems")
        assert r.json()["data"] == []


# ---------------------------------------------------------------------------
# redirect 白名单
# ---------------------------------------------------------------------------

class TestRedirect:
    def test_open_redirect_blocked(self, client):
        r = _login(client, external_id="u1001", redirect="https://evil.com/x")
        assert r.status_code == 200
        # 被拒后回默认 /chat（或空）
        assert r.json()["redirect"] in ("", "/chat")

    def test_internal_path_allowed(self, client):
        r = _login(client, external_id="u1001", redirect="/chat")
        assert r.status_code == 200
        assert r.json()["redirect"] == "/chat"


# ---------------------------------------------------------------------------
# 显示名收养（治分身账号之根）：恰1个未绑定命中→收养；歧义→拒绝；绝不抢占已绑定
# ---------------------------------------------------------------------------

class TestDisplayNameAdoption:
    """显示名收养仅在 SSO 回调生效（external_name 由已认证外部系统签发，可信）。"""

    def _seed_local(self, username: str, display_name: str) -> None:
        user_store.create_user(
            username=username, password="plain-pass",
            display_name=display_name, role="user",
        )

    def _sso_login(self, client: TestClient, external_id: str, external_name: str) -> Response:
        # 与真实挂载一致：api_router(/api) + router(/auth)
        rr = client.get(
            "/api/auth/external/login-state", params={"provider": PROVIDER},
        )
        assert rr.status_code == 200, rr.text
        st = rr.json()["data"]["state"]
        ts = int(time.time())
        sign_string = (
            f"provider={PROVIDER}&external_id={external_id}&timestamp={ts}"
        )
        sig = hmac_mod.new(SECRET.encode(), sign_string.encode(), hashlib.sha256).hexdigest()
        return client.post("/api/auth/external/login", json={
            "provider": PROVIDER, "external_id": external_id,
            "external_name": external_name, "timestamp": ts,
            "signature": sig, "state": st,
        })

    def test_adopts_unique_unbound_user(self, client):
        """刘良旭已有本地账号 liuliangxu（未绑定）→ SSO 登录收养之，不新建。"""
        self._seed_local("liuliangxu", "刘良旭")
        r = self._sso_login(client, external_id="u901", external_name="刘良旭")
        assert r.status_code == 200, r.text
        bindings = external_auth.load_bindings()["bindings"]
        assert any(
            b["provider"] == PROVIDER and str(b["external_id"]) == "u901"
            and b["user_id"] == "liuliangxu"
            for b in bindings
        ), bindings
        names = {u["username"] for u in user_store.list_users()}
        assert not any(n.startswith("oa_") for n in names), names

    def test_ambiguous_display_name_rejected(self, client):
        """同名两个未绑定账号 → 403 拒绝，不建新号、不写绑定。"""
        self._seed_local("zw_a", "张伟")
        self._seed_local("zw_b", "张伟")
        r = self._sso_login(client, external_id="u902", external_name="张伟")
        assert r.status_code == 403
        assert "多个" in r.json()["detail"]
        assert external_auth.load_bindings()["bindings"] == []
        names = {u["username"] for u in user_store.list_users()}
        assert not any(n.startswith("oa_") for n in names), names

    def test_bound_user_never_stolen(self, client):
        """zhangsan 已绑定 u903 → 新外部ID u904 同名登录不得抢占，应另建新号。"""
        self._seed_local("zhangsan", "张三")
        external_auth.save_bindings_atomic({"bindings": [{
            "user_id": "zhangsan", "provider": PROVIDER,
            "external_id": "u903", "external_name": "张三", "status": 1,
        }]})
        r = self._sso_login(client, external_id="u904", external_name="张三")
        assert r.status_code == 200, r.text
        bindings = external_auth.load_bindings()["bindings"]
        b_new = [b for b in bindings if str(b["external_id"]) == "u904"][0]
        assert b_new["user_id"] != "zhangsan", b_new
        assert str(b_new["user_id"]).startswith("oa_"), b_new

    def test_match_display_name_disabled(self, client):
        """match_display_name=False → 跳过收养，走自动建号。"""
        cfg_path = Path(external_identity.SYSTEMS_CONFIG_FILE)
        data = json.loads(cfg_path.read_text())
        data["systems"][0]["user_mapping"]["match_display_name"] = False
        cfg_path.write_text(json.dumps(data, ensure_ascii=False))
        self._seed_local("liuliangxu", "刘良旭")
        r = self._sso_login(client, external_id="u905", external_name="刘良旭")
        assert r.status_code == 200, r.text
        bindings = external_auth.load_bindings()["bindings"]
        b_new = [b for b in bindings if str(b["external_id"]) == "u905"][0]
        assert b_new["user_id"] != "liuliangxu", b_new


