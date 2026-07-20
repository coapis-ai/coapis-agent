# -*- coding: utf-8 -*-
"""Foundation layer - abstractions for storage and services."""

from .repository import KnowledgeBaseRepository, KnowledgeBase
from .repository_factory import RepositoryFactory
from .foundation_manager import FoundationManager
from .memory_entry import MemoryEntry

__all__ = [
    "KnowledgeBaseRepository",
    "KnowledgeBase",
    "RepositoryFactory",
    "FoundationManager",
    "MemoryEntry",
]
