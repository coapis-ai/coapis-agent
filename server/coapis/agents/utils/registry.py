# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Generic registry for registering and retrieving implementations."""

from typing import Callable, Generic, Type, TypeVar

T = TypeVar("T")


class Registry(Generic[T]):
    """Generic registry for registering and retrieving implementations.

    Example:
        from coapis.agents.context.base_context_manager import (
            context_registry,
        )

        @context_registry.register("light")
        class LightContextManager(BaseContextManager):
            ...

        cls = context_registry.get("light")
        instance = cls(working_dir=..., agent_id=...)
    """

    def __init__(self) -> None:
        self._registry: dict[str, Type[T]] = {}

    def register(self, name: str) -> Callable[[Type[T]], Type[T]]:
        """Decorator to register an implementation."""

        def decorator(impl_class: Type[T]) -> Type[T]:
            self._registry[name.lower()] = impl_class
            return impl_class

        return decorator

    def get(self, name: str) -> Type[T] | None:
        """Get registered implementation class by name."""
        return self._registry.get(name.lower())

    def list_registered(self) -> list[str]:
        """List all registered implementation names."""
        return list(self._registry.keys())

    def has(self, name: str) -> bool:
        """Check if an implementation is registered."""
        return name.lower() in self._registry
