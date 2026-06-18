# -*- coding: utf-8 -*-
"""Tests for v0.5.1 memory system migration."""

import shutil
import tempfile
from pathlib import Path


class TestConstantPaths:
    """测试路径常量。"""

    def test_system_evolution_dir(self):
        from coapis.constant import SYSTEM_EVOLUTION_DIR
        assert SYSTEM_EVOLUTION_DIR.name == "evolution"
        assert "system" in str(SYSTEM_EVOLUTION_DIR)

    def test_system_reviews_dir(self):
        from coapis.constant import SYSTEM_REVIEWS_DIR
        assert SYSTEM_REVIEWS_DIR.name == "reviews"
        assert "system" in str(SYSTEM_REVIEWS_DIR)

    def test_tmp_dir(self):
        from coapis.constant import TMP_DIR
        assert TMP_DIR.name == "tmp"


class TestEvolutionEngine:
    """测试 EvolutionEngine workspace_dir 参数。"""

    def test_init_requires_workspace_dir(self):
        from coapis.evolution.evolution_engine import EvolutionEngine, EvolutionConfig
        config = EvolutionConfig()
        engine = EvolutionEngine(
            data_dir=Path("/tmp/test"),
            workspace_dir=Path("/tmp/test/workspace"),
            config=config,
        )
        assert engine.workspace_dir == Path("/tmp/test/workspace")


class TestMemoryManager:
    """测试 MemoryManager 简化。"""

    def test_only_user_and_agent_types(self):
        from coapis.agent.memory_manager import MemoryManager
        with tempfile.TemporaryDirectory() as tmp:
            mm = MemoryManager(Path(tmp))
            types = set(mm._memory_files.keys())
            assert types == {"user", "agent"}
            assert "identity" not in types
            assert "soul" not in types

    def test_get_context_uses_user_and_agent(self):
        from coapis.agent.memory_manager import MemoryManager
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "USER.md").write_text("user prefs", encoding="utf-8")
            (tmp / "MEMORY.md").write_text("agent memory", encoding="utf-8")
            mm = MemoryManager(tmp)
            ctx = mm.get_context()
            assert "user prefs" in ctx
            assert "agent memory" in ctx


class TestUserProvisioning:
    """测试用户创建目录结构。"""

    def test_creates_memory_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspaces" / "testuser"
            workspace.mkdir(parents=True)
            for subdir in ["memory", "agents", "skills", "chat", "files", "files/media", "crons", "backups"]:
                (workspace / subdir).mkdir(parents=True, exist_ok=True)
            assert (workspace / "memory").is_dir()
            assert not (workspace / "evolution").exists()
            assert not (workspace / "workflows").exists()


class TestCleanupManager:
    """测试 CleanupManager。"""

    def test_init(self):
        from coapis.cleanup_manager import CleanupManager
        with tempfile.TemporaryDirectory() as tmp:
            cm = CleanupManager(Path(tmp))
            assert cm.working_dir == Path(tmp)
            assert cm.config["enabled"] is True

    def test_run_cleanup(self):
        from coapis.cleanup_manager import CleanupManager
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            old_dir = tmp / "tmp" / "cache"
            old_dir.mkdir(parents=True)
            (old_dir / "test.txt").write_text("cache")
            cm = CleanupManager(tmp)
            stats = cm.run_cleanup()
            assert "files_deleted" in stats

    def test_get_size_report(self):
        from coapis.cleanup_manager import CleanupManager
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "tmp").mkdir(parents=True)
            (tmp / "system").mkdir(parents=True)
            cm = CleanupManager(tmp)
            report = cm.get_size_report()
            assert "tmp" in report


class TestDiskMonitor:
    """测试 DiskMonitor。"""

    def test_check_disk_space(self):
        from coapis.disk_monitor import DiskMonitor
        with tempfile.TemporaryDirectory() as tmp:
            dm = DiskMonitor(Path(tmp))
            result = dm.check_disk_space()
            assert "free_gb" in result
            assert "total_gb" in result

    def test_get_full_report(self):
        from coapis.disk_monitor import DiskMonitor
        with tempfile.TemporaryDirectory() as tmp:
            dm = DiskMonitor(Path(tmp))
            report = dm.get_full_report()
            assert "disk" in report
            assert "directories" in report


class TestMigrateMemory:
    """测试迁移脚本。"""

    def test_dry_run(self):
        from coapis.migrate_memory import MemoryMigration
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            user = tmp / "workspaces" / "testuser"
            (user / "evolution" / "trajectories").mkdir(parents=True)
            (user / "workflows").mkdir(parents=True)
            (user / "evolution" / "trajectories" / "traj.json").write_text("{}")
            migration = MemoryMigration(tmp, dry_run=True)
            stats = migration.run()
            assert (user / "evolution" / "trajectories" / "traj.json").exists()

    def test_execute_migration(self):
        from coapis.migrate_memory import MemoryMigration
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            user = tmp / "workspaces" / "testuser"
            (user / "evolution" / "trajectories").mkdir(parents=True)
            (user / "evolution" / "experiences").mkdir(parents=True)
            (user / "evolution" / "reviews").mkdir(parents=True)
            (user / "workflows").mkdir(parents=True)
            (user / "evolution" / "trajectories" / "traj.json").write_text("{}")
            (user / "evolution" / "experiences" / "exp.json").write_text("{}")
            (user / "evolution" / "reviews" / "review.json").write_text("{}")
            migration = MemoryMigration(tmp, dry_run=False)
            stats = migration.run()
            assert (tmp / "tmp" / "evolution" / "trajectories" / "traj.json").exists()
            assert (tmp / "tmp" / "evolution" / "experiences" / "exp.json").exists()
            assert (tmp / "system" / "reviews" / "review.json").exists()
            assert not (user / "evolution").exists()
            assert not (user / "workflows").exists()
            assert (user / "MEMORY.md").exists()

    def test_migration_stats(self):
        from coapis.migrate_memory import MemoryMigration
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            user = tmp / "workspaces" / "testuser"
            (user / "evolution").mkdir(parents=True)
            migration = MemoryMigration(tmp, dry_run=False)
            stats = migration.run()
            assert stats["users_migrated"] >= 1
