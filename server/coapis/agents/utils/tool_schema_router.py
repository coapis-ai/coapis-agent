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
        "file_read",
        "list_files",
        "file_write",
        "edit_file",
        "memory_search",
        "memory_save",
    },
    # Web tools
    "web": {
        "browser_use",
        "web_search",
        "tavily_search",
        "tavily_extract",
        "exa_search",
        "exa_answer",
        "exa_extract",
        "jina_reader",
        "fetch_url",
    },
    # Code / execution tools
    "code": {
        "execute_shell_command",
        "python_execute",
        "code_execute",
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
        "xlsx_read",
        "xlsx_write",
        "csv_read",
        "csv_write",
        "json_read",
        "json_write",
        "pdf_read",
        "docx_read",
        "pptx_read",
        "image_to_text",
    },
    # System / admin tools
    "system": {
        "system_info",
        "process_list",
        "file_upload",
        "file_download",
        "send_file_to_user",
    },
    # Memory / knowledge tools
    "memory": {
        "memory_list",
        "memory_delete",
        "knowledge_search",
        "knowledge_add",
    },
    # Media tools
    "media": {
        "image_generate",
        "image_edit",
        "audio_transcribe",
        "tts_speak",
    },
    # Rarely used tools — only loaded on explicit match
    "rarely": {
        "cron_create",
        "cron_list",
        "cron_delete",
        "desktop_screenshot",
        "view_image",
        "view_video",
        "himalaya_send",
        "himalaya_list",
        "himalaya_read",
        "channel_send",
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
