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

"""Tool schema dynamic routing — send only relevant tool schemas per turn.

Groups tools into functional categories and selects which groups to include
based on the current conversation context (last few messages). Core tools
are always included; other groups are activated by intent keywords.

This reduces the baseline tool schema payload from ~8,200 tokens to
~1,200 tokens for typical conversational turns.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ── Tool grouping ──────────────────────────────────────────────────────────
# Each group maps to a set of tool function names.
# Tools not in any group fall into "rarely" (loaded only on explicit match).

TOOL_GROUPS: dict[str, set[str]] = {
    # Always loaded — core conversation tools
    "core": {
        "read_file",
        "write_file",
        "edit_file",
        "append_file",
        "grep_search",
        "glob_search",
        "execute_shell_command",
        "get_current_time",
        "set_user_timezone",
        "send_file_to_user",
    },
    # Web tools
    "web": {
        "browser_use",
        "web_search",
    },
    # Code / execution tools
    "code": {
        "code_exec",
        "git_ops",
    },
    # Agent collaboration tools
    "agent": {
        "chat_with_agent",
        "submit_to_agent",
        "check_agent_task",
        "list_agents",
        "spawn_subagent",
    },
    # Data / file format tools
    "data": {
        "doc_reader",
    },
    # System / admin tools
    "system": {
        "browser_use",
        "desktop_screenshot",
        "view_image",
        "view_video",
    },
    # Memory / knowledge tools
    "memory": {
        "session_search",
    },
    # Skill tools
    "skill": {
        "skill_manager",
    },
    # Rarely used tools — only loaded on explicit match
    "rarely": {
        "cron_scheduler",
        "tool_stats",
    },
}

# ── Intent detection ──────────────────────────────────────────────────────
# Maps keyword patterns to groups to activate.
# ORDER MATTERS: first match wins for each group.

INTENT_KEYWORDS: dict[str, list[str]] = {
    "web": [
        r"搜[索一下]", r"打开.*网站", r"浏览", r"网页", r"网页",
        r"search", r"browse", r"website", r"url", r"http", r"fetch",
        r"查找.*资料", r"google", r"百度", r"上网",
        r"新闻", r"news", r"头条", r"热点", r"最新消息",
        r"天气", r"weather", r"温度",
        r"查[一]?下", r"查一下", r"lookup", r"find\sinfo",
        r"今天.*什么", r"最近.*发生",
    ],
    "code": [
        r"运行", r"执行.*代码", r"python", r"shell", r"bash",
        r"脚本", r"run\s", r"execute", r"script", r"command",
        r"写.*脚本", r"写.*代码", r"终端", r"命令行",
    ],
    "agent": [
        r"问问.*智能体", r"咨询.*agent", r"让.*帮忙",
        r"spawn", r"subagent", r"协同", r"协作",
    ],
    "data": [
        r"\.xlsx", r"\.csv", r"\.pdf", r"\.docx", r"\.pptx",
        r"表格", r"excel", r"电子表格", r"数据.*分析",
        r"spreadsheet", r"table.*data",
    ],
    "system": [
        r"系统信息", r"进程", r"上传", r"下载", r"发送.*文件",
        r"system.info", r"process", r"upload", r"download",
    ],
    "memory": [
        r"知识库", r"knowledge", r"记忆.*管理",
        r"memory.*manage", r"忘记.*什么",
    ],
    "media": [
        r"图片.*生成", r"画[一幅]", r"图片.*编辑",
        r"音频", r"语音", r"image.*generat", r"tts",
        r"generate.*image", r"transcri",
    ],
    "rarely": [
        r"定时任务", r"cron", r"提醒我", r"remind",
        r"截屏", r"screenshot", r"邮件", r"email", r"邮箱",
    ],
}

# Pre-compile patterns for performance
_COMPILED_INTENTS: dict[str, list[re.Pattern]] = {
    group: [re.compile(p, re.IGNORECASE) for p in patterns]
    for group, patterns in INTENT_KEYWORDS.items()
}


def _build_reverse_index() -> dict[str, str]:
    """Build tool_name → group_name mapping."""
    result = {}
    for group, tools in TOOL_GROUPS.items():
        for t in tools:
            result[t] = group
    return result


_TOOL_TO_GROUP = _build_reverse_index()


class ToolSchemaRouter:
    """Select which tool schemas to send to the model per reasoning turn.

    Usage::

        router = ToolSchemaRouter()
        all_schemas = toolkit.get_json_schemas()
        filtered = router.route(all_schemas, recent_messages)
        # Pass filtered to model(prompt, tools=filtered, ...)
    """

    def route(
        self,
        all_schemas: list[dict[str, Any]],
        recent_messages: list[dict[str, Any]] | None = None,
        enable_full: bool = False,
    ) -> list[dict[str, Any]]:
        """Filter tool schemas based on conversation context.

        Args:
            all_schemas: Full list of tool JSON schemas from toolkit.
            recent_messages: Recent conversation messages for intent detection.
                Each message dict should have at least 'content' key.
            enable_full: If True, return all schemas (no filtering).

        Returns:
            Filtered list of tool schemas.
        """
        if enable_full or not all_schemas:
            return all_schemas

        # Always include core group
        active_groups = {"core"}

        # Detect intent from recent messages
        if recent_messages:
            combined_text = self._extract_text(recent_messages)
            detected = self._detect_intent(combined_text)
            active_groups.update(detected)

        # Also include any tool that was explicitly called in recent messages
        # (to ensure the same tool stays available for follow-up)
        if recent_messages:
            called_tools = self._extract_tool_calls(recent_messages)
            for t in called_tools:
                group = _TOOL_TO_GROUP.get(t)
                if group:
                    active_groups.add(group)

        # Build set of tool names to include
        active_tools: set[str] = set()
        for g in active_groups:
            active_tools.update(TOOL_GROUPS.get(g, set()))

        # Filter schemas
        result = []
        for schema in all_schemas:
            func = schema.get("function", {})
            name = func.get("name", "")
            # Include if in active group OR if not in any known group
            # (unknown tools are always included for safety)
            if name in active_tools or name not in _TOOL_TO_GROUP:
                result.append(schema)

        # Log filtering stats
        total = len(all_schemas)
        filtered = len(result)
        if total != filtered:
            logger.info(
                "ToolSchemaRouter: %d/%d tools selected "
                "(groups=%s, intent=%s)",
                filtered, total,
                sorted(active_groups),
                self._detect_intent(
                    self._extract_text(recent_messages) if recent_messages else ""
                ),
            )

        return result

    @staticmethod
    def _extract_text(messages: list[dict[str, Any]]) -> str:
        """Extract text content from recent messages."""
        parts = []
        # Only look at last 3 messages for intent
        for msg in messages[-3:]:
            content = msg.get("content", "")
            if isinstance(content, str):
                parts.append(content[:500])
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", "")[:500])
                    elif hasattr(block, "text"):
                        parts.append(block.text[:500])
        return " ".join(parts)

    @staticmethod
    def _detect_intent(text: str) -> set[str]:
        """Detect which tool groups should be activated from text."""
        groups = set()
        for group, patterns in _COMPILED_INTENTS.items():
            for p in patterns:
                if p.search(text):
                    groups.add(group)
                    break  # One match per group is enough
        return groups

    @staticmethod
    def _extract_tool_calls(messages: list[dict[str, Any]]) -> set[str]:
        """Extract tool names that were recently called."""
        tools = set()
        for msg in messages[-3:]:
            content = msg.get("content", "")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        # Check for tool_use blocks
                        if block.get("type") == "tool_use":
                            tools.add(block.get("name", ""))
                        # Check for tool_call in content
                        if block.get("type") == "tool_call":
                            fn = block.get("function", {})
                            if isinstance(fn, dict):
                                tools.add(fn.get("name", ""))
            # Also check role-based tool messages
            if msg.get("role") == "tool":
                name = msg.get("name", "")
                if name:
                    tools.add(name)
        return tools

    @staticmethod
    def estimate_tokens(schemas: list[dict[str, Any]]) -> int:
        """Rough estimate of token count for a list of tool schemas."""
        try:
            total_chars = len(json.dumps(schemas, ensure_ascii=False))
            return total_chars // 4  # rough: 4 chars ≈ 1 token
        except Exception:
            return 0
