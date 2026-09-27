# -*- coding: utf-8 -*-
"""TelemetryInstaller: instance-local spies over tool + LLM chokepoints.

Wraps the eval agent's ``ToolRegistry.call`` and the OpenAI client's
``chat.completions.create`` (covers BOTH the streaming path used by
``stream_chat`` and the non-streaming ``_call_llm`` path, so every LLM
round-trip is counted exactly once).  Restores originals on uninstall.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, List, Optional

logger = logging.getLogger(__name__)


class TrajectoryRecorder:
    """Collects tool calls and LLM activity for one eval run."""

    def __init__(self) -> None:
        self.started_at = time.time()
        self.tool_calls: List[dict] = []
        self.llm_calls: int = 0
        self.input_tokens: int = 0
        self.output_tokens: int = 0
        self.steps: List[dict] = []

    @property
    def duration_ms(self) -> float:
        return (time.time() - self.started_at) * 1000

    @property
    def tool_call_names(self) -> List[str]:
        return [c["name"] for c in self.tool_calls]

    def reset(self) -> None:
        """Start a fresh recording window (called per benchmark task)."""
        self.started_at = time.time()
        self.tool_calls.clear()
        self.llm_calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.steps.clear()

    def to_row(self) -> dict:
        return {
            "tool_calls": self.tool_calls,
            "llm_calls": self.llm_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "duration_ms": round(self.duration_ms, 1),
            "steps": self.steps,
        }


class TelemetryInstaller:
    def __init__(self, core: Any, registry: Any) -> None:
        self.core = core
        self.registry = registry
        self.recorder = TrajectoryRecorder()
        self._orig_tool_call: Optional[Callable] = None
        self._orig_completions_create: Optional[Callable] = None
        self._wrapped_completions: Optional[Any] = None

    def install(self) -> None:
        # ---- tool chokepoint ------------------------------------------- #
        if self.registry is not None and hasattr(self.registry, "call"):
            self._orig_tool_call = self.registry.call

            async def _spied_tool_call(name: str, *args: Any, **kwargs: Any):
                t0 = time.time()
                ok = True
                err = None
                try:
                    result = await self._orig_tool_call(name, *args, **kwargs)
                    return result
                except Exception as exc:  # noqa: BLE001 - record and rethrow
                    ok = False
                    err = repr(exc)
                    raise
                finally:
                    ms = (time.time() - t0) * 1000
                    self.recorder.tool_calls.append({
                        "name": name,
                        "args": kwargs,
                        "ok": ok,
                        "error": err,
                        "ms": round(ms, 1),
                    })
                    self.recorder.steps.append({
                        "kind": "tool", "name": name,
                        "ok": ok, "ms": round(ms, 1),
                    })

            self.registry.call = _spied_tool_call

        # ---- LLM chokepoint -------------------------------------------- #
        # stream_chat() talks to ``core.client.chat.completions.create``
        # directly (bypassing _call_llm), so the client method is the only
        # chokepoint that sees every round-trip exactly once.
        client = getattr(self.core, "client", None) if self.core is not None else None
        completions = getattr(getattr(client, "chat", None), "completions", None)
        if completions is not None and self._orig_completions_create is None:
            self._orig_completions_create = completions.create
            self._wrapped_completions = completions

            async def _spied_create(*args: Any, **kwargs: Any):
                self.recorder.llm_calls += 1
                self.recorder.steps.append({"kind": "llm"})
                resp = await self._orig_completions_create(*args, **kwargs)
                usage = getattr(resp, "usage", None)
                if usage is not None:
                    self.recorder.input_tokens += int(
                        getattr(usage, "prompt_tokens", 0) or 0
                    )
                    self.recorder.output_tokens += int(
                        getattr(usage, "completion_tokens", 0) or 0
                    )
                return resp

            completions.create = _spied_create

    def uninstall(self) -> None:
        if self.registry is not None and self._orig_tool_call is not None:
            self.registry.call = self._orig_tool_call
            self._orig_tool_call = None
        if self._wrapped_completions is not None and self._orig_completions_create is not None:
            self._wrapped_completions.create = self._orig_completions_create
            self._wrapped_completions = None
            self._orig_completions_create = None
