# -*- coding: utf-8 -*-
"""C1 dream 闭环测试：结局判定纯函数 + dream() 记账胶水 + 故障安全。

独立运行：python tests/test_dream_outcome.py
"""

import asyncio
import importlib
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

# Host-side shim: coapis.constant reads .env via python-dotenv, which is
# absent on bare hosts (present in the container). Provide a no-op module
# so the import chain succeeds everywhere.
try:
    import dotenv  # noqa: F401
except ImportError:
    _fake_dotenv = types.ModuleType("dotenv")
    _fake_dotenv.load_dotenv = lambda *args, **kwargs: None
    sys.modules["dotenv"] = _fake_dotenv

RESULTS: list = []


def check(name: str, cond: bool, detail: str = ""):
    RESULTS.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not cond else ""))


def _stub_agentscope_runtime():
    try:
        importlib.import_module("agentscope_runtime.engine.schemas.exception")
        return
    except Exception:  # noqa: BLE001
        pass
    for name in (
        "agentscope_runtime",
        "agentscope_runtime.engine",
        "agentscope_runtime.engine.schemas",
        "agentscope_runtime.engine.schemas.exception",
    ):
        sys.modules.setdefault(name, MagicMock())


def test_compute_dream_outcome():
    from coapis.agents.memory.dream_outcome import (
        STATUS_FAILED, STATUS_PARTIAL, STATUS_SKIPPED, STATUS_SUCCESS,
        compute_dream_outcome,
    )

    s, r, _ = compute_dream_outcome({})
    check("空结果 → skipped/no_input", s == STATUS_SKIPPED and r == "no_input", f"{s},{r}")

    s, r, _ = compute_dream_outcome({"": "ok"})
    check("全 ok → success", s == STATUS_SUCCESS, f"{s}")

    s, r, _ = compute_dream_outcome({"L3": "ok", "L2": "ok", "L1": "skipped"})
    check("ok+skipped → success", s == STATUS_SUCCESS, f"{s}")

    s, r, _ = compute_dream_outcome({"智能体级": "ok", "用户级": "error"})
    check("ok+error → partial/mixed_levels",
          s == STATUS_PARTIAL and r == "mixed_levels", f"{s},{r}")

    s, r, _ = compute_dream_outcome({"a": "error", "b": "error"})
    check("全 error → failed/llm_error",
          s == STATUS_FAILED and r == "llm_error", f"{s},{r}")

    s, r, summ = compute_dream_outcome({"b": "ok", "a": "skipped"})
    check("summary 按级别排序", summ == "a=skipped,b=ok", summ)


def test_dream_records_outcome():
    from coapis.agents.memory import reme_light_memory_manager as rlmm
    from coapis.agents.memory.reme_light_memory_manager import (
        ReMeLightMemoryManager,
    )
    from coapis.foundation.db.engine import init_engine, get_engine, reset_engine
    from coapis.foundation.db.base import BaseRow
    from coapis.foundation.repository_factory import RepositoryFactory

    tmp = Path(tempfile.mkdtemp(prefix="dream_outcome_test_"))
    init_engine("sqlite:///" + str(tmp / "t.db"))
    BaseRow.metadata.create_all(get_engine())
    RepositoryFactory.initialize(edition="community")

    # 桩掉 LLM 相关
    orig_cfg, orig_cf = rlmm.load_agent_config, rlmm.create_model_and_formatter
    rlmm.load_agent_config = lambda aid: types.SimpleNamespace(language="zh")
    rlmm.create_model_and_formatter = lambda aid: (object(), object())

    mgr = ReMeLightMemoryManager(str(tmp), "a1", None)

    async def _fake_ok(*a, **k):
        return "ok"

    async def _fake_err(*a, **k):
        return "error"

    try:
        # 1. 成功场景
        mgr._dream_level = _fake_ok
        asyncio.new_event_loop().run_until_complete(mgr.dream())
        repo = RepositoryFactory.get_memory_repository()
        rows = repo.list_entries(user_id="", category="dream")
        check("成功后台账有 dream 行", len(rows) == 1, f"got {len(rows)}")
        row1 = rows[0] if rows else None
        check("内容为 status=success",
              row1 is not None and "status=success" in (row1.content or ""),
              row1.content if row1 else "no row")
        check("source=dream", row1 is not None and row1.source == "dream")

        # 2. 失败场景 → 同日 upsert 覆盖（同 id）
        mgr._dream_level = _fake_err
        asyncio.new_event_loop().run_until_complete(mgr.dream())
        rows2 = repo.list_entries(user_id="", category="dream")
        check("再次运行不产生第二行", len(rows2) == 1, f"got {len(rows2)}")
        check("覆盖为 status=failed",
              rows2 and "status=failed" in (rows2[0].content or ""),
              rows2[0].content if rows2 else "no row")

        # 3. 混合场景（两级：ok + error → partial）
        mgr2 = ReMeLightMemoryManager(str(tmp), "a1", "tester")

        async def _fake_mixed(target_dir, *a, **k):
            label = k.get("level_label", "")
            return "ok" if label == "智能体级" else "error"

        mgr2._dream_level = _fake_mixed
        asyncio.new_event_loop().run_until_complete(mgr2.dream())
        rows3 = repo.list_entries(user_id="tester", category="dream")
        check("混合场景 → partial",
              rows3 and "status=partial" in (rows3[0].content or ""),
              rows3[0].content if rows3 else "no row")
    finally:
        rlmm.load_agent_config = orig_cfg
        rlmm.create_model_and_formatter = orig_cf
        RepositoryFactory.reset()
        reset_engine()


def test_dream_fail_safe_without_ledger():
    from coapis.agents.memory import reme_light_memory_manager as rlmm
    from coapis.agents.memory.reme_light_memory_manager import (
        ReMeLightMemoryManager,
    )
    from coapis.foundation.repository_factory import RepositoryFactory

    RepositoryFactory.reset()  # 未初始化 → ledger 不可用

    tmp = Path(tempfile.mkdtemp(prefix="dream_failsafe_test_"))
    orig_cfg, orig_cf = rlmm.load_agent_config, rlmm.create_model_and_formatter
    rlmm.load_agent_config = lambda aid: types.SimpleNamespace(language="zh")
    rlmm.create_model_and_formatter = lambda aid: (object(), object())
    try:
        mgr = ReMeLightMemoryManager(str(tmp), "a1", None)

        async def _fake_ok(*a, **k):
            return "ok"

        mgr._dream_level = _fake_ok
        try:
            asyncio.new_event_loop().run_until_complete(mgr.dream())
            check("ledger 不可用时 dream 不抛异常", True)
        except Exception as e:  # noqa: BLE001
            check("ledger 不可用时 dream 不抛异常", False, repr(e))
    finally:
        rlmm.load_agent_config = orig_cfg
        rlmm.create_model_and_formatter = orig_cf
        RepositoryFactory.reset()


def main():
    _stub_agentscope_runtime()
    test_compute_dream_outcome()
    test_dream_records_outcome()
    test_dream_fail_safe_without_ledger()
    total = len(RESULTS)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n===== {passed}/{total} passed =====")
    if passed != total:
        for name, ok, detail in RESULTS:
            if not ok:
                print(f"  FAIL: {name} {detail}")
        sys.exit(1)


if __name__ == "__main__":
    main()
