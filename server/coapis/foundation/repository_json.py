# -*- coding: utf-8 -*-
"""JSON file-based repository implementation for Community edition."""

import json
import logging
from pathlib import Path
from typing import List, Optional

from .repository import KnowledgeBase, KnowledgeBaseRepository

logger = logging.getLogger(__name__)


class JsonKnowledgeBaseRepository(KnowledgeBaseRepository):
    """JSON file storage implementation - Community edition.
    
    Storage structure:
        data/knowledge_bases.json:
        {
            "knowledge_bases": [
                {"id": "kb-1", "name": "My KB", ...},
                {"id": "kb-2", "name": "Team KB", ...},
            ]
        }
    
    Features:
        - Simple file-based storage
        - No database dependencies
        - Suitable for single-user or small teams
        - Not suitable for multi-tenant or large-scale deployments
    """
    
    def __init__(self, data_dir: Path):
        """Initialize JSON repository.
        
        Args:
            data_dir: Directory to store JSON files
        """
        self.data_dir = Path(data_dir)
        self.kb_file = self.data_dir / "knowledge_bases.json"
        self._ensure_data_dir()
        logger.info(f"Initialized JsonKnowledgeBaseRepository (data_dir={self.data_dir})")
    
    def _ensure_data_dir(self):
        """Ensure data directory and files exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        if not self.kb_file.exists():
            self._write_data({"knowledge_bases": []})
    
    def _read_data(self) -> dict:
        """Read data from JSON file.
        
        Returns:
            Dictionary with knowledge_bases list
        """
        try:
            with open(self.kb_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read {self.kb_file}: {e}")
            return {"knowledge_bases": []}
    
    def _write_data(self, data: dict):
        """Write data to JSON file.
        
        Args:
            data: Dictionary with knowledge_bases list
        """
        with open(self.kb_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    async def create(self, kb: KnowledgeBase) -> KnowledgeBase:
        """Create a new knowledge base."""
        data = self._read_data()
        
        # Check for duplicate ID
        existing_ids = [k["id"] for k in data["knowledge_bases"]]
        if kb.id in existing_ids:
            raise ValueError(f"Knowledge base with ID '{kb.id}' already exists")
        
        # Add new KB
        data["knowledge_bases"].append(kb.to_dict())
        self._write_data(data)
        
        logger.info(f"Created knowledge base '{kb.id}' ({kb.name})")
        return kb
    
    async def get_by_id(self, kb_id: str) -> Optional[KnowledgeBase]:
        """Get knowledge base by ID."""
        data = self._read_data()
        
        for kb_dict in data["knowledge_bases"]:
            if kb_dict["id"] == kb_id:
                return KnowledgeBase.from_dict(kb_dict)
        
        return None
    
    async def list(
        self,
        scope: Optional[str] = None,
        status: Optional[str] = None,
        tenant_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[KnowledgeBase]:
        """List knowledge bases with filters."""
        data = self._read_data()
        
        results = []
        for kb_dict in data["knowledge_bases"]:
            kb = KnowledgeBase.from_dict(kb_dict)
            
            # Apply filters
            if scope and kb.scope != scope:
                continue
            if status and kb.status != status:
                continue
            # Note: tenant_id is ignored in Community edition
            
            results.append(kb)
        
        # Apply pagination
        return results[offset : offset + limit]
    
    async def update(self, kb: KnowledgeBase) -> KnowledgeBase:
        """Update an existing knowledge base."""
        data = self._read_data()
        
        # Find and update
        found = False
        for i, kb_dict in enumerate(data["knowledge_bases"]):
            if kb_dict["id"] == kb.id:
                data["knowledge_bases"][i] = kb.to_dict()
                found = True
                break
        
        if not found:
            raise ValueError(f"Knowledge base '{kb.id}' not found")
        
        self._write_data(data)
        logger.info(f"Updated knowledge base '{kb.id}'")
        return kb
    
    async def delete(self, kb_id: str) -> bool:
        """Delete a knowledge base."""
        data = self._read_data()
        
        initial_count = len(data["knowledge_bases"])
        data["knowledge_bases"] = [
            kb for kb in data["knowledge_bases"] if kb["id"] != kb_id
        ]
        
        if len(data["knowledge_bases"]) < initial_count:
            self._write_data(data)
            logger.info(f"Deleted knowledge base '{kb_id}'")
            return True
        
        return False
    
    async def count(
        self,
        scope: Optional[str] = None,
        status: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> int:
        """Count knowledge bases."""
        data = self._read_data()
        
        count = 0
        for kb_dict in data["knowledge_bases"]:
            kb = KnowledgeBase.from_dict(kb_dict)
            
            # Apply filters
            if scope and kb.scope != scope:
                continue
            if status and kb.status != status:
                continue
            # Note: tenant_id is ignored in Community edition
            
            count += 1
        
        return count
