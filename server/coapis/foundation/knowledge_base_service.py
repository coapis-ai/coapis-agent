# -*- coding: utf-8 -*-
"""Knowledge base service - business logic layer."""

import logging
import uuid
from datetime import datetime
from typing import List, Optional

from .repository import KnowledgeBase
from .repository_factory import RepositoryFactory

logger = logging.getLogger(__name__)


class KnowledgeBaseService:
    """Knowledge base service - edition-agnostic business logic.
    
    This service provides high-level operations for knowledge bases,
    abstracting away the storage implementation. It works with both
    Community (JSON) and Enterprise (PostgreSQL) editions.
    
    Features:
        - CRUD operations
        - Scope management (user, team, organization)
        - Status management (active, archived, deleted)
        - Enterprise: Multi-tenant isolation, permissions
    """
    
    def __init__(self):
        """Initialize service with repository from factory."""
        self._kb_repo = None
    
    @property
    def kb_repo(self):
        """Lazy-load repository (allows initialization after service creation)."""
        if self._kb_repo is None:
            self._kb_repo = RepositoryFactory.get_kb_repository()
        return self._kb_repo
    
    async def create_knowledge_base(
        self,
        name: str,
        description: str = "",
        scope: str = "user",
        metadata: Optional[dict] = None,
        # Enterprise fields
        department_id: Optional[str] = None,
        visibility: Optional[str] = None,
        tenant_id: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> KnowledgeBase:
        """Create a new knowledge base.
        
        Args:
            name: Knowledge base name
            description: Description
            scope: Scope (user, team, organization)
            metadata: Custom metadata
            department_id: Department ID (Enterprise)
            visibility: Visibility (Enterprise)
            tenant_id: Tenant ID (Enterprise)
            created_by: Creator user ID (Enterprise)
            
        Returns:
            Created KnowledgeBase entity
        """
        kb = KnowledgeBase(
            id=str(uuid.uuid4()),
            name=name,
            description=description,
            scope=scope,
            status="active",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            metadata=metadata or {},
            # Enterprise fields
            department_id=department_id,
            visibility=visibility,
            tenant_id=tenant_id,
            created_by=created_by,
            updated_by=created_by,
        )
        
        created_kb = await self.kb_repo.create(kb)
        logger.info(f"Created knowledge base '{created_kb.id}' ({name})")
        return created_kb
    
    async def get_knowledge_base(self, kb_id: str) -> Optional[KnowledgeBase]:
        """Get knowledge base by ID.
        
        Args:
            kb_id: Knowledge base ID
            
        Returns:
            KnowledgeBase if found, None otherwise
        """
        return await self.kb_repo.get_by_id(kb_id)
    
    async def list_knowledge_bases(
        self,
        scope: Optional[str] = None,
        status: Optional[str] = "active",
        tenant_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[KnowledgeBase]:
        """List knowledge bases with filters.
        
        Args:
            scope: Filter by scope
            status: Filter by status (default: active)
            tenant_id: Filter by tenant (Enterprise)
            limit: Max results
            offset: Pagination offset
            
        Returns:
            List of KnowledgeBase entities
        """
        return await self.kb_repo.list(
            scope=scope,
            status=status,
            tenant_id=tenant_id,
            limit=limit,
            offset=offset,
        )
    
    async def update_knowledge_base(
        self,
        kb_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        scope: Optional[str] = None,
        status: Optional[str] = None,
        metadata: Optional[dict] = None,
        # Enterprise fields
        department_id: Optional[str] = None,
        visibility: Optional[str] = None,
        updated_by: Optional[str] = None,
    ) -> KnowledgeBase:
        """Update an existing knowledge base.
        
        Args:
            kb_id: Knowledge base ID
            name: New name
            description: New description
            scope: New scope
            status: New status
            metadata: New metadata (merged with existing)
            department_id: New department ID (Enterprise)
            visibility: New visibility (Enterprise)
            updated_by: Updater user ID (Enterprise)
            
        Returns:
            Updated KnowledgeBase entity
            
        Raises:
            ValueError: If knowledge base not found
        """
        kb = await self.kb_repo.get_by_id(kb_id)
        if not kb:
            raise ValueError(f"Knowledge base '{kb_id}' not found")
        
        # Update fields
        if name is not None:
            kb.name = name
        if description is not None:
            kb.description = description
        if scope is not None:
            kb.scope = scope
        if status is not None:
            kb.status = status
        if metadata is not None:
            kb.metadata.update(metadata)
        
        # Enterprise fields
        if department_id is not None:
            kb.department_id = department_id
        if visibility is not None:
            kb.visibility = visibility
        if updated_by is not None:
            kb.updated_by = updated_by
        
        kb.updated_at = datetime.now()
        
        updated_kb = await self.kb_repo.update(kb)
        logger.info(f"Updated knowledge base '{kb_id}'")
        return updated_kb
    
    async def delete_knowledge_base(self, kb_id: str) -> bool:
        """Delete a knowledge base.
        
        Args:
            kb_id: Knowledge base ID
            
        Returns:
            True if deleted, False if not found
        """
        deleted = await self.kb_repo.delete(kb_id)
        if deleted:
            logger.info(f"Deleted knowledge base '{kb_id}'")
        return deleted
    
    async def archive_knowledge_base(self, kb_id: str) -> KnowledgeBase:
        """Archive a knowledge base (soft delete).
        
        Args:
            kb_id: Knowledge base ID
            
        Returns:
            Archived KnowledgeBase entity
        """
        return await self.update_knowledge_base(kb_id, status="archived")
    
    async def count_knowledge_bases(
        self,
        scope: Optional[str] = None,
        status: Optional[str] = "active",
        tenant_id: Optional[str] = None,
    ) -> int:
        """Count knowledge bases with filters.
        
        Args:
            scope: Filter by scope
            status: Filter by status
            tenant_id: Filter by tenant (Enterprise)
            
        Returns:
            Number of matching knowledge bases
        """
        return await self.kb_repo.count(
            scope=scope,
            status=status,
            tenant_id=tenant_id,
        )
