# -*- coding: utf-8 -*-
"""Repository factory for dependency injection."""

import logging
from pathlib import Path
from typing import Optional

from .repository import KnowledgeBaseRepository
from .repository_json import JsonKnowledgeBaseRepository

logger = logging.getLogger(__name__)


class RepositoryFactory:
    """Factory for creating repository instances.
    
    This factory provides dependency injection for repositories,
    allowing different implementations based on edition:
        - Community: JsonKnowledgeBaseRepository, JsonUserRepository
        - Enterprise: PostgresKnowledgeBaseRepository, PostgresUserRepository (loaded dynamically)
    
    Usage:
        # Community edition (default)
        RepositoryFactory.initialize(
            edition="community",
            data_dir=Path("./data")
        )
        
        # Enterprise edition
        RepositoryFactory.initialize(
            edition="enterprise",
            session=db_session,
            user_repository=postgres_user_repo  # 注入企业版Repository
        )
        
        # Get repository instance
        kb_repo = RepositoryFactory.get_kb_repository()
        user_repo = RepositoryFactory.get_user_repository()
    """
    
    _kb_repo: Optional[KnowledgeBaseRepository] = None
    _user_repo = None  # User repository (injected by enterprise)
    _tag_repo = None   # Tag repository (injected by enterprise)
    _scene_repo = None # Scene repository (injected by enterprise)
    _edition: Optional[str] = None
    _initialized: bool = False
    
    @classmethod
    def initialize(
        cls,
        edition: str = "community",
        **kwargs,
    ):
        """Initialize repository based on edition.
        
        Args:
            edition: "community" or "enterprise"
            **kwargs: Edition-specific configuration
                - Community: data_dir (Path)
                - Enterprise: session, user_repository (injected)
        
        Raises:
            ValueError: If invalid edition or missing required config
        """
        if cls._initialized:
            logger.warning("RepositoryFactory already initialized, re-initializing...")
        
        cls._edition = edition
        
        if edition == "community":
            data_dir = kwargs.get("data_dir", Path.cwd() / "data")
            cls._kb_repo = JsonKnowledgeBaseRepository(data_dir)
            logger.info(f"Initialized Community edition repositories (data_dir={data_dir})")
            
            # 社区版：使用JSON User Repository
            try:
                from .user_repository_json import JsonUserRepository
                cls._user_repo = JsonUserRepository()
                logger.info("Initialized Community User repository (JSON)")
            except Exception as e:
                logger.warning(f"Failed to initialize JsonUserRepository: {e}")
        
        elif edition == "enterprise":
            # 企业版：注入Repository（由企业版plugin提供）
            
            # 1. KnowledgeBase Repository（可选）
            session = kwargs.get("session")
            kb_repo = kwargs.get("kb_repository")
            
            if kb_repo:
                cls._kb_repo = kb_repo
                logger.info("Enterprise KB repository injected")
            elif session:
                try:
                    from coapis.enterprise.repository_postgres import PostgresKnowledgeBaseRepository
                    cls._kb_repo = PostgresKnowledgeBaseRepository(session)
                    logger.info("Enterprise KB repository initialized (PostgreSQL)")
                except ImportError:
                    logger.info("Enterprise KB repository not available, using JSON")
                    data_dir = kwargs.get("data_dir", Path.cwd() / "data")
                    cls._kb_repo = JsonKnowledgeBaseRepository(data_dir)
            else:
                # 默认使用JSON
                data_dir = kwargs.get("data_dir", Path.cwd() / "data")
                cls._kb_repo = JsonKnowledgeBaseRepository(data_dir)
                logger.info("Using JSON KB repository (default)")
            
            # 2. User Repository（企业版注入）
            user_repo = kwargs.get("user_repository")
            session = kwargs.get("session")
            
            if user_repo:
                cls._user_repo = user_repo
                logger.info("✅ Enterprise User repository injected")
            elif session:
                # 尝试从数据库创建 PostgresUserRepository
                try:
                    from coapis.enterprise.repository_postgres import PostgresUserRepository
                    cls._user_repo = PostgresUserRepository(session)
                    logger.info("Enterprise User repository initialized (PostgreSQL)")
                except ImportError:
                    try:
                        from coapis.database.repositories.user_repository import PostgresUserRepository
                        cls._user_repo = PostgresUserRepository(session)
                        logger.info("Enterprise User repository initialized (PostgreSQL)")
                    except Exception as e:
                        logger.warning(f"Failed to initialize PostgresUserRepository: {e}")
            else:
                # 没有 session 也没有 user_repository，使用 JSON fallback
                logger.info("Enterprise User repository not injected, using JSON")
                try:
                    from .user_repository_json import JsonUserRepository
                    cls._user_repo = JsonUserRepository()
                except Exception as e:
                    logger.warning(f"Failed to initialize JsonUserRepository: {e}")
        
        else:
            raise ValueError(f"Invalid edition: {edition}. Must be 'community' or 'enterprise'")
        
        cls._initialized = True
    
    @classmethod
    def get_kb_repository(cls) -> KnowledgeBaseRepository:
        """Get knowledge base repository instance.
        
        Returns:
            KnowledgeBaseRepository implementation
            
        Raises:
            RuntimeError: If factory not initialized
        """
        if not cls._initialized:
            raise RuntimeError(
                "RepositoryFactory not initialized. "
                "Call RepositoryFactory.initialize() first."
            )
        
        return cls._kb_repo
    
    @classmethod
    def get_user_repository(cls):
        """Get user repository instance.
        
        Returns:
            UserRepository implementation (JSON or PostgreSQL)
            
        Raises:
            RuntimeError: If factory not initialized
        """
        if not cls._initialized:
            raise RuntimeError(
                "RepositoryFactory not initialized. "
                "Call RepositoryFactory.initialize() first."
            )
        
        if cls._user_repo is None:
            raise RuntimeError(
                "User repository not available. "
                "Ensure RepositoryFactory.initialize() was called with user_repository."
            )
        
        return cls._user_repo
    
    @classmethod
    def inject_tag_repository(cls, tag_repo):
        """Inject tag repository instance."""
        cls._tag_repo = tag_repo
        logger.info("✅ Tag repository injected into RepositoryFactory")

    @classmethod
    def get_tag_repository(cls):
        """Get tag repository instance.
        
        Returns:
            TagRepository implementation (PostgreSQL in enterprise)
            
        Raises:
            RuntimeError: If factory not initialized or tag repo not available
        """
        if not cls._initialized:
            raise RuntimeError(
                "RepositoryFactory not initialized. "
                "Call RepositoryFactory.initialize() first."
            )
        
        if cls._tag_repo is None:
            raise RuntimeError(
                "Tag repository not available. "
                "Ensure RepositoryFactory was configured with tag_repository."
            )
        
        return cls._tag_repo

    @classmethod
    def inject_scene_repository(cls, scene_repo):
        """Inject scene repository instance."""
        cls._scene_repo = scene_repo
        logger.info("✅ Scene repository injected into RepositoryFactory")

    @classmethod
    def get_scene_repository(cls):
        """Get scene repository instance.
        
        Returns:
            SceneRepository implementation (PostgreSQL in enterprise)
            
        Raises:
            RuntimeError: If factory not initialized or scene repo not available
        """
        if not cls._initialized:
            raise RuntimeError(
                "RepositoryFactory not initialized. "
                "Call RepositoryFactory.initialize() first."
            )
        
        if cls._scene_repo is None:
            raise RuntimeError(
                "Scene repository not available. "
                "Ensure RepositoryFactory was configured with scene_repository."
            )
        
        return cls._scene_repo

    @classmethod
    def get_edition(cls) -> Optional[str]:
        """Get current edition.
        
        Returns:
            "community" or "enterprise" or None if not initialized
        """
        return cls._edition
    
    @classmethod
    def is_initialized(cls) -> bool:
        """Check if factory is initialized.
        
        Returns:
            True if initialized, False otherwise
        """
        return cls._initialized
