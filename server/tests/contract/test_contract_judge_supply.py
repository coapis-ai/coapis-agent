# -*- coding: utf-8 -*-
"""B0 契约锁 · 判官供给面（方案 v1 §3 第 0 批 / D14）

**口径照抄代码**（``coapis/decision/resolver.py`` 的公开面就是
``__all__`` 那六个名字）。今天已成立的行为是**现状锁**——B3 把判官接真时
不许把它们改松：

* ``assert_chat_capable``：类型以 ``ModelInfo.model_type``（用户在模型管理
  里的显式分类）为准，缺失时按名字推断，**推断值带 ``(推断)`` 标记** ——
  台账不许把推断当声明。
* 模型必须真实存在（用户删模型后偏好会变陈旧 → 降级不判断）。
* ``judge_enabled=False`` 就是不供给（关闭就是关闭）。
* 两处（hub 显式键 / decision 槽位）都空 → ``None`` = 判官不上岗，
  **绝不兜底会话激活模型**（D-A 拍板：不借对话模型，避免"模型切换攻击"）。
* 内网端点空 Key 合法（v25 实锤：Key 判定归 provider 层，判定层不得越界）。

B1 目标锁（``xfail(strict=True)``）：判官直连 provider，绕开
``RetryChatModel`` —— 失败既不计 token 也不计可用性，于是"判官没意见"
与"判官连不上"在看板上长得一模一样。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from coapis.decision import resolver as rs

B1 = pytest.mark.xfail(
    strict=True,
    reason="B1 目标契约：判官调用纳入重试/可用性台账（未实现）",
)


def _model(model_id: str, model_type: str | None) -> SimpleNamespace:
    return SimpleNamespace(id=model_id, name=model_id, model_type=model_type)


def _provider(models: list[SimpleNamespace], base_url: str = "http://127.0.0.1:8085/v1"):
    return SimpleNamespace(
        provider_id="p1",
        models=models,
        base_url=base_url,
        api_key="",
        list_models=lambda: [m.id for m in models],
    )


@pytest.fixture()
def use_provider(monkeypatch):
    """把 resolver 取 provider 的入口换成测试桩（它内部是延迟 import）。"""
    import coapis.providers.provider_manager as pm

    def _apply(provider):
        monkeypatch.setattr(pm.ProviderManager, "get_instance", lambda: provider)

    return _apply


@pytest.fixture()
def slot(monkeypatch):
    """控制 decision 槽位（判官的第二供给来源）。"""

    def _apply(pair: tuple[str, str]) -> None:
        monkeypatch.setattr(rs, "_decision_slot_pair", lambda: pair)

    return _apply


# ── 1. 类型硬闸：不是 chat 的模型绝不能当判官 ───────────────────────────


@pytest.mark.parametrize("bad_type", ["embedding", "rerank", "tts", "asr", "image"])
def test_assert_chat_capable_rejects_declared_non_chat(bad_type):
    # "嵌入模型当判官"的根治点：这类模型在 OpenAI 兼容接口上**不报错**，
    # 只是永远读不出结论。必须在进入判断之前挡掉。
    provider = _provider([_model("m-1", bad_type)])
    ok, got = rs.assert_chat_capable(provider, "m-1")
    assert ok is False
    assert got == bad_type


def test_assert_chat_capable_accepts_chat():
    provider = _provider([_model("m-1", "chat")])
    ok, got = rs.assert_chat_capable(provider, "m-1")
    assert ok is True
    assert got == "chat"


def test_inferred_type_is_marked_as_inference():
    # 用户没标类型时按名字兜底推断，但**必须带 (推断) 标记**：
    # 台账/看板不许把推断值当作用户的显式分类。
    provider = _provider([_model("qwen3-embedding-v3", None)])
    ok, got = rs.assert_chat_capable(provider, "qwen3-embedding-v3")
    assert ok is False
    assert "推断" in got


def test_model_missing_from_list_falls_back_to_name_inference():
    provider = _provider([_model("other", "chat")])
    ok, got = rs.assert_chat_capable(provider, "qwen3-embedding-v3")
    assert ok is False  # 名字推成 embedding 就挡掉
    assert "推断" in got


def test_provider_without_models_is_not_vetoed():
    # 探测能力缺失不该顺手关掉判官（v25 越界教训：判定层不许杀供给）。
    # 无 models 时按名字推断，值带 (推断) 标记。
    ok, got = rs.assert_chat_capable(SimpleNamespace(), "some-model")
    assert ok is True
    assert "推断" in got


def test_provider_with_empty_model_list_is_not_vetoed():
    provider = SimpleNamespace(models=[], list_models=lambda: [])
    ok, _got = rs.assert_chat_capable(provider, "qwen-plus")
    assert ok is True


# ── 2. 内网端点判定：无 Key 的本地模型是合法判官 ────────────────────────


@pytest.mark.parametrize(
    "url,expected",
    [
        ("http://localhost:8085/v1", True),
        ("http://127.0.0.1:8080/v1", True),
        ("http://192.168.1.20:11434", True),
        ("https://api.openai.com/v1", False),
        ("", False),
    ],
)
def test_is_local_base_url_classifies_intranet_endpoints(url, expected):
    assert rs.is_local_base_url(url) is expected


def test_ollama_detection_is_a_separate_ruler():
    # Ollama 的 /api/chat 与 OpenAI 兼容 /v1 是两套端点，混判必 404。
    assert rs.is_ollama_base_url("http://127.0.0.1:11434") is True
    assert rs.is_ollama_base_url("http://127.0.0.1:8085/v1") is False


def test_local_endpoints_are_keyless_legal():
    assert rs.is_local_base_url("http://127.0.0.1:8085/v1") is True


# ── 3. 配置组装：不合格就降级，绝不带病上岗 ─────────────────────────────


def test_build_provider_config_rejects_missing_provider(use_provider):
    use_provider(SimpleNamespace(get_provider=lambda pid: None))
    assert rs.build_provider_config("ghost", "m1") is None


def test_build_provider_config_rejects_deleted_model(use_provider):
    use_provider(
        SimpleNamespace(
            get_provider=lambda pid: _provider([_model("other", "chat")]),
        ),
    )
    # 用户删模型后偏好会变陈旧：必须降级，不能拿幽灵模型去调用
    assert rs.build_provider_config("p1", "gone-model") is None


def test_build_provider_config_rejects_embedding_model(use_provider):
    use_provider(
        SimpleNamespace(
            get_provider=lambda pid: _provider([_model("qwen3-embedding-v3", "embedding")]),
        ),
    )
    assert rs.build_provider_config("p1", "qwen3-embedding-v3") is None


def test_build_provider_config_normalizes_api_base(use_provider):
    provider = _provider([_model("local-judge", "chat")], base_url="http://127.0.0.1:8085/v1/")
    use_provider(SimpleNamespace(get_provider=lambda pid: provider))
    out_source: dict = {}
    cfg = rs.build_provider_config("p1", "local-judge", out_source, source="judge")
    assert cfg is not None
    # 去尾斜杠：下游拼 f"{api_base}/chat/completions"，带斜杠会拼出
    # "//chat/completions" 这种 404（网关里同类坑已踩过一次）。
    assert cfg["api_base"] == "http://127.0.0.1:8085/v1"
    assert not cfg["api_base"].endswith("/")
    assert cfg["model_type"] == "chat"
    assert cfg["provider_id"] == "p1" and cfg["model"] == "local-judge"
    # 命中层写进 out_source（台账/看板据此分桶）；配置字典本身**不带** source。
    assert out_source["source"] == "judge"
    assert "source" not in cfg


def test_build_provider_config_marks_undeclared_type(use_provider):
    provider = _provider([_model("mystery", None)])
    use_provider(SimpleNamespace(get_provider=lambda pid: provider))
    cfg = rs.build_provider_config("p1", "mystery")
    assert cfg is not None
    # 名字推不出类型 → 按 chat 放行，但必须留痕
    assert "chat" in cfg["model_type"]


# ── 4. 供给取位：hub 显式键优先，槽位次之，皆空则不判断 ─────────────────


def test_hub_judge_keys_win_over_decision_slot(use_provider, slot):
    provider = _provider([_model("hub-judge", "chat"), _model("slot-judge", "chat")])
    use_provider(SimpleNamespace(get_provider=lambda pid: provider))
    slot(("p1", "slot-judge"))
    hub = SimpleNamespace(judge_provider_id="p1", judge_model="hub-judge", judge_enabled=True)
    out_source: dict = {}
    cfg = rs.get_judge_provider_config(hub, out_source=out_source)
    assert cfg is not None
    assert cfg["model"] == "hub-judge"
    # 命中层写进 out_source（台账/看板据此分桶）。字面量以代码为准：
    # hub 显式键 = "judge_slot"，槽位 = "decision_slot"。
    assert out_source["source"] == "judge_slot"


def test_falls_back_to_decision_slot_when_hub_empty(use_provider, slot):
    provider = _provider([_model("slot-judge", "chat")])
    use_provider(SimpleNamespace(get_provider=lambda pid: provider))
    slot(("p1", "slot-judge"))
    hub = SimpleNamespace(judge_provider_id="", judge_model="", judge_enabled=True)
    out_source: dict = {}
    cfg = rs.get_judge_provider_config(hub, out_source=out_source)
    assert cfg is not None
    assert cfg["model"] == "slot-judge"
    assert out_source["source"] == "decision_slot"


def test_empty_everywhere_means_no_judge(use_provider, slot):
    # 判官不上岗是合法状态：返回 None，上层弃权并记台账。
    # **绝不兜底会话激活模型**（D-A 拍板：不借对话模型）。
    provider = _provider([_model("chat-model", "chat")])
    use_provider(SimpleNamespace(get_provider=lambda pid: provider))
    slot(("", ""))
    hub = SimpleNamespace(judge_provider_id="", judge_model="", judge_enabled=True)
    assert rs.get_judge_provider_config(hub) is None


def test_disabled_switch_is_not_enforced_at_supply_layer(use_provider, slot):
    # 实测现状（B0 取证，锁住它，别以为开关在供给层）：
    # ``get_judge_provider_config`` **完全不看 judge_enabled**，四种组合
    # 都给配置。关闭判官靠各消费点自己判断 judge_enabled。
    # 含义：任何新增消费点忘记自查开关，就会"关了判官仍在判断"。
    # B3 目标锁见下方 test_supply_layer_honours_disabled_switch。
    provider = _provider([_model("hub-judge", "chat")])
    use_provider(SimpleNamespace(get_provider=lambda pid: provider))
    slot(("p1", "hub-judge"))
    hub = SimpleNamespace(judge_provider_id="p1", judge_model="hub-judge", judge_enabled=False)
    assert rs.get_judge_provider_config(hub) is not None


@B1
def test_supply_layer_honours_disabled_switch(use_provider, slot):
    # B3 目标：开关应该在供给层生效一次，免得每个消费点各抄一份判定
    # （今天 judge_enabled 在 gateway/plan_gate/selfcheck 里各查一遍）。
    provider = _provider([_model("hub-judge", "chat")])
    use_provider(SimpleNamespace(get_provider=lambda pid: provider))
    slot(("p1", "hub-judge"))
    hub = SimpleNamespace(judge_provider_id="p1", judge_model="hub-judge", judge_enabled=False)
    assert rs.get_judge_provider_config(hub) is None


def test_judge_supply_rejects_embedding_slot_without_crash(use_provider, slot):
    # 槽位被配成嵌入模型：供给必须降级为 None（不是异常、不是静默判断）。
    provider = _provider([_model("qwen3-embedding-v3", "embedding")])
    use_provider(SimpleNamespace(get_provider=lambda pid: provider))
    slot(("p1", "qwen3-embedding-v3"))
    hub = SimpleNamespace(judge_provider_id="", judge_model="", judge_enabled=True)
    assert rs.get_judge_provider_config(hub) is None


def test_judgment_config_entry_degrades_on_resolver_failure(use_provider, slot, monkeypatch):
    # 解析入口坏了 → 降级不判断（返回 None），绝不抛异常停主链。
    import coapis.app.routers.user_model_prefs as ump

    def _boom(*_a, **_k):
        raise RuntimeError("prefs exploded")

    monkeypatch.setattr(ump, "resolve_chat_model_slot", _boom)
    use_provider(SimpleNamespace(get_provider=lambda pid: None))
    slot(("", ""))
    assert rs.get_judgment_provider_config("u1", "a1") is None


# ── 5. 公开面：契约只锁 __all__ 里真实存在的名字 ────────────────────────


def test_public_surface_is_the_documented_set():
    assert set(rs.__all__) >= {
        "is_local_base_url",
        "is_ollama_base_url",
        "assert_chat_capable",
        "get_judgment_provider_config",
        "build_provider_config",
        "get_judge_provider_config",
    }


def test_source_whitelist_covers_the_five_posts():
    # 判官五岗名必须与台账岗位白名单同源（两处各写一份就会漂移）。
    from coapis.decision import ledger_contract as lc

    posts = {"plan_gate", "plan_review", "skill_trigger", "tool_gate", "acceptance"}
    assert posts <= set(lc.SOURCES)


# ── 6. B1 目标：判官也要进可用性台账 ────────────────────────────────────


@B1
def test_judge_config_carries_availability_ledger_key(use_provider, slot):
    # 判官直连 provider，绕开 RetryChatModel：失败不计 token、也不计
    # 可用性。B1 要求供给结果带可用性台账键，使"没意见"与"连不上"可分。
    provider = _provider([_model("slot-judge", "chat")])
    use_provider(SimpleNamespace(get_provider=lambda pid: provider))
    slot(("p1", "slot-judge"))
    hub = SimpleNamespace(judge_provider_id="", judge_model="", judge_enabled=True)
    cfg = rs.get_judge_provider_config(hub)
    assert cfg is not None
    assert cfg.get("availability_key") == "p1:slot-judge"