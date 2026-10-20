"""单调度器选举锁测试（G3「三重执行」根因修复）。

同一份任务库被多个进程加载时，只允许一个进程注册调度任务，其余进程
只提供接口不注册 job —— 从根上杜绝同一任务被重复触发。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from coapis.app.crons.manager import CronManager
from coapis.app.crons.repo.json_repo import JsonJobRepository


def _jobs_payload(job_id: str = "job-1") -> dict:
    return {
        "jobs": [
            {
                "id": job_id,
                "name": "daily-report",
                "enabled": True,
                "task_type": "text",
                "text": "生成日报",
                "schedule": {"type": "cron", "cron": "0 9 * * *", "timezone": "UTC"},
                "dispatch": {
                    "type": "channel",
                    "target": {"user_id": "u1", "session_id": "s1"},
                },
            }
        ]
    }


def _make_repo(path: Path) -> JsonJobRepository:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jobs_payload()), encoding="utf-8")
    return JsonJobRepository(path)


def _manager(repo: JsonJobRepository) -> CronManager:
    return CronManager(
        repo=repo,
        runner=None,
        channel_manager=None,
        timezone="UTC",
    )


@pytest.mark.asyncio
async def test_second_manager_does_not_register_jobs(tmp_path: Path) -> None:
    """同一任务库：第二个进程抢不到锁，不得注册任何 job。"""
    jobs_path = tmp_path / "crons" / "jobs.json"

    manager_a = _manager(_make_repo(jobs_path))
    await manager_a.start()
    assert manager_a._scheduler.get_jobs(), "首个进程应把任务注册进调度器"

    manager_b = _manager(_make_repo(jobs_path))
    await manager_b.start()

    assert not manager_b._scheduler.get_jobs(), (
        "第二个进程抢锁失败后不得向调度器注册任务，否则同一任务会被重复触发"
    )
    # 接口照常可用：任务数据仍能从仓储读出
    assert await manager_b.list_jobs(), "抢锁失败的进程仍需提供任务查询接口"
    assert manager_b._started is True, "接口仍应可用"

    await manager_a.stop()
    await manager_b.stop()


@pytest.mark.asyncio
async def test_lock_released_after_shutdown(tmp_path: Path) -> None:
    """前一个进程退出后，新进程必须能重新拿到调度权。"""
    jobs_path = tmp_path / "crons" / "jobs.json"

    manager_a = _manager(_make_repo(jobs_path))
    await manager_a.start()
    await manager_a.stop()

    manager_b = _manager(_make_repo(jobs_path))
    await manager_b.start()
    assert await manager_b.list_jobs(), "锁释放后新进程应能接管调度"

    await manager_b.stop()


@pytest.mark.asyncio
async def test_lock_file_lives_next_to_jobs(tmp_path: Path) -> None:
    """锁文件与 jobs.json 同目录，随任务库迁移自动跟随。"""
    jobs_path = tmp_path / "crons" / "jobs.json"
    repo = _make_repo(jobs_path)
    assert repo.scheduler_lock_path() == jobs_path.parent / "scheduler.lock"

    manager = _manager(repo)
    await manager.start()
    assert repo.scheduler_lock_path().exists()
    await manager.stop()


@pytest.mark.asyncio
async def test_repository_without_lock_semantics_is_not_blocked(tmp_path: Path) -> None:
    """不参与选举的仓储（锁路径为 None）必须照常注册任务。"""
    jobs_path = tmp_path / "crons" / "jobs.json"
    repo = _make_repo(jobs_path)

    repo.scheduler_lock_path = lambda: None  # type: ignore[method-assign]

    manager = _manager(repo)
    await manager.start()
    assert await manager.list_jobs(), "无锁语义的仓储不应被阻塞"
    await manager.stop()
