"""Auto-register all builtin tools into the plugin registry.

Only HIGH-FREQUENCY tools retain @register_tool. Low-frequency tools
keep their code but are NOT auto-registered (schema bloat reduction).
They can still be imported on-demand by skills or agents that need them.
"""

# ── Core file I/O (always needed) ──
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

# ── Skill / memory ──
from . import todo_tool
from . import web_search
from . import session_search
from . import doc_reader
from . import skill_manager

# ── Code tools ──
from . import git_ops
from . import cron_scheduler
from . import tool_stats

# ── Code execution ──
from . import code_exec

# ── Low-frequency tools: REMOVED from auto-registration ──
# These tools keep their code but don't register @register_tool,
# reducing schema from ~62 tools to ~30 high-frequency ones.
#
# # Skill / memory (low-freq)
# from . import ast_search      — rare, use web_search instead
# from . import memory_manager  — handled by MemoryManager directly
# from . import notes           — rare, use file_io instead
#
# # Code tools (low-freq)
# from . import file_diff       — merged into git_ops (diff support)
# from . import project_analyzer — rare, on-demand only
# from . import text_processor  — rare, use shell instead
# from . import deploy_helper   — rare, on-demand only
#
# # v0.7.x standalone (low-freq)
# from . import image_gen       — rare, on-demand only
# from . import http_client     — rare, use shell curl instead
# from . import context_manager — internal, not user-facing
# from . import archive_ops     — merged into shell (tar/zip support)
# from . import env_manager     — rare, on-demand only
# from . import clipboard_ops   — rare, desktop-only
# from . import auto_heal       — rare, internal diagnostics
# from . import resource_guard  — rare, internal diagnostics
# from . import changelog_gen   — rare, on-demand only
# from . import task_delegation — rare, use delegate_external_agent
#
# # v0.7.21 merged (low-freq)
# from . import code_quality    — rare, on-demand only
# from . import sys_monitor     — rare, on-demand only
# from . import api_tools       — rare, on-demand only
# from . import fault_tolerance — rare, on-demand only
# from . import data_store      — rare, on-demand only
#
# # v0.7.22 merged (low-freq)
# from . import llm_helper      — rare, on-demand only
# from . import data_ops        — rare, on-demand only
# from . import security_ops    — merged into security_scan
# from . import collab_ops      — rare, on-demand only
# from . import security_scan   — rare, on-demand only

# ── Previously merged tools (code deleted, consolidated) ──
# code_formatter, code_docgen, code_review → code_quality
# knowledge_base, rag_search, embedding_ops → knowledge_rag
# perf_monitor, health_check, trace_ops → sys_monitor
# api_mock, schema_validate → api_tools
# checkpoint_tool, error_recovery → fault_tolerance
# db_ops, cache_ops, queue_ops → data_store
# secret_scan, dependency_audit → security_scan
# audit_log, crypto_ops → security_ops
# notify_ops, shared_state → collab_ops
# test_runner, code_runner → code_exec
# llm_ops, prompt_builder → llm_helper
# data_processor, batch_ops → data_ops


def register_all_builtin_tools() -> int:
    """Ensure all HIGH-FREQUENCY builtin tool modules are imported.

    Every tool module above uses ``@register_tool`` — this function
    simply triggers the imports so the decorators fire.

    Returns:
        Number of tool modules imported.
    """
    import sys as _sys
    imported = 0
    for mod_name, mod in list(_sys.modules.items()):
        if mod_name.startswith("coapis.agents.tools."):
            imported += 1
    return imported
