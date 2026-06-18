"""Auto-register all builtin tools into the plugin registry.

All tools use @register_tool decorator — this module ensures every tool
module is imported so the decorator fires. No manual registry entries needed.
"""

# ── Core file I/O ──
from . import file_io
from . import file_search
from . import shell
from . import send_file
from . import browser_control
from . import desktop_screenshot
from . import view_media
from . import get_current_time
from . import get_token_usage
from . import agent_management

# ── Agent management ──
from . import delegate_external_agent

# ── Skill / memory / knowledge ──
from . import todo_tool
from . import web_search
from . import ast_search
from . import memory_manager
from . import notes
from . import session_search
from . import doc_reader

# ── Code tools ──
from . import file_diff
from . import project_analyzer
from . import git_ops
from . import cron_scheduler
from . import text_processor
from . import deploy_helper

# ── v0.7.x tools (standalone) ──
from . import image_gen
from . import http_client
from . import tool_stats
from . import context_manager
from . import archive_ops
from . import env_manager
from . import clipboard_ops
from . import auto_heal
from . import resource_guard
from . import changelog_gen
from . import task_delegation
from . import structured_logger

# ── v0.7.21 merged tools ──
from . import code_quality
from . import knowledge_rag
from . import sys_monitor
from . import api_tools
from . import fault_tolerance
from . import data_store

# ── v0.7.22 new merged tools ──
from . import code_exec
from . import llm_helper
from . import data_ops
from . import security_scan
from . import security_ops
from . import collab_ops

# ── Old tools merged into newer tools above — files deleted ──
# code_formatter, code_docgen, code_review → code_quality
# knowledge_base, rag_search, embedding_ops → knowledge_rag
# perf_monitor, health_check, trace_ops → sys_monitor
# api_mock, schema_validate → api_tools
# checkpoint_tool, error_recovery → fault_tolerance
# db_ops, cache_ops, queue_ops → data_store
# from . import secret_scan     — merged into security_scan
# from . import dependency_audit — merged into security_scan
# from . import audit_log       — merged into security_ops
# from . import crypto_ops      — merged into security_ops
# from . import notify_ops      — merged into collab_ops
# from . import shared_state    — merged into collab_ops
# from . import test_runner     — merged into code_exec
# from . import code_runner     — merged into code_exec
# from . import llm_ops         — merged into llm_helper
# from . import prompt_builder  — merged into llm_helper
# from . import data_processor  — merged into data_ops
# from . import batch_ops       — merged into data_ops


def register_all_builtin_tools() -> int:
    """Ensure all builtin tool modules are imported.

    Every tool module above uses @register_tool decorator, which
    auto-registers into the global registry on import. This function
    simply ensures all modules are loaded.

    Returns:
        Always returns 0 (registration is decorator-driven now).
    """
    return 0
