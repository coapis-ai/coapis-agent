"""v16 模型管理两项修复的回归测试。

问题 1：一次聊天触发的后台探测把 qwen-flash 的 19 个网关模型灌进了手加的 2 个
        模型列表 → 探测只许学窗口，不许灌模型；自定义提供商默认"只手加"。
问题 2：决策模型（判官）有分类无槽位 → 默认槽位体系加第 6 个 decision 槽位，
        判官解析按 判官槽位 > 决策模型槽位 > 无 的优先级取。
"""

from __future__ import annotations

from coapis.providers.model_type import VALID_DEFAULT_SLOTS, VALID_MODEL_TYPES
from coapis.providers.provider import (
    DEFAULT_MODEL_SLOTS,
    DefaultModelSlot,
    DefaultModelsConfig,
    ModelInfo,
    ProviderInfo,
)
from coapis.providers.provider_manager import Provider, ProviderManager


# ---------------------------------------------------------------- 槽位定义 ----
def test_decision_slot_is_a_default_slot_not_a_model_type():
    """decision 是"用途槽位"：在槽位名单里，但不在模型类型名单里。"""
    assert "decision" in VALID_DEFAULT_SLOTS
    assert "decision" not in VALID_MODEL_TYPES
    assert DEFAULT_MODEL_SLOTS == tuple(VALID_DEFAULT_SLOTS)


def test_legacy_default_models_file_without_model_type_still_loads():
    """历史文件（to_dict 曾漏写 model_type）必须能读回来，不能触发重置。"""
    cfg = DefaultModelsConfig.model_validate(
        {"chat": {"provider_id": "p", "model_id": "m"}},
    )
    assert cfg.get_by_type("chat").model_id == "m"


def test_to_dict_writes_every_slot_including_decision():
    cfg = DefaultModelsConfig()
    cfg.set_by_type(
        "decision",
        DefaultModelSlot(
            provider_id="qwen-flash",
            model_id="auto",
            model_type="decision",
        ),
    )
    dumped = cfg.to_dict()
    assert dumped["decision"]["model_id"] == "auto"
    # 只写配置了的槽位（None 不落盘），键名必须来自共享槽位名单
    assert set(dumped) <= set(DEFAULT_MODEL_SLOTS)
    assert "decision" in DEFAULT_MODEL_SLOTS
    # 写出去的文件必须能被自己读回来（往返损坏曾让默认模型每次启动被清空）
    again = DefaultModelsConfig.model_validate(dumped)
    assert again.get_by_type("decision").provider_id == "qwen-flash"


# ------------------------------------------------------- manual-only 三态 ----
def test_custom_provider_is_manual_only_by_default():
    """None = 按类型默认：自定义提供商只用手加的模型。"""
    p = ProviderInfo(id="x", name="x", chat_model="c", is_custom=True)
    assert p.manual_models_only is None
    assert p.keeps_models_manual() is True


def test_builtin_provider_imports_models_by_default():
    p = ProviderInfo(id="y", name="y", chat_model="c", is_custom=False)
    assert p.keeps_models_manual() is False


def test_explicit_override_wins_over_kind_default():
    p = ProviderInfo(
        id="z",
        name="z",
        chat_model="c",
        is_custom=False,
        manual_models_only=True,
    )
    assert p.keeps_models_manual() is True
    q = ProviderInfo(
        id="w",
        name="w",
        chat_model="c",
        is_custom=True,
        manual_models_only=False,
    )
    assert q.keeps_models_manual() is False


def test_manual_models_only_survives_the_serialization_round_trip():
    """老文件没有这个键也必须加载成功，且新写出的文件带着它。"""
    old = ProviderInfo.model_validate({"id": "o", "name": "o", "chat_model": "c"})
    assert old.manual_models_only is None
    assert "manual_models_only" in old.model_dump()


# ----------------------------------------------------------- 探测/发现 行为 ----
class _StubProvider(Provider):
    """`Provider` 是抽象基类，测试不能直接实例化（缺 4 个抽象方法必 TypeError）。

    这里给一个最小的具体子类：连接检查恒真、模型实例不给，fetch_models 由每个
    用例自己 monkeypatch。
    """

    async def check_connection(self, timeout: float = 5) -> tuple[bool, str]:
        return True, "stub"

    async def fetch_models(self, timeout: float = 5):  # pragma: no cover
        return list(self.models)

    async def check_model_connection(
        self,
        model_id: str,
        timeout: float = 5,
    ) -> tuple[bool, str]:
        return True, "stub"

    def get_chat_model_instance(self, model_id: str):  # pragma: no cover
        raise NotImplementedError("stub provider")


def _stub_manager(tmp_path, provider: Provider, saved: list) -> ProviderManager:
    """最小可用的 ProviderManager：不碰磁盘，只记录"是否落盘"。"""
    mgr = ProviderManager.__new__(ProviderManager)
    mgr.custom_providers_dir = tmp_path
    mgr.builtin_providers = {}
    mgr.plugin_providers = {}
    mgr.core_providers = {}
    mgr.profiles = {}
    mgr.active_model = None
    mgr.default_models = DefaultModelsConfig()
    mgr.get_provider = lambda pid: provider
    mgr._normalize_provider_id = lambda pid: pid
    mgr._save_provider = lambda p, is_builtin=False: saved.append(
        [m.id for m in p.models],
    )
    mgr._save_plugin_provider = lambda p: saved.append([m.id for m in p.models])
    return mgr


GATEWAY_REPORT = [
    ModelInfo(id="auto", name="auto", max_sequence_length=131072),
    ModelInfo(id="glm-5.3", name="glm-5.3"),
    ModelInfo(id="qwen3.8-max", name="qwen3.8-max"),
    ModelInfo(id="wan3.0-video", name="wan3.0-video"),
    ModelInfo(id="deepseek-v4.1-flash", name="deepseek-v4.1-flash"),
]


async def test_probe_fills_windows_without_importing_models(tmp_path, monkeypatch):
    """后台探测：学到窗口要写，看见新模型不许加（问题 1 的核心断言）。"""
    provider = _StubProvider(
        **ProviderInfo(
            id="qwen-flash",
            name="qwen-flash",
            chat_model="OpenAIChatModel",
            is_custom=True,
            base_url="https://example.test/v1",
        ).model_dump(),
    )
    provider.models = [ModelInfo(id="auto", name="auto", max_sequence_length=None)]
    saved: list = []
    mgr = _stub_manager(tmp_path, provider, saved)

    async def fake_fetch(self):
        return list(GATEWAY_REPORT)

    monkeypatch.setattr(_StubProvider, "fetch_models", fake_fetch)
    mgr._auto_probe_models = lambda p, added: _noop()

    fetched = await mgr.fetch_provider_models(
        "qwen-flash",
        save=True,
        persist_new_models=False,
    )

    assert len(fetched) == 5, "返回值仍是网关报的全集（预览要用）"
    assert [m.id for m in provider.models] == ["auto"], "探测不得灌模型进列表"
    assert provider.models[0].max_sequence_length == 131072, "窗口必须学到"
    assert saved, "学到东西才落盘"


async def test_probe_without_new_info_does_not_rewrite_the_file(tmp_path, monkeypatch):
    """探测每次聊天都可能跑：没学到新东西就不许重写 provider 文件。"""
    provider = _StubProvider(
        **ProviderInfo(
            id="qwen-flash",
            name="qwen-flash",
            chat_model="OpenAIChatModel",
            is_custom=True,
        ).model_dump(),
    )
    provider.models = [
        ModelInfo(id="auto", name="auto", max_sequence_length=131072),
    ]
    saved: list = []
    mgr = _stub_manager(tmp_path, provider, saved)

    async def fake_fetch(self):
        return [ModelInfo(id="auto", name="auto", max_sequence_length=131072)]

    monkeypatch.setattr(_StubProvider, "fetch_models", fake_fetch)
    await mgr.fetch_provider_models(
        "qwen-flash",
        save=True,
        persist_new_models=False,
    )
    assert saved == [], "无变化不落盘"


async def test_custom_provider_refuses_import_even_when_caller_asks(
    tmp_path,
    monkeypatch,
):
    """自定义提供商 = 只手加：调用方要 save 也不灌（D1 默认口径）。"""
    provider = _StubProvider(
        **ProviderInfo(
            id="gw",
            name="gw",
            chat_model="OpenAIChatModel",
            is_custom=True,
        ).model_dump(),
    )
    provider.models = [ModelInfo(id="mine", name="mine")]
    saved: list = []
    mgr = _stub_manager(tmp_path, provider, saved)

    async def fake_fetch(self):
        return [
            ModelInfo(id="mine", name="mine"),
            ModelInfo(id="other", name="other"),
        ]

    monkeypatch.setattr(_StubProvider, "fetch_models", fake_fetch)
    mgr._auto_probe_models = lambda p, added: _noop()

    fetched = await mgr.fetch_provider_models("gw", save=True)
    assert [m.id for m in provider.models] == ["mine"]
    assert {m.id for m in fetched} == {"mine", "other"}


async def test_imported_models_are_marked_discovered_not_added(
    tmp_path,
    monkeypatch,
):
    """只有用户手加的才是 'added'；导入进来的必须说实话。"""
    provider = _StubProvider(
        **ProviderInfo(
            id="gw2",
            name="gw2",
            chat_model="OpenAIChatModel",
            is_custom=True,
            manual_models_only=False,  # 显式允许导入，用于验证来源标签
        ).model_dump(),
    )
    provider.models = [ModelInfo(id="mine", name="mine", source="added")]
    saved: list = []
    mgr = _stub_manager(tmp_path, provider, saved)

    async def fake_fetch(self):
        return [
            ModelInfo(id="mine", name="mine"),
            ModelInfo(id="newcomer", name="newcomer"),
        ]

    monkeypatch.setattr(_StubProvider, "fetch_models", fake_fetch)
    mgr._auto_probe_models = lambda p, added: _noop()

    await mgr.fetch_provider_models("gw2", save=True)
    by_id = {m.id: m for m in provider.models}
    assert by_id["mine"].source == "added", "手加标签不许被改写"
    assert by_id["newcomer"].source == "discovered", "导入必须说实话"


async def _noop():
    return None


# ---------------------------------------------------------------- 判官解析 ----
class _Hub:
    def __init__(self, judge_provider_id="", judge_model=""):
        self.judge_provider_id = judge_provider_id
        self.judge_model = judge_model


def test_no_config_means_no_judge(monkeypatch):
    """两边都没配 → None：判官不上岗，各岗按规则直判（设计内）。"""
    from coapis.decision import resolver

    monkeypatch.setattr(resolver, "_decision_slot_pair", lambda: ("", ""))
    assert resolver.get_judge_provider_config(_Hub()) is None


def test_decision_slot_is_used_when_hub_slot_empty(monkeypatch):
    from coapis.decision import resolver

    monkeypatch.setattr(
        resolver,
        "_decision_slot_pair",
        lambda: ("qwen-flash", "auto"),
    )
    monkeypatch.setattr(
        resolver,
        "build_provider_config",
        lambda pid, mid, out=None, source="": {
            "provider_id": pid,
            "model": mid,
            "source": source,
        },
    )
    cfg = resolver.get_judge_provider_config(_Hub(), out_source={})
    assert cfg is not None
    assert cfg["provider_id"] == "qwen-flash"
    assert cfg["source"] == "decision_slot"


def test_hub_slot_outranks_decision_slot(monkeypatch):
    """兼容期：判官槽位（hub 的历史键）优先级高于决策模型槽位。"""
    from coapis.decision import resolver

    monkeypatch.setattr(
        resolver,
        "_decision_slot_pair",
        lambda: ("slot-p", "slot-m"),
    )
    monkeypatch.setattr(
        resolver,
        "build_provider_config",
        lambda pid, mid, out=None, source="": {
            "provider_id": pid,
            "model": mid,
            "source": source,
        },
    )
    cfg = resolver.get_judge_provider_config(_Hub("hub-p", "hub-m"), out_source={})
    assert cfg["provider_id"] == "hub-p"
    assert cfg["source"] == "judge_slot"
