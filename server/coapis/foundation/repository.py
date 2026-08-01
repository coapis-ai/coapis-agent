# -*- coding: utf-8 -*-
"""Repository abstraction layer for knowledge bases."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class KnowledgeBase:
    """Knowledge base entity - shared by Community and Enterprise editions.
    
    Community edition fields:
        - id, name, description, scope, status
        - created_at, updated_at
        - metadata (stored as JSON)
    
    Enterprise edition additional fields:
        - department_id: Department/team ownership
        - visibility: public/private/team
        - tenant_id: Multi-tenant isolation
        - created_by, updated_by: User tracking
    """
    
    # Core fields (Community + Enterprise)
    id: str
    name: str
    description: str = ""
    scope: str = "user"  # user, team, organization
    status: str = "active"  # active, archived, deleted
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    # Metadata (flexible, stored as JSON in Community)
    metadata: dict = field(default_factory=dict)
    
    # Enterprise-only fields (None in Community)
    department_id: Optional[str] = None
    visibility: Optional[str] = None  # public, private, team
    tenant_id: Optional[str] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "scope": self.scope,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": self.metadata,
            # Enterprise fields
            "department_id": self.department_id,
            "visibility": self.visibility,
            "tenant_id": self.tenant_id,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "KnowledgeBase":
        """Create from dictionary (JSON deserialization)."""
        # Parse datetime strings
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        elif not created_at:
            created_at = datetime.now()
        
        updated_at = data.get("updated_at")
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)
        elif not updated_at:
            updated_at = datetime.now()
        
        return cls(
            id=data["id"],
            name=data["name"],
            description=data.get("description", ""),
            scope=data.get("scope", "user"),
            status=data.get("status", "active"),
            created_at=created_at,
            updated_at=updated_at,
            metadata=data.get("metadata", {}),
            # Enterprise fields
            department_id=data.get("department_id"),
            visibility=data.get("visibility"),
            tenant_id=data.get("tenant_id"),
            created_by=data.get("created_by"),
            updated_by=data.get("updated_by"),
        )


class KnowledgeBaseRepository(ABC):
    """Abstract repository interface for knowledge bases.
    
    This interface defines the contract for knowledge base storage.
    Different implementations (JSON, PostgreSQL, etc.) must implement
    all methods.
    
    The abstraction allows:
        - Community edition: Use JSON file storage
        - Enterprise edition: Use PostgreSQL + Weaviate
        - Testing: Use in-memory mock storage
    """
    
    @abstractmethod
    async def create(self, kb: KnowledgeBase) -> KnowledgeBase:
        """Create a new knowledge base.
        
        Args:
            kb: KnowledgeBase entity to create
            
        Returns:
            Created KnowledgeBase with any auto-generated fields
            
        Raises:
            ValueError: If knowledge base with same ID already exists
        """
        pass
    
    @abstractmethod
    async def get_by_id(self, kb_id: str) -> Optional[KnowledgeBase]:
        """Get knowledge base by ID.
        
        Args:
            kb_id: Knowledge base ID
            
        Returns:
            KnowledgeBase if found, None otherwise
        """
        pass
    
    @abstractmethod
    async def list(
        self,
        scope: Optional[str] = None,
        status: Optional[str] = None,
        tenant_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[KnowledgeBase]:
        """List knowledge bases with optional filters.
        
        Args:
            scope: Filter by scope (user, team, organization)
            status: Filter by status (active, archived, deleted)
            tenant_id: Filter by tenant (Enterprise only)
            limit: Maximum number of results
            offset: Pagination offset
            
        Returns:
            List of KnowledgeBase entities
        """
        pass
    
    @abstractmethod
    async def update(self, kb: KnowledgeBase) -> KnowledgeBase:
        """Update an existing knowledge base.
        
        Args:
            kb: KnowledgeBase entity with updated fields
            
        Returns:
            Updated KnowledgeBase
            
        Raises:
            ValueError: If knowledge base not found
        """
        pass
    
    @abstractmethod
    async def delete(self, kb_id: str) -> bool:
        """Delete a knowledge base.
        
        Args:
            kb_id: Knowledge base ID
            
        Returns:
            True if deleted, False if not found
        """
        pass
    
    @abstractmethod
    async def count(
        self,
        scope: Optional[str] = None,
        status: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> int:
        """Count knowledge bases with optional filters.
        
        Args:
            scope: Filter by scope
            status: Filter by status
            tenant_id: Filter by tenant (Enterprise only)
            
        Returns:
            Number of matching knowledge bases
        """
        pass
