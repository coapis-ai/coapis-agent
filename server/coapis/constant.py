# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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
# 2. Default → /apps/ai/coapis (standard deployment path)
#
# ⚠️ WORKING_DIR must be explicitly configured via COAPIS_WORKING_DIR env var.
# No implicit fallback to ~/.coapis.
_explicit_working_dir = _get_env("COAPIS_WORKING_DIR")
if _explicit_working_dir:
    WORKING_DIR = Path(_explicit_working_dir).expanduser().resolve()
else:
    WORKING_DIR = Path("/apps/ai/coapis").resolve()

# System directory - all system-level configs and data
# Contains: config.json, users.json, auth.json, permissions.json,
#           evolution_config.json, providers.json, token_usage.json, .secret/
SYSTEM_DIR = WORKING_DIR / "system"

# Global templates directory - shared base templates for all agents/users
# Contains: SOUL.md, MEMORY.md, PROFILE.md (global "soul" templates)
# New users inherit from these templates; global agents can override individually
TEMPLATES_DIR = SYSTEM_DIR / "templates"

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


# Builtin Q&A helper profile.  agent_id keeps "CoApis" prefix for existing
# workspaces and agent.json; do not rename.
def _discover_agent_languages() -> frozenset[str]:
    md_root = Path(__file__).resolve().parent / "agents" / "md_files"
    if md_root.is_dir():
        langs = {
            d.name
            for d in md_root.iterdir()
            if d.is_dir()
            and not d.name.startswith(".")
            and any(d.glob("*.md"))
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

# Auth
AUTH_ENABLED_ENV = "COAPIS_AUTH_ENABLED"
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
    "/auth/verify",
    "/auth/logout",
    "/api/auth/login",
    "/api/auth/status",
    "/api/auth/register",
    # User system auth endpoints (login/register via /api/users/)
    "/api/users/login",
    "/api/users/register",
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
    # SSE streaming endpoints — BaseHTTPMiddleware deadlocks with async generators
    "/api/console/chat",
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
    "/favicon.ico",
    "/robots.txt",
)

# Growth system intervals
MEMORY_NUDGE_INTERVAL = 5
SKILL_NUDGE_INTERVAL = 8

