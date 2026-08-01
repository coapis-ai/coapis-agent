"""
CoApis Runtime Hook System (ported from QwenPaw).

Provides a topological, phase-aware hook framework with three states:
    CONTINUE        — proceed to next hook
    SHORT_CIRCUIT   — skip remaining hooks of this phase and continue to next phase
    SKIP_AGENT      — skip the entire agent execution (e.g. cached, blocked)

Phases (topological order):
    PRE_DISPATCH, POST_DISPATCH,
    PRE_BUILD, POST_BUILD,
    PRE_EXECUTE, POST_EXECUTE,
    PRE_POST_PROCESS, POST_POST_PROCESS

Builtin rules:
    - Builtin hooks run first (ordered by phase index).
    - User-defined hooks run after builtin hooks of the same phase.
    - Global failure of any hook short-circuits to the agent error path.

Example:

    >>> hooks = HookManager()
    >>> hooks.register(MyAuditHook())
    >>> await hooks.run(PRE_DISPATCH, ctx)  # ctx: HookContext
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Tuple


class HookState(str, Enum):
    """Control flow states carried by each hook invocation."""

    CONTINUE = "CONTINUE"
    SHORT_CIRCUIT = "SHORT_CIRCUIT"
    SKIP_AGENT = "SKIP_AGENT"


class HookPhase(str, Enum):
    """Topological phases of agent dispatch/build/execute/post-process lifecycle."""

    PRE_DISPATCH = "PRE_DISPATCH"
    POST_DISPATCH = "POST_DISPATCH"
    PRE_BUILD = "PRE_BUILD"
    POST_BUILD = "POST_BUILD"
    PRE_EXECUTE = "PRE_EXECUTE"
    POST_EXECUTE = "POST_EXECUTE"
    PRE_POST_PROCESS = "PRE_POST_PROCESS"
    POST_POST_PROCESS = "POST_POST_PROCESS"


PHASE_ORDER: Tuple[HookPhase, ...] = (
    HookPhase.PRE_DISPATCH,
    HookPhase.POST_DISPATCH,
    HookPhase.PRE_BUILD,
    HookPhase.POST_BUILD,
    HookPhase.PRE_EXECUTE,
    HookPhase.POST_EXECUTE,
    HookPhase.PRE_POST_PROCESS,
    HookPhase.POST_POST_PROCESS,
)


class HookContext:
    """
    Mutable context passed through all hook invocations.

    Attributes are intentionally generic; tools should use typed accessors.
    """

    def __init__(self, phase: HookPhase, data: Optional[Dict[str, Any]] = None) -> None:
        self.phase = phase
        self.data: Dict[str, Any] = data or {}
        self.state: HookState = HookState.CONTINUE
        self.errors: List[Exception] = []
        self.meta: Dict[str, Any] = {}

    # Convenience typed accessors -------------------------------------------

    @property
    def agent_id(self) -> Optional[str]:
        return self.data.get("agent_id")

    @property
    def user_id(self) -> Optional[str]:
        return self.data.get("user_id")

    @property
    def message(self) -> Optional[str]:
        return self.data.get("message")

    @property
    def response(self) -> Optional[str]:
        return self.data.get("response")

    @property
    def tools(self) -> Optional[List[Any]]:
        return self.data.get("tools")


class BaseHook(ABC):
    """
    Abstract hook contract. Subclass and implement `run` for phase-specific logic.
    """

    # Hook activation filter. Return True to run this hook for the given context.
    # Defaults to always active.
    is_active = True  # type: ignore[assignment]

    # Builtin hooks run before user hooks when both share the same phase.
    builtin: bool = False

    def __init__(self, name: Optional[str] = None) -> None:
        self.name = name or self.__class__.__name__

    @abstractmethod
    async def run(self, ctx: HookContext) -> HookState:
        """
        Execute hook logic for the current phase.

        Args:
            ctx: Mutable lifecycle context.

        Returns:
            Next control flow state. Default implementation returns CONTINUE.
        """
        return HookState.CONTINUE

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} phase={getattr(self, 'phase', '?')}>"


PHASE_HOOKS: Dict[HookPhase, List[BaseHook]] = {phase: [] for phase in PHASE_ORDER}


class HookManager:
    """
    Topological hook pipeline manager.

    Hooks are organized by phase and executed in registration order.
    Builtin hooks (``builtin=True``) execute before user hooks within the same phase.
    """

    def __init__(self) -> None:
        # Copy the module-level registry so tests remain isolated.
        self._hooks: Dict[HookPhase, List[BaseHook]] = {
            phase: list(hooks) for phase, hooks in PHASE_HOOKS.items()
        }

    def register(self, hook: BaseHook) -> None:
        """Register a hook instance under its ``phase`` attribute."""
        phase = getattr(hook, "phase", None)
        if phase is None:
            raise ValueError(f"Hook {hook.name!r} must declare a HookPhase")
        if not isinstance(phase, HookPhase):
            raise TypeError(f"Hook phase must be HookPhase, got {type(phase).__name__}")
        self._hooks.setdefault(phase, []).append(hook)

    def get_hooks(self, phase: HookPhase) -> List[BaseHook]:
        """Return builtin hooks first, then user hooks, preserving order."""
        hooks = self._hooks.get(phase, [])
        return sorted(hooks, key=lambda h: (not h.builtin, self._hooks[phase].index(h)))

    async def run(self, phase: HookPhase, data: Optional[Dict[str, Any]] = None) -> HookContext:
        """
        Execute all hooks for the given phase.

        Args:
            phase: Lifecycle phase identifier.
            data: Initial arbitrary payload passed to hooks.

        Returns:
            Mutable context with final state and any accumulated errors.
        """
        ctx = HookContext(phase=phase, data=data)

        active_hooks = [
            hook
            for hook in self.get_hooks(phase)
            if getattr(hook, "is_active", True) is True
        ]

        for hook in active_hooks:
            try:
                next_state = await hook.run(ctx)
            except Exception as exc:  # pylint: disable=broad-except
                ctx.errors.append(exc)
                ctx.state = HookState.SHORT_CIRCUIT
                break
            else:
                ctx.state = next_state
                if next_state in (HookState.SHORT_CIRCUIT, HookState.SKIP_AGENT):
                    break

        return ctx

    @property
    def phases(self) -> Iterable[HookPhase]:
        """Return all supported phases in topological order."""
        return PHASE_ORDER


# Module-level singleton for convenience; tests should instantiate HookManager.
default_manager = HookManager()
