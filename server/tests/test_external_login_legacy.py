# -*- coding: utf-8 -*-
"""Tests for the legacy inbound login adapter (/api/external/login).

覆盖生产主登录路径（旧契约：门户 302 直投 ``token=HMAC(secret, username)``）。
2026-10 起该端点改为**薄适配器**，登录业务统一调用 ``external_login_core``，
本文件锁定其对外契约不变，并记录收敛到唯一真源后新增的行为。
"""
import hashlib
import hmac as hmac_mod
import json
import os
import time

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from coapis.app import auth as auth_mod
from coapis.app import external_identity
from coapis.app import external_login_core as core
from coapis.app import user_store
from coapis.app.routers import external_auth

import coapis.app.external_login as legacy

SECRET = "legacy-sso-secret-for-tests"
USERNAME = "zrsz_144"
PROVIDER = "sczrsz_oa"


def _sign(username, secret=SECRET):
    return hmac_mod.new(secret.encode(), username.encode(), hashlib.sha256).hexdigest()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """临时环境：外部系统配置 + 绑定文件 + SQLite 用户库 + 旧契约密钥。"""
    from coapis.foundation.repository_factory import RepositoryFactory

    systems_file = tmp_path / "external_systems_config.json"
    mappings_file = tmp_path / "external_identity_mappings.json"
    state_file = tmp_path / "external_login_states.json"
    auth_file = tmp_path / "auth.json"
    db_path = tmp_path / "test_coapis.db"

    system = {
        "provider_id": PROVIDER,
        "name": "测试 OA",
        "login_type": "sso_redirect",
        "sso": {
            "login_url": "https://oa.example.com/sso/login?client_id=coapis&state={state}&redirect={redirect}",
            "callback": {"timestamp_ttl": 300},
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
        "base_urls": ["https://oa.example.com"],
        "status": 1,
    }
    systems_file.write_text(json.dumps({"systems": [system]}, ensure_ascii=False))
    mappings_file.write_text(json.dumps({"bindings": []}))
    state_file.write_text(json.dumps({}))

    monkeypatch.setattr(core, "MAPPINGS_FILE", str(mappings_file))
    monkeypatch.setattr(core, "STATE_FILE", str(state_file))
    monkeypatch.setattr(external_identity, "SYSTEMS_CONFIG_FILE", str(systems_file))
    monkeypatch.setattr(auth_mod, "AUTH_FILE", auth_file)
    # 旧契约密钥：生产由 COAPIS_SSO_SECRET 提供（系统未配 shared_secret 时生效）
    monkeypatch.setenv("COAPIS_SSO_SECRET", SECRET)

    from coapis.foundation.db.base import Base
    from coapis.foundation.db.engine import get_engine, init_engine, reset_engine
    from coapis.foundation.user_repository_impl import SqlaUserRepository

    init_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(get_engine())
    RepositoryFactory.reset()
    RepositoryFactory._user_repo = SqlaUserRepository()
    RepositoryFactory._initialized = True
    RepositoryFactory._edition = "community"

    core._state_cache["data"] = {}
    core._state_cache["mtime"] = -1
    legacy._recent_tokens.clear()

    app = FastAPI()
    api_router = APIRouter()
    api_router.include_router(legacy.router)
    api_router.include_router(external_auth.router)
    app.include_router(api_router, prefix="/api")
    with TestClient(app) as client:
        yield client, str(mappings_file)

    RepositoryFactory.reset()
    try:
        reset_engine()
    except Exception:
        pass


def _bindings(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)["bindings"]


def _read_systems():
    with open(external_identity.SYSTEMS_CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)


def _write_systems(obj):
    with open(external_identity.SYSTEMS_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


# ---------------------------------------------------------------------------
# GET（生产主路径）
# ---------------------------------------------------------------------------

class TestLegacyGet:

    def test_valid_token_returns_html_with_token(self, env):
        client, _ = env
        r = client.get(
            "/api/external/login",
            params={"token": _sign(USERNAME), "username": USERNAME,
                    "display_name": "张三"},
        )
        assert r.status_code == 200
        assert "coapis_auth_token" in r.text
        assert USERNAME in r.text
        # 前端登录态契约（迁移前后必须一致）
        for key in ("coapis_saved_accounts", "coapis-agent-storage-",
                    "coapis-last-used-agent-", "coapis-current-username",
                    "AuthStorage.logout(false)"):
            assert key in r.text, key

    def test_token_issued_and_login_state(self, env):
        client, _ = env
        r = client.get("/api/external/login",
                       params={"token": _sign(USERNAME), "username": USERNAME})
        assert r.status_code == 200
        token = r.text.split("AuthStorage.login('", 1)[1].split("'", 1)[0]
        assert auth_mod.verify_token(token) == USERNAME
        # 新增：token 记录登录来源外部系统
        assert auth_mod.get_token_ext_provider(token) == PROVIDER

    def test_invalid_token_401(self, env):
        client, _ = env
        r = client.get("/api/external/login",
                       params={"token": "deadbeef", "username": USERNAME})
        assert r.status_code == 401

    def test_missing_username_422(self, env):
        client, _ = env
        r = client.get("/api/external/login", params={"token": _sign(USERNAME)})
        assert r.status_code == 422

    def test_missing_token_422(self, env):
        client, _ = env
        r = client.get("/api/external/login", params={"username": USERNAME})
        assert r.status_code == 422

    def test_redirect_defaults_to_chat(self, env):
        client, _ = env
        r = client.get("/api/external/login",
                       params={"token": _sign(USERNAME), "username": USERNAME})
        assert r.status_code == 200
        # 旧实现未传 redirect 时会拼出字符串 "None" 并跳转 /None —— 已修
        assert "const redirect = '/chat'" in r.text
        assert "None" not in r.text

    def test_insite_redirect_preserved(self, env):
        client, _ = env
        r = client.get("/api/external/login",
                       params={"token": _sign(USERNAME), "username": USERNAME,
                               "redirect": "/chat?agent=user:x"})
        assert "const redirect = '/chat?agent=user:x'" in r.text

    def test_open_redirect_blocked_to_chat(self, env):
        client, _ = env
        r = client.get("/api/external/login",
                       params={"token": _sign(USERNAME), "username": USERNAME,
                               "redirect": "https://evil.example.com"})
        assert "const redirect = '/chat'" in r.text

    def test_user_created_with_quota_and_muga_key(self, env):
        """建号唯一入口必须带 muga_key（旧新实现漏掉的字段）。"""
        client, _ = env
        r = client.get("/api/external/login",
                       params={"token": _sign(USERNAME), "username": USERNAME,
                               "display_name": "张三"})
        assert r.status_code == 200
        u = user_store.get_user(USERNAME)
        assert u is not None
        assert u.get("muga_key"), "muga_key 必须生成（用户隔离文件空间）"
        assert u.get("display_name") == "张三"
        assert u.get("password_set_by_user") in (0, False, None)

    def test_binding_written_on_login(self, env):
        """新增行为：旧契约登录写入外部身份绑定（旧实现完全不写）。"""
        client, mappings = env
        client.get("/api/external/login",
                   params={"token": _sign(USERNAME), "username": USERNAME,
                           "display_name": "张三"})
        bs = _bindings(mappings)
        assert len(bs) == 1
        assert bs[0]["user_id"] == USERNAME
        assert bs[0]["provider"] == PROVIDER
        assert bs[0]["source"] == "legacy_sso"

    def test_second_login_reuses_binding(self, env):
        client, mappings = env
        for _ in range(2):
            r = client.get("/api/external/login",
                           params={"token": _sign(USERNAME), "username": USERNAME})
            assert r.status_code == 200
        bs = _bindings(mappings)
        assert len(bs) == 1, "不得重复写绑定"
        assert bs[0]["login_count"] == 2

    def test_last_login_updated(self, env):
        client, _ = env
        client.get("/api/external/login",
                   params={"token": _sign(USERNAME), "username": USERNAME})
        assert user_store.get_user(USERNAME).get("last_login")

    def test_existing_user_password_untouched(self, env):
        client, _ = env
        user_store.create_user(USERNAME, "known-password-123", "李四")
        before = user_store.get_user(USERNAME)["password"]
        client.get("/api/external/login",
                   params={"token": _sign(USERNAME), "username": USERNAME})
        assert user_store.get_user(USERNAME)["password"] == before


# ---------------------------------------------------------------------------
# POST（JSON 契约）
# ---------------------------------------------------------------------------

class TestLegacyPost:

    def test_post_creates_user_and_returns_contract_fields(self, env):
        client, _ = env
        r = client.post("/api/external/login", json={
            "token": _sign(USERNAME), "username": USERNAME, "display_name": "张三",
        })
        assert r.status_code == 200
        data = r.json()
        assert set(data) == {"token", "username", "display_name", "is_new_user",
                             "default_agent_id", "redirect"}
        assert data["is_new_user"] is True
        assert data["username"] == USERNAME
        assert data["display_name"] == "张三"
        assert data["default_agent_id"] == f"user:{USERNAME}"
        assert data["redirect"] == "/chat"

    def test_post_existing_user_not_new(self, env):
        client, _ = env
        user_store.create_user(USERNAME, "pw-12345678", "李四")
        r = client.post("/api/external/login",
                        json={"token": _sign(USERNAME), "username": USERNAME})
        assert r.status_code == 200
        assert r.json()["is_new_user"] is False
        # 已有账号显示名不被外部入参覆盖
        assert r.json()["display_name"] == "李四"

    def test_post_invalid_token_401(self, env):
        client, _ = env
        r = client.post("/api/external/login",
                        json={"token": "nope", "username": USERNAME})
        assert r.status_code == 401

    def test_post_missing_username_422(self, env):
        client, _ = env
        r = client.post("/api/external/login", json={"token": _sign(USERNAME)})
        assert r.status_code == 422

    def test_post_invalid_json_422(self, env):
        client, _ = env
        r = client.post("/api/external/login", content=b"not-json",
                        headers={"Content-Type": "application/json"})
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# 外部系统解析与密钥来源
# ---------------------------------------------------------------------------

class TestProviderAndSecret:

    def test_single_system_used_when_provider_absent(self, env):
        client, mappings = env
        r = client.post("/api/external/login",
                        json={"token": _sign(USERNAME), "username": USERNAME})
        assert r.status_code == 200
        assert _bindings(mappings)[0]["provider"] == PROVIDER

    def test_explicit_unknown_provider_404(self, env):
        client, _ = env
        r = client.post("/api/external/login",
                        json={"token": _sign(USERNAME), "username": USERNAME,
                              "provider": "nope"})
        assert r.status_code == 404

    def test_per_system_secret_wins(self, env):
        """系统配置 shared_secret 时优先于环境变量（密钥解析唯一入口）。"""
        client, _ = env
        systems = _read_systems()
        systems["systems"][0]["shared_secret"] = "per-system-secret"
        _write_systems(systems)

        # 用 env 密钥签名 → 应失败
        r = client.post("/api/external/login",
                        json={"token": _sign(USERNAME), "username": USERNAME})
        assert r.status_code == 401
        # 用系统密钥签名 → 成功
        r = client.post("/api/external/login",
                        json={"token": _sign(USERNAME, "per-system-secret"),
                              "username": USERNAME})
        assert r.status_code == 200

    def test_secret_precedence_function(self, env):
        _, _ = env
        secret, source = core.resolve_login_secret(None, "legacy")
        assert (secret, source) == (SECRET, "env_COAPIS_SSO_SECRET")
        secret, source = core.resolve_login_secret({"shared_secret": "S"}, "legacy")
        assert (secret, source) == ("S", "system_shared_secret")
        secret, source = core.resolve_login_secret(None, "model_a")
        assert source == "env_global"

    def test_no_system_configured_still_logs_in_without_binding(self, env, monkeypatch):
        """0 个外部系统：登录可用（旧部署兼容），但不写绑定。"""
        client, mappings = env
        _write_systems({"systems": []})
        r = client.post("/api/external/login",
                        json={"token": _sign(USERNAME), "username": USERNAME})
        assert r.status_code == 200
        assert user_store.get_user(USERNAME) is not None
        assert _bindings(mappings) == []

    def test_multiple_systems_without_provider_skips_binding(self, env):
        client, mappings = env
        systems = _read_systems()
        extra = dict(systems["systems"][0])
        extra["provider_id"] = "other_oa"
        systems["systems"].append(extra)
        _write_systems(systems)

        r = client.post("/api/external/login",
                        json={"token": _sign(USERNAME), "username": USERNAME})
        assert r.status_code == 200
        assert _bindings(mappings) == []

    def test_multiple_systems_with_provider_binds(self, env):
        client, mappings = env
        systems = _read_systems()
        extra = dict(systems["systems"][0])
        extra["provider_id"] = "other_oa"
        systems["systems"].append(extra)
        _write_systems(systems)

        r = client.post("/api/external/login",
                        json={"token": _sign(USERNAME), "username": USERNAME,
                              "provider": "other_oa"})
        assert r.status_code == 200
        assert _bindings(mappings)[0]["provider"] == "other_oa"


# ---------------------------------------------------------------------------
# 单一真源：旧契约与模型A 共用同一份身份解析
# ---------------------------------------------------------------------------

class TestSingleSourceOfTruth:

    def test_legacy_and_model_a_share_core(self, env):
        """旧契约建的账号，模型A（SSO 回调）登录同一人时复用同一账号。"""
        client, mappings = env
        r = client.get("/api/external/login",
                       params={"token": _sign(USERNAME), "username": USERNAME,
                               "display_name": "张三"})
        assert r.status_code == 200

        # 模型A：external_id 与旧契约 username 相同 → 绑定命中 → 复用账号
        ts = int(time.time())
        state = client.get(f"/api/auth/external/login-state?provider={PROVIDER}"
                           ).json()["data"]["state"]
        # 模型A 契约的密钥来源与旧契约不同（系统未配 shared_secret 时走全局密钥），
        # 必须按同一入口取密钥，不能拿 legacy 的 env 密钥签名。
        sig = _sign_model_a(PROVIDER, USERNAME, ts,
                            secret=core.resolve_login_secret(None, "model_a")[0])
        r2 = client.post("/api/auth/external/login", json={
            "provider": PROVIDER, "external_id": USERNAME, "timestamp": ts,
            "signature": sig, "state": state, "external_name": "张三",
        })
        assert r2.status_code == 200, r2.text
        assert r2.json()["username"] == USERNAME, "同一外部身份必须落同一账号"
        assert len(_bindings(mappings)) == 1

    def test_split_detection_is_readonly(self, env):
        """同名分身只告警，绝不改数据。"""
        client, mappings = env
        # 先造一个已绑定的同名账号
        user_store.create_user("oa_0001", "pw-12345678", "张三")
        core.bind_matched_existing_user(
            "oa_0001", PROVIDER, "144", "张三",
            {"bindings": []}, None, source="auto")
        before = _bindings(mappings)

        r = client.get("/api/external/login",
                       params={"token": _sign(USERNAME), "username": USERNAME,
                               "display_name": "张三"})
        assert r.status_code == 200
        after = _bindings(mappings)
        assert len(after) == len(before) + 1, "只新增自己的绑定"
        assert all(b["user_id"] == "oa_0001" for b in before), "不得改动他人绑定"


def _sign_model_a(provider, external_id, ts, secret=SECRET):
    s = f"provider={provider}&external_id={external_id}&timestamp={ts}"
    return hmac_mod.new(secret.encode(), s.encode(), hashlib.sha256).hexdigest()
