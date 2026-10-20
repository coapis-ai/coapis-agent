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

"""Safe JSON session with filename sanitization for cross-platform
compatibility.

Windows filenames cannot contain: \\ / : * ? " < > |
This module wraps agentscope's SessionBase so that session_id and user_id
are sanitized before being used as filenames.
"""
import os
import re
import json
import uuid
import inspect
import logging

from typing import Any, Dict, Union, Sequence

import aiofiles
from agentscope.session import SessionBase
from agentscope_runtime.engine.schemas.exception import ConfigurationException
from ...exceptions import AgentStateError

logger = logging.getLogger(__name__)


def _safe_json_loads(content: str, filepath: str = "") -> dict:
    """Parse JSON with corruption recovery.

    Attempts standard ``json.loads`` first.  If that fails due to
    trailing garbage (a common symptom of concurrent-write race
    conditions), falls back to ``raw_decode`` to extract the first
    valid JSON object.  If the file is completely unparseable, returns
    an empty dict and logs a warning so callers never crash.

    Args:
        content: Raw file content.
        filepath: Used only for log messages.

    Returns:
        Parsed dict, or ``{}`` when the content is beyond recovery.
    """
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Try to extract the first valid JSON object.
    try:
        result, _ = json.JSONDecoder().raw_decode(content)
        logger.warning(
            "Session file %s had corrupted JSON. "
            "Recovered first valid object via raw_decode.",
            filepath,
        )
        return result
    except json.JSONDecodeError:
        logger.warning(
            "Session file %s is completely corrupted and could not "
            "be recovered. Returning empty dict.",
            filepath,
        )
        return {}


# Characters forbidden in Windows filenames
_UNSAFE_FILENAME_RE = re.compile(r'[\\/:*?"<>|]')


def sanitize_filename(name: str) -> str:
    """Replace characters that are illegal in Windows filenames with ``--``.

    >>> sanitize_filename('discord:dm:12345')
    'discord--dm--12345'
    >>> sanitize_filename('normal-name')
    'normal-name'
    """
    return _UNSAFE_FILENAME_RE.sub("--", name)


def _normalize_content_block(block: dict) -> dict:
    """Normalize a single content block: ensure ``type`` exists and strip
    streaming-event fields that should never be persisted.

    This handles two classes of legacy data:
    1. Blocks without ``type`` — infer from structure (thinking, tool_use, …)
    2. Blocks with ``type`` but bloated with streaming-event fields
       (sequence_number, object, status, error, index, delta, msg_id)
    """
    if not isinstance(block, dict):
        return block

    # --- Step 1: ensure type exists ---
    if "type" not in block:
        if "thinking" in block:
            block["type"] = "thinking"
        elif "tool_use_id" in block or (
            "is_error" in block and "content" in block
        ):
            block["type"] = "tool_result"
        elif "id" in block and "name" in block and "input" in block:
            block["type"] = "tool_use"
        elif "text" in block:
            block["type"] = "text"
        elif "image_url" in block:
            block["type"] = "image"
        elif "data" in block and "format" in block:
            block["type"] = "audio"
        elif "video_url" in block:
            block["type"] = "video"
        else:
            block["type"] = "text"

    # --- Step 2: strip streaming-event junk if present ---
    btype = block.get("type", "text")
    has_streaming_junk = any(
        k in block
        for k in ("sequence_number", "object", "status", "error",
                   "index", "delta", "msg_id")
    )
    if has_streaming_junk:
        if btype == "thinking":
            clean = {k: block[k] for k in ("type", "thinking") if k in block}
        elif btype == "tool_use":
            clean = {k: block[k] for k in ("type", "id", "name", "input") if k in block}
        elif btype == "tool_result":
            clean = {k: block[k] for k in ("type", "tool_use_id", "content", "is_error") if k in block}
        else:
            clean = {k: block[k] for k in ("type", "text") if k in block}
        block.clear()
        block.update(clean)

    return block


def _ensure_content_block_types(state_dict: dict) -> dict:
    """Ensure all content blocks in memory have a 'type' field.

    The agentscope InMemoryMemory stores Msg objects whose content blocks
    (TextBlock, ThinkingBlock, etc.) sometimes lack the ``type`` key when
    the agent creates them without it.  This causes history messages to
    lose their type information after a serialize → deserialize round-trip,
    making every block appear as plain text.

    This helper patches the ``agent.memory.content`` array in-place before
    the state dict is written to disk, inferring ``type`` from the block
    structure for backward-compatible old records.
    """
    if not isinstance(state_dict, dict):
        return state_dict

    memory = state_dict.get("agent", {}).get("memory", {})
    content = memory.get("content", [])
    if not isinstance(content, list):
        return state_dict

    for item in content:
        # Each item is [msg_dict, marks] or just msg_dict
        msg_dict = None
        if isinstance(item, (list, tuple)) and len(item) >= 1:
            msg_dict = item[0]
        elif isinstance(item, dict):
            msg_dict = item

        if not isinstance(msg_dict, dict):
            continue

        blocks = msg_dict.get("content", [])
        if not isinstance(blocks, list):
            continue

        for i, block in enumerate(blocks):
            if not isinstance(block, dict):
                continue
            blocks[i] = _normalize_content_block(block)

    return state_dict


def _load_state_tolerant(state_module: Any, saved: Any) -> list[str]:
    """Restore one state module, skipping keys the module does not declare.

    ``StateModule.load_state_dict(strict=True)`` raises ``KeyError`` for every
    module the agent registers that the saved file does not contain, and a
    session file written before a module existed is the normal case, not an
    error: measured on dev 2026-10-19, 10 occurrences of
    ``Key 'toolkit' not found in state_dict`` in 24 hours -- one per chat
    **start** -- and the runner's handler threw the whole saved history away
    ("will save fresh state on completion to recover file").

    ``strict=False`` is the documented switch for exactly this: it skips
    missing keys and restores everything the file does carry.  Modules that
    predate the ``strict`` keyword keep the old behaviour, and the skipped
    keys are returned so a "the file was recovered" claim is checkable in the
    log instead of being asserted.
    """
    keys = set(saved) if isinstance(saved, dict) else set()
    try:
        declared = set(getattr(state_module, "_module_dict", {}) or {})
        declared |= set(getattr(state_module, "_attribute_dict", {}) or {})
    except Exception:  # pragma: no cover - exotic modules
        declared = set()
    missing = sorted(declared - keys)

    try:
        accepts_strict = "strict" in inspect.signature(
            state_module.load_state_dict,
        ).parameters
    except (TypeError, ValueError):
        accepts_strict = False

    if accepts_strict:
        state_module.load_state_dict(saved, strict=False)
    else:
        state_module.load_state_dict(saved)
    return missing


class SafeJSONSession(SessionBase):
    """SessionBase subclass with filename sanitization and async file I/O.

    Overrides all file-reading/writing methods to use :mod:`aiofiles` so
    that disk I/O does not block the event loop.
    """

    def __init__(
        self,
        save_dir: str = "./",
    ) -> None:
        """Initialize the JSON session class.

        Args:
            save_dir (`str`, defaults to `"./"):
                The directory to save the session state.
        """
        self.save_dir = save_dir

    def _get_save_path(self, session_id: str, user_id: str) -> str:
        """Return a filesystem-safe save path.

        Overrides the parent implementation to ensure the generated
        filename is valid on Windows, macOS and Linux.
        """
        os.makedirs(self.save_dir, exist_ok=True)
        safe_sid = sanitize_filename(session_id)
        safe_uid = sanitize_filename(user_id) if user_id else ""
        if safe_uid:
            file_path = f"{safe_uid}_{safe_sid}.json"
        else:
            file_path = f"{safe_sid}.json"
        return os.path.join(self.save_dir, file_path)

    async def save_session_state(
        self,
        session_id: str,
        user_id: str = "",
        **state_modules_mapping,
    ) -> None:
        """Save state modules to a JSON file using atomic async I/O.

        Writes to a .tmp file first, then renames atomically to prevent
        corruption on crash/power-loss.
        """
        state_dicts = {
            name: state_module.state_dict()
            for name, state_module in state_modules_mapping.items()
        }
        # Ensure content blocks always have 'type' for proper history rendering
        _ensure_content_block_types(state_dicts)
        session_save_path = self._get_save_path(session_id, user_id=user_id)
        # ⚠ 并发安全：tmp 路径必须唯一。旧写法固定用 `save_path + ".tmp"`，
        # 同一会话并发保存（多消息/多渠道同时落盘）时两个协程会写同一个 tmp
        # 文件，短内容覆盖长内容后残留尾部字节 → 状态文件出现非法 UTF-8 尾巴，
        # 下次加载直接 UnicodeDecodeError，整条聊天 failed。
        tmp_path = f"{session_save_path}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        payload = json.dumps(state_dicts, ensure_ascii=False)
        try:
            async with aiofiles.open(
                tmp_path, "wb",
            ) as f:
                await f.write(payload.encode("utf-8", errors="replace"))
                await f.flush()
                # Force flush to disk before rename
                try:
                    os.fsync(f.fileno())
                except (AttributeError, OSError):
                    pass  # aiofiles may not expose fileno
            os.replace(tmp_path, session_save_path)
            logger.info(
                "Saved session state to %s successfully.",
                session_save_path,
            )
        except Exception:
            logger.error(
                "Failed to save session state to %s",
                session_save_path,
                exc_info=True,
            )
            # Clean up tmp file on failure
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
            raise

    @staticmethod
    def _decode_state_bytes(raw: bytes, path: str) -> str:
        """Decode a session state file, never raising on invalid bytes.

        Falls back from strict UTF-8 (surrogatepass, needed for agent state
        round-tripping) to a lossy decode, and finally to truncating at the
        last complete JSON object so a corrupted tail cannot kill a session.
        """
        try:
            return raw.decode("utf-8", errors="surrogatepass")
        except UnicodeDecodeError:
            pass
        text = raw.decode("utf-8", errors="replace")
        # 尾部脏字节通常落在合法 JSON 之后：截到最后一个完整闭合的顶层对象。
        end = text.rfind("}")
        if end != -1:
            candidate = text[: end + 1]
            try:
                json.loads(candidate)
                return candidate
            except (json.JSONDecodeError, ValueError):
                pass
        logger.warning(
            "session state file %s contains invalid bytes; "
            "decoded lossily (session history may be partially lost)",
            path,
        )
        return text

    async def load_session_state(
        self,
        session_id: str,
        user_id: str = "",
        allow_not_exist: bool = True,
        **state_modules_mapping,
    ) -> None:
        """Load state modules from a JSON file using async I/O."""
        session_save_path = self._get_save_path(session_id, user_id=user_id)
        if os.path.exists(session_save_path):
            # ⚠ 容错解码：旧写法用 errors="surrogatepass"，它对任意非法字节
            # （如 0x94）直接抛 UnicodeDecodeError，导致整条聊天 response=failed。
            # 状态文件是缓存而非唯一真相，绝不能因为尾部脏字节让会话彻底不可用。
            async with aiofiles.open(session_save_path, "rb") as f:
                raw = await f.read()
            content = self._decode_state_bytes(raw, session_save_path)
            states = _safe_json_loads(content, session_save_path)

            for name, state_module in state_modules_mapping.items():
                if name in states:
                    # Patch old records missing 'type' in content blocks
                    _ensure_content_block_types(states)
                    missing = _load_state_tolerant(state_module, states[name])
                    if missing:
                        logger.info(
                            "Session state for '%s' restored with %d module(s) "
                            "the file did not carry (%s); the rest was loaded.",
                            name,
                            len(missing),
                            ", ".join(missing),
                        )
            logger.info(
                "Load session state from %s successfully.",
                session_save_path,
            )

        elif allow_not_exist:
            logger.info(
                "Session file %s does not exist. Skip loading session state.",
                session_save_path,
            )

        else:
            raise AgentStateError(
                session_id=session_id,
                message=(
                    f"Failed to load session state for file "
                    f"{session_save_path} because it does not exist"
                ),
            )

    async def update_session_state(
        self,
        session_id: str,
        key: Union[str, Sequence[str]],
        value,
        user_id: str = "",
        create_if_not_exist: bool = True,
    ) -> None:
        """Update a key in the session state file using atomic async I/O.

        Reads the existing state, merges the new key-value pair, then writes
        atomically (tmp + rename) to prevent corruption on crash/power-loss.
        """
        session_save_path = self._get_save_path(session_id, user_id=user_id)

        if os.path.exists(session_save_path):
            try:
                async with aiofiles.open(
                    session_save_path,
                    "r",
                    encoding="utf-8",
                    errors="surrogatepass",
                ) as f:
                    content = await f.read()
                    states = _safe_json_loads(content, session_save_path)
            except Exception:
                logger.error(
                    "Failed to read session state from %s, starting fresh",
                    session_save_path,
                    exc_info=True,
                )
                states = {}

        else:
            if not create_if_not_exist:
                raise AgentStateError(
                    session_id=session_id,
                    message=f"Session file {session_save_path} does not exist",
                )
            states = {}

        path = key.split(".") if isinstance(key, str) else list(key)
        if not path:
            raise ConfigurationException(
                message="key path is empty",
            )

        cur = states
        for k in path[:-1]:
            if k not in cur or not isinstance(cur[k], dict):
                cur[k] = {}
            cur = cur[k]

        cur[path[-1]] = value

        # Ensure content blocks always have 'type' for proper history rendering
        _ensure_content_block_types(states)

        tmp_path = session_save_path + ".tmp"
        try:
            async with aiofiles.open(
                tmp_path, "w", encoding="utf-8",
            ) as f:
                await f.write(json.dumps(states, ensure_ascii=False))
                await f.flush()
                try:
                    os.fsync(f.fileno())
                except (AttributeError, OSError):
                    pass
            os.replace(tmp_path, session_save_path)
            logger.info(
                "Updated session state key '%s' in %s successfully.",
                key,
                session_save_path,
            )
        except Exception:
            logger.error(
                "Failed to update session state key '%s' in %s",
                key,
                session_save_path,
                exc_info=True,
            )
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
            raise

    async def get_session_state_dict(
        self,
        session_id: str,
        user_id: str = "",
        allow_not_exist: bool = True,
    ) -> dict:
        """Return the session state dict from the JSON file.

        Args:
            session_id (`str`):
                The session id.
            user_id (`str`, default to `""`):
                The user ID for the storage.
            allow_not_exist (`bool`, defaults to `True`):
                Whether to allow the session to not exist. If `False`, raises
                an error if the session does not exist.

        Returns:
            `dict`:
                The session state dict loaded from the JSON file. Returns an
                empty dict if the file does not exist and
                `allow_not_exist=True`.
        """
        session_save_path = self._get_save_path(session_id, user_id=user_id)
        if os.path.exists(session_save_path):
            async with aiofiles.open(
                session_save_path,
                "r",
                encoding="utf-8",
                errors="surrogatepass",
            ) as file:
                content = await file.read()
                states = _safe_json_loads(content, session_save_path)

            # Patch old records missing 'type' in content blocks
            _ensure_content_block_types(states)

            logger.info(
                "Get session state dict from %s successfully.",
                session_save_path,
            )
            return states

        if allow_not_exist:
            logger.info(
                "Session file %s does not exist. Return empty state dict.",
                session_save_path,
            )
            return {}

        raise AgentStateError(
            session_id=session_id,
            message=(
                f"Failed to get session state for file {session_save_path} "
                f"because it does not exist"
            ),
        )
