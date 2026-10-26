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

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from project root before reading any env vars
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)


def _get_env(key: str, default: str = "") -> str:
    """Look up an env var with automatic COAPIS_ legacy fallback.

    Primary key is always used as-is.  When the primary key starts with
    ``COAPIS_``, the corresponding ``COAPIS_`` variant is transparently
    checked as a fallback so that existing deployments keep working.
    """
    if key in os.environ:
        return os.environ[key]
    if key.startswith("COAPIS_"):
        legacy_key = "COAPIS_" + key[len("COAPIS_") :]
        if legacy_key in os.environ:
            return os.environ[legacy_key]
    return default


class EnvVarLoader:
    """Utility to load and parse environment variables with type safety
    and defaults.  Pass COAPIS_* keys; COAPIS_* legacy variants are
    checked automatically as a fallback inside _get_env.
    """

    @staticmethod
    def get_bool(env_var: str, default: bool = False) -> bool:
        """Get a boolean environment variable,
        interpreting common truthy values."""
        val = _get_env(env_var, str(default)).lower()
        return val in ("true", "1", "yes")

    @staticmethod
    def get_float(
        env_var: str,
        default: float = 0.0,
        min_value: float | None = None,
        max_value: float | None = None,
        allow_inf: bool = False,
    ) -> float:
        """Get a float environment variable with optional bounds
        and infinity handling."""
        try:
            value = float(_get_env(env_var, str(default)))
            if min_value is not None and value < min_value:
                return min_value
            if max_value is not None and value > max_value:
                return max_value
            if not allow_inf and (
                value == float("inf") or value == float("-inf")
            ):
                return default
            return value
        except (TypeError, ValueError):
            return default

    @staticmethod
    def get_int(
        env_var: str,
        default: int = 0,
        min_value: int | None = None,
        max_value: int | None = None,
    ) -> int:
        """Get an integer environment variable with optional bounds."""
        try:
            value = int(_get_env(env_var, str(default)))
            if min_value is not None and value < min_value:
                return min_value
            if max_value is not None and value > max_value:
                return max_value
            return value
        except (TypeError, ValueError):
            return default

    @staticmethod
    def get_str(env_var: str, default: str = "") -> str:
        """Get a string environment variable with a default fallback."""
        return _get_env(env_var, default)


# WORKING_DIR priority:
# 1. COAPIS_WORKING_DIR env var is set → use it (fully configurable)
# 2. Default → ~/.coapis (user home directory)
#
# ⚠️ WORKING_DIR must be explicitly configured via COAPIS_WORKING_DIR env var.
_explicit_working_dir = _get_env("COAPIS_WORKING_DIR")
if _explicit_working_dir:
    WORKING_DIR = Path(_explicit_working_dir).expanduser().resolve()
else:
    WORKING_DIR = Path.home() / ".coapis"

# System directory - all system-level configs and data
# Contains: config.json, users.json, auth.json, permissions.json,
#           evolution_config.json, providers.json, token_usage.json, .secret/
SYSTEM_DIR = WORKING_DIR / "system"

# Global templates directory - shared base templates for all agents/users
# Contains: SOUL.md, MEMORY.md, PROFILE.md (global "soul" templates)
# New users inherit from these templates; global agents can override individually
TEMPLATES_DIR = SYSTEM_DIR / "templates"

# Data packs directory - language-aware initialization data
# Structure: data/packs/{base,zh,en,...}/
DATA_PACKS_DIR = Path(__file__).resolve().parent.parent / "data" / "packs"

# Workspaces directory - user-level data (isolated per user)
# Each user has: workspaces/{username}/ (agents, skills, files, crons, backups, etc.)
# Configurable via COAPIS_WORKSPACES_DIR (e.g. for NFS/separate storage)
WORKSPACES_DIR = Path(
    EnvVarLoader.get_str("COAPIS_WORKSPACES_DIR", f"{WORKING_DIR}/workspaces")
).expanduser().resolve()

LOG_DIR = WORKING_DIR / "logs"
LOGS_DIR = LOG_DIR  # Alias for backward compatibility
AUDIT_LOG_DIR = WORKING_DIR / "audit_log"  # Immutable audit trail (hash chain)
SKILLS_DIR = WORKING_DIR / "skills"
AGENTS_DIR = WORKING_DIR / "agents"

# Legacy aliases (for backward compatibility, points to SYSTEM_DIR)
# DEPRECATED: DATA_DIR is an alias for SYSTEM_DIR (system/ directory).
# All agent runtime data MUST go to agents/{id}/data/ or workspaces/{username}/.
# Do NOT use DATA_DIR in new code. Use AGENTS_DIR for agent data,
# WORKSPACES_DIR for user data, or SYSTEM_DIR directly for system config.
DATA_DIR = SYSTEM_DIR
CONFIG_DIR = SYSTEM_DIR


def _get_user_workspace_dir(username: str) -> Path:
    """Get user's workspace directory (unified user data path).
    
    Returns: workspaces/{username}/
    """
    return WORKSPACES_DIR / username


# ---------------------------------------------------------------------------
# Canonical agent naming (single source of truth — kills the dual-track)
# ---------------------------------------------------------------------------
#
# There is exactly ONE identity per agent: the semantic agent id.
#
#   user default agent : "user:{username}"      -> workspaces/{username}/
#   user sub-agent     : "{agent_key}" + owner  -> workspaces/{owner}/agents/{agent_key}/
#   global agent       : "global_*"              -> agents/{agent_id}/
#
# Display names (e.g. "王小伟") live ONLY in the ``name`` field and MUST
# NEVER take part in building an id or a directory name.  Legacy builds did
# ``f"{username}({display_name})"`` and produced dirs like
# ``workspaces/zrsz_153(王小伟)`` — that is what this module makes impossible.

USER_AGENT_ID_PREFIX = "user:"

#: Prefixes allowed to occupy ``AGENTS_DIR``.  ``global_*`` is the shared
#: baseline agent, ``scene-*`` is the scene agent directory written by
#: SceneAgentService (``agents/scene-{scene_id}/``).  Anything else sitting in
#: ``AGENTS_DIR`` is leftover data from the retired dual naming — most often a
#: *user* agent that a call site routed there by omitting ``username``.
GLOBAL_AGENT_ID_PREFIX = "global_"
SCENE_AGENT_ID_PREFIX = "scene-"
AGENTS_DIR_ID_PREFIXES = (GLOBAL_AGENT_ID_PREFIX, SCENE_AGENT_ID_PREFIX)


def is_agents_dir_scoped(agent_id: str) -> bool:
    """True when *agent_id* is allowed to live in ``AGENTS_DIR``.

    ``AGENTS_DIR`` is the global/scene namespace.  Registering a directory
    there that does not carry one of :data:`AGENTS_DIR_ID_PREFIXES` would
    hand a user's agent a second, *global* identity — the exact dual-track
    this module exists to remove.
    """
    return isinstance(agent_id, str) and agent_id.startswith(
        AGENTS_DIR_ID_PREFIXES,
    )


#: Max length of a username / agent key (filesystem + header friendly).
AGENT_KEY_MAX_LEN = 64

#: Characters that must never appear in a username or agent key.  Covers path
#: separators, the id namespace separator ``:``, bracket/quote forms used by
#: legacy display-name pollution, and anything a shell/URL/JSON layer would
#: have to quote.
_FORBIDDEN_KEY_CHARS = frozenset(
    '/\\:()[]{}|<>\'"`'
    " \t\n\r\v\f"
    "?*;&=%#~!@$^,"
)

#: Control characters (0x00-0x1F, 0x7F) — never allowed.
_CONTROL_CHARS = frozenset(chr(c) for c in range(0x20)) | {chr(0x7F)}


def is_valid_agent_key(key: str) -> bool:
    """True when *key* is safe to use as a username / agent key / dir name.

    Allowed: ASCII letters+digits, ``_``, ``-``, ``.``, and CJK (production
    has Chinese usernames, so ASCII-only would be a regression).
    Rejected: empty, over-long, leading ``.``, path traversal, and any
    character in :data:`_FORBIDDEN_KEY_CHARS` / :data:`_CONTROL_CHARS`.
    """
    if not isinstance(key, str) or not key:
        return False
    if len(key) > AGENT_KEY_MAX_LEN:
        return False
    if key.startswith(".") or ".." in key:
        return False
    for ch in key:
        if ch in _CONTROL_CHARS or ch in _FORBIDDEN_KEY_CHARS:
            return False
    return True


def normalize_agent_key(raw: str, *, kind: str = "username") -> str:
    """Validate *raw* as an agent key / username and return it.

    This is the single gate every call site that builds a workspace
    directory or an agent id MUST go through.  It never silently mutates the
    value: an unsafe key raises, so a bad name can never reach the disk.

    Raises:
        ValueError: when *raw* is empty, too long, or contains a forbidden
            character (message names the offending character).
    """
    if not isinstance(raw, str):
        raise ValueError(f"{kind} must be a string, got {type(raw).__name__}")
    key = raw.strip()
    if not key:
        raise ValueError(f"{kind} is empty")
    if len(key) > AGENT_KEY_MAX_LEN:
        raise ValueError(
            f"{kind} too long: {len(key)} > {AGENT_KEY_MAX_LEN}"
        )
    if key.startswith(".") or ".." in key:
        raise ValueError(f"{kind} must not contain path traversal: {raw!r}")
    for ch in key:
        if ch in _CONTROL_CHARS:
            raise ValueError(f"{kind} contains control character: {raw!r}")
        if ch in _FORBIDDEN_KEY_CHARS:
            raise ValueError(
                f"{kind} contains forbidden character {ch!r}: {raw!r} "
                f"(display names belong in the 'name' field, never in an id)"
            )
    return key


def user_agent_id(username: str) -> str:
    """Canonical id of a user's default agent: ``user:{username}``."""
    return f"{USER_AGENT_ID_PREFIX}{normalize_agent_key(username)}"


def is_user_agent_id(agent_id: str) -> bool:
    """True when *agent_id* is a user default-agent id."""
    return isinstance(agent_id, str) and agent_id.startswith(USER_AGENT_ID_PREFIX)


def username_from_user_agent_id(agent_id: str) -> str:
    """Extract the username out of ``user:{username}``."""
    if not is_user_agent_id(agent_id):
        raise ValueError(f"not a user agent id: {agent_id!r}")
    return agent_id[len(USER_AGENT_ID_PREFIX):]


def legacy_internal_agent_id(agent_id: str) -> bool:
    """True for the retired ``agent:{numeric}`` form (dual-track leftover).

    Kept around only so migration/compat code can recognise it; nothing in
    the runtime should produce it any more.
    """
    return isinstance(agent_id, str) and agent_id.startswith("agent:")


def agent_data_key(agent_id: str) -> str:
    """Filesystem-safe key for an agent's *runtime data* sub-directory.

    Runtime data lives at ``workspaces/{username}/agents/{key}/``.  The key
    must never be the full semantic id: ``agents/user:admin`` was created
    exactly that way, putting the id-namespace separator ``:`` into a
    directory name, where tooling, shells and URL encoding all choke on it.

    ``user:admin`` -> ``admin``; a bare sub-agent key passes through
    unchanged (and validated).

    Raises:
        ValueError: legacy ``agent:{n}`` id, or a key with unsafe characters.
    """
    if legacy_internal_agent_id(agent_id):
        raise ValueError(
            f"agent_data_key: legacy internal id {agent_id!r} has no data "
            "directory; normalise the workspace to 'user:{username}' first"
        )
    if is_user_agent_id(agent_id):
        return normalize_agent_key(username_from_user_agent_id(agent_id))
    return normalize_agent_key(agent_id, kind="agent key")


def sub_agent_key(agent_id: str) -> str:
    """Validate a sub-agent id coming from an API caller.

    Several routers build ``workspaces/{username}/agents/{agent_id}`` straight
    from the request body.  Without a gate, ``user:admin`` or
    ``zrsz_153(王小伟)`` becomes a directory name there — which is precisely
    how the colon-named and display-name-polluted workspaces appeared.

    Raises:
        ValueError: a user default-agent id (``user:*`` is not a sub-agent),
            a legacy ``agent:{n}`` id, or any unsafe key.
    """
    if is_user_agent_id(agent_id):
        raise ValueError(
            f"sub-agent id must not be a user default-agent id: {agent_id!r} "
            "(the 'user:' prefix is reserved for a user's default agent)"
        )
    if legacy_internal_agent_id(agent_id):
        raise ValueError(f"sub-agent id {agent_id!r} is the retired form")
    return normalize_agent_key(agent_id, kind="agent key")

# System-level file paths
CONFIG_JSON = SYSTEM_DIR / "config.json"
USERS_JSON = SYSTEM_DIR / "users.json"
AUTH_JSON = SYSTEM_DIR / "auth.json"
PERMISSIONS_JSON = SYSTEM_DIR / "permissions.json"
EVOLUTION_CONFIG_JSON = SYSTEM_DIR / "evolution_config.json"
PROVIDERS_JSON = SYSTEM_DIR / "providers.json"
TOKEN_USAGE_JSON = SYSTEM_DIR / "token_usage.json"

SECRET_DIR = (
    Path(
        EnvVarLoader.get_str(
            "COAPIS_SECRET_DIR",
            f"{SYSTEM_DIR}/.secret",
        ),
    )
    .expanduser()
    .resolve()
)

PROJECT_NAME = "CoApis"

# Default media directory for channels (cross-platform)
DEFAULT_MEDIA_DIR = WORKING_DIR / "media"

# Default local provider directory
DEFAULT_LOCAL_PROVIDER_DIR = WORKING_DIR / "local_models"

JOBS_FILE = EnvVarLoader.get_str("COAPIS_JOBS_FILE", "jobs.json")

CHATS_FILE = EnvVarLoader.get_str("COAPIS_CHATS_FILE", "chats.json")

# Ceiling for one model request, in seconds.  Measured on dev 2026-10-18: a
# chat whose upstream stalled sat in ``running`` for 18 min 40 s and produced
# **zero** log lines, because model clients were built with the SDK default of
# 600 s per request.  This is a per-read timeout, so a healthy stream that
# keeps producing chunks is unaffected -- only a stalled request dies, and
# ``RetryChatModel`` then retries it with backoff and says so in the log.
LLM_REQUEST_TIMEOUT_SECONDS = EnvVarLoader.get_float(
    "COAPIS_LLM_REQUEST_TIMEOUT_SECONDS",
    120.0,
    min_value=10.0,
    max_value=900.0,
)

# Ceiling for one **compaction** call, in seconds.  Compaction sits on the
# critical path of the next reasoning step, so it gets a tighter budget than
# a chat turn: a chunk that the server never answers is skipped and the
# summary merges from the chunks that did answer, which is a shorter summary
# instead of a chat that never answers.
CONTEXT_COMPACTION_TIMEOUT_SECONDS = EnvVarLoader.get_float(
    "COAPIS_CONTEXT_COMPACTION_TIMEOUT_SECONDS",
    90.0,
    min_value=10.0,
    max_value=600.0,
)

# Character cap for one compaction **map** request.  Fitting the window is not
# the same as answering in time: measured on dev 2026-10-18, chunks sized to
# the window came out at 70-90K chars and the model needed ~90 s for each, so
# a 305-row compaction burned 7+ minutes of the user's turn before the answer
# (5 chunks in series).  A chunk this size answers in seconds instead.
CONTEXT_COMPACTION_CHUNK_MAX_CHARS = EnvVarLoader.get_int(
    "COAPIS_CONTEXT_COMPACTION_CHUNK_MAX_CHARS",
    16_000,
    min_value=4_000,
    max_value=200_000,
)

# How many compaction map requests may be in flight at once.  Chunks are
# independent by construction, so serializing them buys nothing but latency.
CONTEXT_COMPACTION_MAP_CONCURRENCY = EnvVarLoader.get_int(
    "COAPIS_CONTEXT_COMPACTION_MAP_CONCURRENCY",
    3,
    min_value=1,
    max_value=8,
)

# Wall-clock ceiling for **one whole compaction**: every map chunk plus the
# merge.  The per-chunk timeout bounds a single call, which is not the same as
# bounding the work: measured on dev 2026-10-18, a 285-row compaction split
# into 19 chunks of 14,233 chars and the session sat in ``running`` for
# 18 min 40 s producing zero log lines.  Past this deadline the chunks that
# answered are merged and the rest are dropped -- a summary covering part of
# the history beats a compaction that never ends.
CONTEXT_COMPACTION_GLOBAL_TIMEOUT_SECONDS = EnvVarLoader.get_float(
    "COAPIS_CONTEXT_COMPACTION_GLOBAL_TIMEOUT_SECONDS",
    180.0,
    min_value=15.0,
    max_value=1800.0,
)

# How many experience extractions may run at once, server-wide.  Extraction is
# background work (5 strategies x N segments per session end), so it is capped
# the same way compaction is: a busy server finishes chats, it does not queue
# LLM work behind them.
EVOLUTION_EXTRACTION_SLOTS = EnvVarLoader.get_int(
    "COAPIS_EVOLUTION_EXTRACTION_SLOTS",
    2,
    min_value=1,
    max_value=8,
)

# One experience-extraction call, in seconds.  The extractor owns a raw
# provider client, which inherits the SDK's 600 s default; extraction ran on
# the path that closes the user's stream, so an endpoint that never answered
# held a delivered answer open for minutes (dev, 2026-10-18: 199 s).
EVOLUTION_EXTRACT_TIMEOUT_SECONDS = EnvVarLoader.get_float(
    "COAPIS_EVOLUTION_EXTRACT_TIMEOUT_SECONDS",
    45.0,
    min_value=5.0,
    max_value=300.0,
)

# One whole extraction round (5 strategies x every segment of the session), in
# seconds.  The per-call timeout bounds a single request; a session with many
# segments and a slow endpoint is bounded by the round, or the two extraction
# slots can be occupied for the better part of an hour by one chat.
EVOLUTION_EXTRACT_ROUND_TIMEOUT_SECONDS = EnvVarLoader.get_float(
    "COAPIS_EVOLUTION_EXTRACT_ROUND_TIMEOUT_SECONDS",
    300.0,
    min_value=30.0,
    max_value=1800.0,
)

# What a hard context prune archives in one go is dropped from working memory
# with no summary at all, and the deferred compaction then finds the history
# under its trigger and does nothing.  This is how many of those archived
# batches stay queued for a summary, and how much text they may carry in
# total; past the cap the oldest batch is dropped (the dialog/ archive on disk
# still holds every line).
CONTEXT_PRUNED_SUMMARY_MAX_BATCHES = EnvVarLoader.get_int(
    "COAPIS_CONTEXT_PRUNED_SUMMARY_MAX_BATCHES",
    3,
    min_value=1,
    max_value=16,
)

CONTEXT_PRUNED_SUMMARY_MAX_CHARS = EnvVarLoader.get_int(
    "COAPIS_CONTEXT_PRUNED_SUMMARY_MAX_CHARS",
    240_000,
    min_value=8_000,
    max_value=2_000_000,
)


# Builtin Q&A helper profile.  agent_id keeps "CoApis" prefix for existing
# workspaces and agent.json; do not rename.
def _discover_agent_languages() -> frozenset[str]:
    """Discover available agent languages from data/packs directory."""
    packs_dir = Path(__file__).resolve().parent / "data" / "packs"
    if packs_dir.is_dir():
        langs = {
            d.name
            for d in packs_dir.iterdir()
            if d.is_dir()
            and not d.name.startswith(".")
            and (d / "templates" / "user_level").exists()
        }
        if langs:
            return frozenset(langs)
    return frozenset({"en", "zh", "ru"})


SUPPORTED_AGENT_LANGUAGES: frozenset[str] = _discover_agent_languages()

BUILTIN_QA_AGENT_ID = "global_qa_agent"
BUILTIN_QA_AGENT_NAME = "QA Agent"
# Default skills when the builtin QA workspace is first created only.
BUILTIN_QA_AGENT_SKILL_NAMES: tuple[str, ...] = (
    "guidance",
    "QA_source_index",
)

# CoApis-era builtin QA; may remain in config.json — disabled when the current
# ``BUILTIN_QA_AGENT_ID`` profile is first created (see ``migration``), not
# every startup, so users can re-enable this id if they want.
LEGACY_QA_AGENT_ID = "CoPaw_QA_Agent_0.1beta1"

TOKEN_USAGE_FILE = EnvVarLoader.get_str(
    "COAPIS_TOKEN_USAGE_FILE",
    "token_usage.json",
)

CONFIG_FILE = EnvVarLoader.get_str("COAPIS_CONFIG_FILE", "config.json")

HEARTBEAT_FILE = EnvVarLoader.get_str("COAPIS_HEARTBEAT_FILE", "HEARTBEAT.md")
HEARTBEAT_DEFAULT_EVERY = "6h"
HEARTBEAT_DEFAULT_TARGET = "main"
HEARTBEAT_TARGET_LAST = "last"

# Debug history file for /dump_history and /load_history commands
DEBUG_HISTORY_FILE = EnvVarLoader.get_str(
    "COAPIS_DEBUG_HISTORY_FILE",
    "debug_history.jsonl",
)
MAX_LOAD_HISTORY_COUNT = 10000

# Env key for app log level (used by CLI and app load for reload child).
LOG_LEVEL_ENV = "COAPIS_LOG_LEVEL"

# Env to indicate running inside a container (e.g. Docker). Set to 1/true/yes.
RUNNING_IN_CONTAINER = EnvVarLoader.get_bool(
    "COAPIS_RUNNING_IN_CONTAINER",
    False,
)

# Timeout in seconds for checking if a provider is reachable.
MODEL_PROVIDER_CHECK_TIMEOUT = EnvVarLoader.get_float(
    "COAPIS_MODEL_PROVIDER_CHECK_TIMEOUT",
    5.0,
    min_value=0,
    allow_inf=False,
)

# Playwright: use system Chromium when set (e.g. in Docker).
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH_ENV = "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"

# When True, expose /docs, /redoc, /openapi.json
# (dev only; keep False in prod).
DOCS_ENABLED = EnvVarLoader.get_bool("COAPIS_OPENAPI_DOCS", False)

# ═══════════════════════════════════════════════════════════
# v0.5.1 新路径常量（记忆系统重构）
# ═══════════════════════════════════════════════════════════

# 全局进化机制（跨用户的经验聚合、技能统计、智能体进化）
# 位于 system/ 下，所有用户共享
SYSTEM_EVOLUTION_DIR = SYSTEM_DIR / "evolution"

# 全局审查记录（记忆/技能/经验审查）
SYSTEM_REVIEWS_DIR = SYSTEM_DIR / "reviews"

# 全局审计日志
SYSTEM_AUDIT_DIR = SYSTEM_DIR / "audit"

# 全局知识库（未来规划）
SYSTEM_KNOWLEDGE_DIR = SYSTEM_DIR / "knowledge"

# 临时数据目录（与 system/ 同级，可随时清理）
# 包含：对话轨迹、缓存、会话临时数据等
TMP_DIR = WORKING_DIR / "tmp"

# 临时数据子目录
TMP_EVOLUTION_DIR = TMP_DIR / "evolution"
TMP_EVOLUTION_TRAJECTORIES_DIR = TMP_EVOLUTION_DIR / "trajectories"
TMP_EVOLUTION_EXPERIENCES_DIR = TMP_EVOLUTION_DIR / "experiences"
TMP_CACHE_DIR = TMP_DIR / "cache"
TMP_SESSIONS_DIR = TMP_DIR / "sessions"

# 全局 agent 目录（保持不变）
# agents/{agent_id}/ 是全局智能体的根目录

# 用户级记忆目录（简化后的结构）
# workspaces/{username}/MEMORY.md - 用户默认智能体的经验记忆
# workspaces/{username}/memory/   - 用户默认智能体的每日记忆笔记
# workspaces/{username}/agents/{id}/MEMORY.md - 子智能体的经验记忆
# workspaces/{username}/agents/{id}/memory/   - 子智能体的每日记忆笔记

# Memory directory (global, for backward compatibility)
MEMORY_DIR = WORKING_DIR / "memory"

# Backup directory
BACKUP_DIR = (
    Path(
        EnvVarLoader.get_str(
            "COAPIS_BACKUP_DIR",
            f"{WORKING_DIR}.backups",
        ),
    )
    .expanduser()
    .resolve()
)

# Custom channel modules (installed via `coapis channels install`); manager
# loads BaseChannel subclasses from here.
CUSTOM_CHANNELS_DIR = WORKING_DIR / "custom_channels"

# Plugin directory (installed via `coapis plugin install`)
PLUGINS_DIR = WORKING_DIR / "plugins"

# Local models directory
MODELS_DIR = WORKING_DIR / "models"

MEMORY_COMPACT_KEEP_RECENT = EnvVarLoader.get_int(
    "COAPIS_MEMORY_COMPACT_KEEP_RECENT",
    3,
    min_value=0,
)

# Memory compaction configuration
MEMORY_COMPACT_RATIO = EnvVarLoader.get_float(
    "COAPIS_MEMORY_COMPACT_RATIO",
    0.7,
    min_value=0,
    allow_inf=False,
)

DASHSCOPE_BASE_URL = EnvVarLoader.get_str(
    "DASHSCOPE_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
)

# CORS configuration — comma-separated list of allowed origins for dev mode.
# Example: COAPIS_CORS_ORIGINS="http://localhost:5173,http://127.0.0.1:5173"
# When unset, CORS middleware is not applied.
CORS_ORIGINS = EnvVarLoader.get_str("COAPIS_CORS_ORIGINS", "").strip()

# LLM API retry configuration
LLM_MAX_RETRIES = EnvVarLoader.get_int(
    "COAPIS_LLM_MAX_RETRIES",
    3,
    min_value=0,
)

LLM_BACKOFF_BASE = EnvVarLoader.get_float(
    "COAPIS_LLM_BACKOFF_BASE",
    1.0,
    min_value=0.1,
)

LLM_BACKOFF_CAP = EnvVarLoader.get_float(
    "COAPIS_LLM_BACKOFF_CAP",
    10.0,
    min_value=0.5,
)

# LLM concurrency control
# Maximum number of concurrent in-flight LLM calls; excess requests wait on
# the semaphore.  Tune to your API quota: start conservatively at 3-5 and
# increase (e.g. OpenAI Tier 1 ~500 QPM allows ~25 at 3 s/call average).
LLM_MAX_CONCURRENT = EnvVarLoader.get_int(
    "COAPIS_LLM_MAX_CONCURRENT",
    10,
    min_value=1,
)

# Maximum queries per minute (QPM), enforced via a 60-second sliding window.
# New requests that would exceed this limit will wait before being dispatched
# to the API — proactively preventing 429s rather than reacting to them.
# 0 = unlimited (disabled).
# Examples: Anthropic Tier-1 ≈ 50 QPM; OpenAI Tier-1 ≈ 500 QPM.
LLM_MAX_QPM = EnvVarLoader.get_int(
    "COAPIS_LLM_MAX_QPM",
    600,
    min_value=0,
)

# Default global pause duration (seconds) applied to all waiters when a 429
# is received.  Overridden by the API's Retry-After header when present.
LLM_RATE_LIMIT_PAUSE = EnvVarLoader.get_float(
    "COAPIS_LLM_RATE_LIMIT_PAUSE",
    5.0,
    min_value=1.0,
)

# Random jitter range (seconds) added on top of the pause remaining time so
# concurrent waiters stagger their wake-up and avoid a new burst.
LLM_RATE_LIMIT_JITTER = EnvVarLoader.get_float(
    "COAPIS_LLM_RATE_LIMIT_JITTER",
    1.0,
    min_value=0.0,
)

# Maximum time (seconds) a caller will wait for a semaphore slot before
# giving up with a RuntimeError rather than blocking indefinitely.
LLM_ACQUIRE_TIMEOUT = EnvVarLoader.get_float(
    "COAPIS_LLM_ACQUIRE_TIMEOUT",
    300.0,
    min_value=10.0,
)

# Tool guard approval timeout (seconds).
try:
    TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS = max(
        float(
            _get_env("COAPIS_TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS", "300"),
        ),
        1.0,
    )
except (TypeError, ValueError):
    TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS = 300.0

# Tool guard approval heartbeat interval (seconds).
# Sends periodic heartbeat messages during approval wait to keep SSE
# connection alive. Should be less than browser/proxy timeout (30-60s).
try:
    TOOL_GUARD_APPROVAL_HEARTBEAT_INTERVAL = max(
        float(
            _get_env("COAPIS_TOOL_GUARD_APPROVAL_HEARTBEAT_INTERVAL", "15"),
        ),
        5.0,
    )
except (TypeError, ValueError):
    TOOL_GUARD_APPROVAL_HEARTBEAT_INTERVAL = 15.0

# Marker prepended to every truncation notice.
# Format:
#   <<<TRUNCATED>>>
#   The output above was truncated.
#   The full content is saved to the file and contains Z lines in total.
#   This excerpt starts at line X and covers the next N bytes.
#   If the current content is not enough, call `read_file` with
#   file_path=<path> start_line=Y to read more.
#
# Split output on this marker to recover the original (untruncated) portion:
#   original = output.split(TRUNCATION_NOTICE_MARKER)[0]
TRUNCATION_NOTICE_MARKER = "<<<TRUNCATED>>>"

# Placeholder text used when media blocks are stripped from messages
# because the model does not support multimodal content.
MEDIA_UNSUPPORTED_PLACEHOLDER = (
    "[Media content removed - model does not support this media type]"
)

# ═══════════════════════════════════════════════════════════
# 多用户系统常量
# ═══════════════════════════════════════════════════════════

# User system files are now in SYSTEM_DIR (unified system path)
# SYSTEM_DIR contains: config.json, users.json, auth.json, permissions.json, etc.

# Legacy aliases for backward compatibility
USERS_DIR = SYSTEM_DIR
AUTH_DIR = SYSTEM_DIR
USERS_FILE = SYSTEM_DIR / "users.json"
AUTH_FILE = SYSTEM_DIR / "auth.json"
# JWT signing secret: prefer env var (12-factor, recommended for production);
# falls back to the value stored in auth.json when unset.
JWT_SECRET = EnvVarLoader.get_str("COAPIS_JWT_SECRET", "").strip()

# Auth
TOKEN_EXPIRY_SECONDS = 7 * 24 * 3600  # 7 days default
TOKEN_EXPIRY_MAX = 100 * 365 * 24 * 3600  # 100 years for permanent

# Public API paths (no auth required)
PUBLIC_PATHS: frozenset = frozenset({
    # Root — SPA frontend (console handles auth routing internally)
    "/",
    # Auth endpoints (both /auth/ and /api/auth/ prefixes)
    "/auth/login",
    "/auth/status",
    "/auth/register",
    # /auth/verify NOT in PUBLIC_PATHS — must validate token to prevent
    # AuthGuard from always passing even with invalid tokens.
    "/auth/logout",
    "/api/auth/login",
    "/api/auth/status",
    "/api/auth/register",
    # User system auth endpoints (login/register via /api/users/)
    "/api/users/login",
    "/api/users/register",
    # SSO 单点登录（外部系统接入）
    "/api/external/login",
    "/external/login",
    # 外部系统 SSO（登录前匿名访问：按钮列表 / state 签发 / 回调验签 / 凭证直登）
    "/api/auth/external/systems",
    "/api/auth/external/login",
    "/api/auth/external/login-state",
    "/api/auth/external/credential-login",
    # 当前会话外部系统（头部徽标；端点内部自校验 token，未登录返回 null）
    "/api/auth/external/current-system",
    # Health and docs
    "/api/health",
    "/health",
    "/docs",
    "/openapi.json",
    # User config
    "/api/users/config",
    "/api/level-info",
    "/api/tokens/config",
    # Version (used by SPA on load)
    "/api/version",
    # Login page bootstrap — called before authentication
    "/api/settings/language",
    "/api/plugins",
    # SSE streaming endpoints — BaseHTTPMiddleware deadlocks with async generators
    "/api/console/chat",
    # Scene list (read-only, for workbench)
    "/api/scenes",
})

# Public prefixes (static assets + frontend)
PUBLIC_PREFIXES: tuple = (
    # Frontend SPA routes
    "/console",
    "/app/",
    "/assets/",
    # Static assets
    "/logo.png",
    "/coapis-symbol.svg",
    # Workbench public APIs (no auth required)
    # ⚠️ 注意：只开放只读API，enter需要认证
    "/api/scenes/workbench",  # Scene list for workbench (read-only)
    "/api/scenes/categories/grouped",  # Categories for workbench
    "/api/scenes/recommendations",  # Scene recommendations (read-only)
    "/api/scenes/hot",  # Hot scenes (read-only)
    # ⚠️ 只放开菜单端点，不放整段前缀：/api/admin/tags 前缀下的请求会被鉴权
    # 中间件标记为 anonymous，路由上的 @require_permission("tag:read") 拿不到
    # 用户名 → 已登录用户访问标签列表恒 401（实测 admin 也 401）。
    "/api/admin/tags/menu",  # Tag menu for workbench (read-only, 登录前渲染用)
    "/api/menus",  # Main menu configuration (read-only from tags.json)
    # Model management APIs (read-only, for default model selector)
    "/api/models/by-type",  # Get models by type (read-only)
    # SSO login APIs (for external system integration)
    "/api/external",  # SSO login endpoint (no auth required, it's for getting token)
    # Plugin asset files (enterprise frontend plugins entry JS)
    "/api/plugins/enterprise/files/",
    # 一次性预览票据（预览窗口方案 D6）：URL 里只有 60 秒即焚的短票据，
    # 身份由票据本身携带、兑换端点自行校验；旧 ?token=<JWT> 直链不受影响。
    "/api/myfiles/p/",
    "/api/myfiles/d/",
    "/favicon.ico",
    "/robots.txt",
)

# Growth system intervals
MEMORY_NUDGE_INTERVAL = 5
SKILL_NUDGE_INTERVAL = 8

# Evolution auto-review thresholds (可配置 via .env)
AUTO_APPROVE_CONFIDENCE = EnvVarLoader.get_float(
    "COAPIS_AUTO_APPROVE_CONFIDENCE", default=0.8, min_value=0.0, max_value=1.0,
)
SKILL_AUTO_REVIEW_THRESHOLD = EnvVarLoader.get_float(
    "COAPIS_SKILL_AUTO_REVIEW_THRESHOLD", default=0.5, min_value=0.0, max_value=1.0,
)

