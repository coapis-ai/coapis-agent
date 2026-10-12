# -*- coding: utf-8 -*-
"""夜间 dream 管线接线测试（F1/F2：runtime 走 registry 后端 + 去重）。

覆盖：
  A. runner 带 memory_backend（含 dream()）时，callback 调 backend.dream()，
     不调 legacy memory_manager.dream()；
  B. callback 自身不再 record_outcome（dream() 内部已记录，防每晚双行）；
  C. 无 memory_backend 时回退 memory_manager.dream()；
  D. 两者都没有 dream() 时优雅报错，不抛异常。

独立运行：python tests/test_dream_callback_wiring.py
"""

import asyncio
import importlib
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

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


_stub_agentscope_runtime()


def _make_runner(with_backend: bool, backend_has_dream: bool = True,
                 legacy_has_dream: bool = True):
    runner = MagicMock()
    runner.backend_calls = 0
    runner.legacy_calls = 0
    if with_backend:
        backend = MagicMock()
        if backend_has_dream:
            async def _dream(**kw):
                runner.backend_calls += 1
                return "consolidated"
            backend.dream = _dream
        else:
            del backend.dream
        runner.memory_backend = backend
    else:
        runner.memory_backend = None
    legacy = MagicMock()
    if legacy_has_dream:
        async def _legacy_dream(**kw):
            runner.legacy_calls += 1
            return "legacy"
        legacy.dream = _legacy_dream
    else:
        del legacy.dream
    runner.memory_manager = legacy
    return runner


def _make_mgr(runner):
    from coapis.app.crons.manager import CronManager
    repo = MagicMock()
    cm = MagicMock()
    mgr = CronManager(
        repo=repo, runner=runner, channel_manager=cm,
        agent_id="a1", owner_user_id="alice",
    )
    return mgr


def _spy_factories(tmp):
    """Patch repository factories onto a temp sqlite DB (real repos)."""
    from coapis.foundation.db.base import BaseRow
    from coapis.foundation.db.engine import get_engine, init_engine

    (tmp / "system").mkdir(parents=True)
    init_engine(f"sqlite:///{tmp / 'system' / 'coapis.db'}")
    BaseRow.metadata.create_all(get_engine())
    from coapis.foundation import repository_factory
    return repository_factory.RepositoryFactory


def test_wiring():
    tmp = Path(tempfile.mkdtemp(prefix="dream_cb_test_"))
    rf = _spy_factories(tmp)

    # A. backend 优先
    runner = _make_runner(with_backend=True)
    mgr = _make_mgr(runner)
    with patch.object(rf, "get_memory_repository") as mr, \
         patch.object(rf, "get_memory_timeline_repository") as tr:
        tr.return_value.promotion_candidates.return_value = []
        asyncio.run(mgr._dream_callback())
        check("A1 backend.dream() 被调用", runner.backend_calls == 1,
              f"calls={runner.backend_calls}")
        check("A2 legacy memory_manager.dream() 未被调用",
              runner.legacy_calls == 0, f"calls={runner.legacy_calls}")
        check("B callback 自身未 record_outcome（防双行）",
              not mr.return_value.record_outcome.called,
              f"calls={mr.return_value.record_outcome.call_count}")

    # C. 无 backend 时回退 legacy
    runner2 = _make_runner(with_backend=False)
    mgr2 = _make_mgr(runner2)
    with patch.object(rf, "get_memory_repository") as mr2, \
         patch.object(rf, "get_memory_timeline_repository") as tr2:
        tr2.return_value.promotion_candidates.return_value = []
        asyncio.run(mgr2._dream_callback())
        check("C legacy memory_manager.dream() 被回退调用",
              runner2.legacy_calls == 1, f"calls={runner2.legacy_calls}")
        check("C2 回退路径同样不自记录 outcome",
              not mr2.return_value.record_outcome.called)

    # D. 两者都无 dream() → 优雅处理
    runner3 = _make_runner(with_backend=True, backend_has_dream=False,
                           legacy_has_dream=False)
    mgr3 = _make_mgr(runner3)
    with patch.object(rf, "get_memory_repository") as mr3, \
         patch.object(rf, "get_memory_timeline_repository") as tr3:
        tr3.return_value.promotion_candidates.return_value = []
        try:
            asyncio.run(mgr3._dream_callback())
            ok = True
        except Exception:  # noqa: BLE001
            ok = False
        check("D 无 dream() 时不抛异常", ok)


if __name__ == "__main__":
    test_wiring()
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    sys.exit(1 if failed else 0)
