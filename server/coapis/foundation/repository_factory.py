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
        - Community: JsonKnowledgeBaseRepository
        - Enterprise: PostgresKnowledgeBaseRepository (loaded dynamically)
    
    Usage:
        # Community edition (default)
        RepositoryFactory.initialize(
            edition="community",
            data_dir=Path("./data")
        )
        
        # Enterprise edition
        RepositoryFactory.initialize(
            edition="enterprise",
            database_url="postgresql://..."
        )
        
        # Get repository instance
        kb_repo = RepositoryFactory.get_kb_repository()
    """
    
    _kb_repo: Optional[KnowledgeBaseRepository] = None
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
                - Enterprise: database_url, session_pool, etc.
        
        Raises:
            ValueError: If invalid edition or missing required config
        """
        if cls._initialized:
            logger.warning("RepositoryFactory already initialized, re-initializing...")
        
        if edition == "community":
            data_dir = kwargs.get("data_dir", Path.cwd() / "data")
            cls._kb_repo = JsonKnowledgeBaseRepository(data_dir)
            logger.info(f"Initialized Community edition repositories (data_dir={data_dir})")
        
        elif edition == "enterprise":
            # Dynamically import enterprise implementation
            try:
                from coapis.enterprise.repository_postgres import PostgresKnowledgeBaseRepository
                
                session = kwargs.get("session")
                if not session:
                    raise ValueError("Enterprise edition requires 'session' parameter")
                
                cls._kb_repo = PostgresKnowledgeBaseRepository(session)
                logger.info("Initialized Enterprise edition repositories (PostgreSQL)")
            
            except ImportError as e:
                logger.error(f"Failed to import enterprise repositories: {e}")
                raise ValueError(
                    "Enterprise edition requires 'coapis.enterprise' package. "
                    "Install it with: pip install coapis-enterprise"
                )
        
        else:
            raise ValueError(f"Invalid edition: {edition}. Must be 'community' or 'enterprise'")
        
        cls._edition = edition
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
    def get_edition(cls) -> Optional[str]:
        """Get current edition.
        
        Returns:
            "community" or "enterprise", None if not initialized
        """
        return cls._edition
    
    @classmethod
    def is_initialized(cls) -> bool:
        """Check if factory is initialized.
        
        Returns:
            True if initialized, False otherwise
        """
        return cls._initialized
    
    @classmethod
    def reset(cls):
        """Reset factory (mainly for testing)."""
        cls._kb_repo = None
        cls._edition = None
        cls._initialized = False
