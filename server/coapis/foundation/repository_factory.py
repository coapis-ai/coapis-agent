# -*- coding: utf-8 -*-
"""Repository factory for dependency injection.

纯注入点（社区版为唯一内置实现）：

- ``community``：内置 SQLite 实现（SQLAlchemy 全局 engine），
  初始化时自动完成 JSON → DB 迁移（幂等）。
- ``enterprise``：由上层 edition 插件在启动时通过
  ``inject_*_repository()`` 注入 PostgreSQL 实现；工厂自身
  **不 import 任何上层 edition 包**（禁止 coapis.enterprise.* 反向依赖）。
"""

import logging
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class RepositoryFactory:
    """Factory for creating repository instances (edition-aware injection).

    Usage:
        # Community edition (default)
        RepositoryFactory.initialize(
            edition="community",
            data_dir=Path("./data"),
        )

        # Enterprise edition: repositories are injected by the edition plugin
        RepositoryFactory.initialize(edition="enterprise")
        RepositoryFactory.inject_user_repository(postgres_user_repo)

        # Get repository instance
        user_repo = RepositoryFactory.get_user_repository()
    """

    _user_repo = None  # User repository (SQLite community / Postgres enterprise)
    _lock: threading.Lock = threading.Lock()
    _tag_repo = None   # Tag repository (community: SQLite / enterprise: injected)
    _scene_repo = None # Scene repository (community: SQLite / enterprise: injected)
    _user_scene_repo = None  # User scene settings repo (community / enterprise: injected)
    _ext_store = None  # External identity store (community: SQLAlchemy / enterprise: injected)
    _edition: Optional[str] = None
    _initialized: bool = False

    # ── lifecycle ──

    @classmethod
    def initialize(cls, edition: str = "community", **kwargs) -> None:
        """Initialize repository based on edition.

        Args:
            edition: "community" or "enterprise"
            **kwargs: Edition-specific configuration
                - Community: data_dir (Path, reserved)

        Raises:
            ValueError: If invalid edition
        """
        if cls._initialized:
            logger.warning("RepositoryFactory already initialized, re-initializing...")

        cls._edition = edition

        if edition == "community":
            cls._initialize_community()
        elif edition == "enterprise":
            cls._initialize_enterprise(kwargs)
        else:
            raise ValueError(f"Invalid edition: {edition}. Must be 'community' or 'enterprise'")

        cls._initialized = True

    @classmethod
    def _initialize_community(cls) -> None:
        """Community edition: built-in SQLite repositories (SQLAlchemy engine).

        初始化失败直接报错，不回退（D-8：社区版 = SQLite only）。
        """
        from ..constant import SYSTEM_DIR, WORKING_DIR
        from .db_settings import resolve_db_path
        from .migrations import (
            ensure_domain_migrated,
            ensure_migrated,
            ensure_runtime_domain_migrated,
        )
        from .user_repository_impl import SqlaUserRepository

        # D-7/D-8/D-9：COAPIS_DATABASE_URL（可选；默认 <WORKING_DIR>/system/coapis.db，
        # 相对路径相对 WORKING_DIR 解析，必须落在挂载卷内）
        db_path = resolve_db_path()

        # T2 单一事实来源（结构）= Alembic / ORM metadata：先建齐全部表 +
        # stamp head，再跑下面的数据迁移。旧库缺的 B-tier 表由同一份
        # Base.metadata 补齐；存量表整体跳过（幂等）。
        from .db.migrate import run_migrations

        try:
            run_migrations()
        except Exception as e:
            logger.error(f"Migration failed (non-fatal): {e}")

        # 首启迁移：users.json → coapis.db（幂等，已迁移则跳过）——纯 INSERT，表结构已由上面保证。
        ensure_migrated(system_dir=SYSTEM_DIR, db_path=db_path)
        # F3: external identity bindings (SSO) → same coapis.db.
        from .external_identity_impl import SqlaExternalIdentityStore
        cls._ext_store = SqlaExternalIdentityStore()
        # M1 四域落库：域迁移（tags/scenes/user_scene_settings 建表 + JSON 播种，幂等）。
        ensure_domain_migrated(data_dir=WORKING_DIR, system_dir=SYSTEM_DIR, db_path=db_path)
        # B 档：运行时域 JSON → DB（token_usage 日聚合/明细、权限配置）。
        # B 档迁移函数基于 SQLAlchemy text() + :name 命名参数，必须走全局
        # engine（裸 sqlite3 连接无法解析 text() 对象，会静默迁移 0 行）。
        from .db.engine import get_engine
        with get_engine().begin() as engine_conn:
            ensure_runtime_domain_migrated(engine_conn, SYSTEM_DIR)

        cls._user_repo = SqlaUserRepository()
        from .tag_repository_sqlite import SqliteTagRepository
        from .scene_repository_sqlite import SqliteSceneRepository
        from .user_scene_repository_sqlite import SqliteUserSceneSettingsRepo
        cls._tag_repo = SqliteTagRepository(db_path)
        cls._scene_repo = SqliteSceneRepository(db_path)
        cls._user_scene_repo = SqliteUserSceneSettingsRepo(db_path)
        logger.info("Initialized Community repositories (SQLAlchemy at %s)", db_path)

    @classmethod
    def _initialize_enterprise(cls, kwargs: dict) -> None:
        """Enterprise edition: repositories must be injected by the edition plugin.

        The factory never imports coapis.enterprise.* — the plugin calls
        ``inject_user_repository()`` / ``inject_tag_repository()`` / ...
        after ``initialize()`` returns.
        """
        user_repo = kwargs.get("user_repository")
        if user_repo is not None:
            cls._user_repo = user_repo
            logger.info("Enterprise User repository injected at initialize()")
        else:
            logger.warning(
                "Enterprise edition initialized without user_repository; "
                "the edition plugin must call inject_user_repository() at startup."
            )

    # ── getters ──

    @classmethod
    def _require_initialized(cls) -> None:
        """Guard: getters require initialize() to have run first."""
        if not cls._initialized:
            raise RuntimeError(
                "RepositoryFactory not initialized. "
                "Call RepositoryFactory.initialize(edition=...) first."
            )

    @classmethod
    def get_user_repository(cls):
        """Get user repository instance (SQLAlchemy community / Postgres enterprise)."""
        cls._require_initialized()
        if cls._user_repo is None:
            raise RuntimeError(
                "User repository not available. "
                "Ensure RepositoryFactory.initialize() was called with a user repository."
            )
        return cls._user_repo

    @classmethod
    def get_tag_repository(cls):
        """Get tag repository instance."""
        cls._require_initialized()
        if cls._tag_repo is None:
            raise RuntimeError(
                "Tag repository not available. "
                "Ensure RepositoryFactory was configured with tag_repository."
            )
        return cls._tag_repo

    @classmethod
    def get_scene_repository(cls):
        """Get scene repository instance."""
        cls._require_initialized()
        if cls._scene_repo is None:
            raise RuntimeError(
                "Scene repository not available. "
                "Ensure RepositoryFactory was configured with scene_repository."
            )
        return cls._scene_repo

    @classmethod
    def get_user_scene_repository(cls):
        """Get user scene settings repository instance."""
        cls._require_initialized()
        if cls._user_scene_repo is None:
            raise RuntimeError(
                "User scene repository not available. "
                "Ensure RepositoryFactory was configured with user_scene_repository."
            )
        return cls._user_scene_repo

    @classmethod
    def get_external_identity_store(cls):
        """Get external identity store instance (None if not initialized)."""
        return cls._ext_store

    @classmethod
    def get_edition(cls) -> Optional[str]:
        """Get current edition ("community" / "enterprise" / None)."""
        return cls._edition

    @classmethod
    def is_initialized(cls) -> bool:
        """Check if factory is initialized."""
        return cls._initialized

    # ── injection (enterprise plugin API) ──

    @classmethod
    def inject_user_repository(cls, repo) -> None:
        """Inject user repository instance (enterprise plugin)."""
        cls._user_repo = repo
        logger.info("User repository injected into RepositoryFactory")

    @classmethod
    def inject_tag_repository(cls, tag_repo) -> None:
        """Inject tag repository instance (enterprise plugin)."""
        cls._tag_repo = tag_repo
        logger.info("Tag repository injected into RepositoryFactory")

    @classmethod
    def inject_scene_repository(cls, scene_repo) -> None:
        """Inject scene repository instance (enterprise plugin)."""
        cls._scene_repo = scene_repo
        logger.info("Scene repository injected into RepositoryFactory")

    @classmethod
    def inject_user_scene_repository(cls, repo) -> None:
        """Inject user scene settings repository instance (enterprise plugin)."""
        cls._user_scene_repo = repo
        logger.info("User scene repository injected into RepositoryFactory")

    @classmethod
    def inject_external_identity_store(cls, store) -> None:
        """Inject external identity store instance (enterprise plugin)."""
        cls._ext_store = store
        logger.info("External identity store injected into RepositoryFactory")

    # ── testing helpers ──

    @classmethod
    def reset_user_repo(cls) -> None:
        """Close and reset the user repository (for testing / re-init)."""
        with cls._lock:
            if cls._user_repo is not None and hasattr(cls._user_repo, "close"):
                try:
                    cls._user_repo.close()
                except Exception:
                    pass
            cls._user_repo = None

    @classmethod
    def reset(cls) -> None:
        """Reset factory state (used by tests)."""
        for attr in ("_user_repo", "_scene_repo", "_tag_repo",
                     "_user_scene_repo", "_ext_store"):
            repo = getattr(cls, attr, None)
            if repo is not None and hasattr(repo, "close"):
                try:
                    repo.close()
                except Exception:  # noqa: BLE001
                    pass
            setattr(cls, attr, None)
        cls._edition = None
        cls._initialized = False
