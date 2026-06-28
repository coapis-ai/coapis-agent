# -*- coding: utf-8 -*-
"""Base class for input guardians."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import InputGuardResult


class BaseInputGuardian(ABC):
    """Abstract base for input content guardians."""

    @abstractmethod
    def check(self, text: str) -> InputGuardResult:
        """Check input text and return a guard result."""
        ...
