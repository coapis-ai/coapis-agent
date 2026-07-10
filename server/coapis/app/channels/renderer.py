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
"""Message Renderer — channel-aware display configuration.

Inspired by CoApis's RenderStyle, this module provides per-channel
display policies so that different channels (console, WeCom, DingTalk)
can have different visibility rules for thinking blocks, tool details,
emojis, and separators.

Usage:
    from .renderer import RenderStyle, MessageRenderer

    style = RenderStyle.from_channel("wecom")
    renderer = MessageRenderer(style)
    parts = renderer.render_block(block, full_response, full_reasoning)
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class BlockRenderAction(str, Enum):
    """What to do with a block."""
    SHOW = "show"           # Show content as-is
    HIDE = "hide"           # Completely suppress
    SUMMARIZE = "summarize"  # Replace with a brief summary
    EMOJI_ONLY = "emoji_only"  # Show only emoji indicator + friendly name


@dataclass
class RenderStyle:
    """Channel-specific display policy.

    Each field controls visibility of a specific block type.
    """
    # Thinking/reasoning blocks
    show_thinking: bool = False
    thinking_emoji: str = "🤔"

    # Tool call blocks
    show_tool_details: bool = False
    tool_emoji: str = "🔧"

    # Text blocks
    show_text: bool = True

    # Newlines / separators
    show_newlines: bool = False

    # Progress indicators (shown when block is hidden)
    show_progress: bool = True
    progress_emoji: str = "⏳"

    # Maximum thinking preview length (0 = no preview)
    thinking_preview_len: int = 0

    # Custom emoji mapping (tool_name -> emoji)
    tool_emoji_map: Dict[str, str] = field(default_factory=dict)

    # Filter tool call/output messages (only show media outputs)
    filter_tool_messages: bool = False

    # Internal tool names to skip in output display
    internal_tools: set = field(default_factory=set)

    @classmethod
    def from_channel(cls, channel_name: str, channel_config: dict = None) -> "RenderStyle":
        """Create a RenderStyle from channel name + optional config overrides."""
        presets = {
            "console": cls(
                show_thinking=True,
                show_tool_details=True,
                show_newlines=True,
                show_progress=False,
                thinking_preview_len=0,
            ),
            "wecom": cls(
                show_thinking=False,
                thinking_preview_len=120,
                show_tool_details=False,
                show_newlines=False,
                show_progress=True,
                progress_emoji="⏳",
                tool_emoji_map={
                    "web_search": "🔍",
                    "browser_use": "🌐",
                    "read_file": "📄",
                    "write_file": "✏️",
                    "execute_shell_command": "🖥️",
                    "desktop_screenshot": "📸",
                    "view_image": "🖼️",
                    "view_video": "🎬",
                    "send_file_to_user": "📤",
                    "get_current_time": "🕐",
                },
            ),
            "dingtalk": cls(
                show_thinking=False,
                show_tool_details=False,
                show_newlines=False,
                show_progress=True,
            ),
            "slack": cls(
                show_thinking=True,
                show_tool_details=True,
                show_newlines=True,
            ),
            "telegram": cls(
                show_thinking=False,
                show_tool_details=False,
                show_newlines=True,
                show_progress=True,
            ),
            # P0-3: All remaining channels default to hiding thinking,
            # showing tool emoji-only progress, no newlines.
            "discord": cls(
                show_thinking=False,
                show_tool_details=False,
                show_newlines=False,
                show_progress=True,
            ),
            "feishu": cls(
                show_thinking=False,
                show_tool_details=False,
                show_newlines=False,
                show_progress=True,
            ),
            "qq": cls(
                show_thinking=False,
                show_tool_details=False,
                show_newlines=False,
                show_progress=True,
            ),
            "weixin": cls(
                show_thinking=False,
                show_tool_details=False,
                show_newlines=False,
                show_progress=True,
            ),
            "xiaoyi": cls(
                show_thinking=False,
                show_tool_details=False,
                show_newlines=False,
                show_progress=True,
            ),
            "matrix": cls(
                show_thinking=False,
                show_tool_details=False,
                show_newlines=False,
                show_progress=True,
            ),
            "mattermost": cls(
                show_thinking=False,
                show_tool_details=False,
                show_newlines=False,
                show_progress=True,
            ),
            "mqtt": cls(
                show_thinking=False,
                show_tool_details=False,
                show_newlines=False,
                show_progress=True,
            ),
            "onebot": cls(
                show_thinking=False,
                show_tool_details=False,
                show_newlines=False,
                show_progress=True,
            ),
            "sip": cls(
                show_thinking=False,
                show_tool_details=False,
                show_newlines=False,
                show_progress=True,
            ),
            "voice": cls(
                show_thinking=False,
                show_tool_details=False,
                show_newlines=False,
                show_progress=True,
            ),
            "imessage": cls(
                show_thinking=False,
                show_tool_details=False,
                show_newlines=False,
                show_progress=True,
            ),
        }

        style = presets.get(channel_name, cls())  # Default: show everything

        # Apply config overrides
        if channel_config:
            # Map filter_* fields (agent.json convention) to show_* attrs (inverted)
            if "filter_thinking" in channel_config:
                style.show_thinking = not channel_config["filter_thinking"]
            if "filter_tool_messages" in channel_config:
                style.show_tool_details = not channel_config["filter_tool_messages"]
                style.filter_tool_messages = channel_config["filter_tool_messages"]
            # Direct show_* overrides
            for key, value in channel_config.items():
                if key.startswith("filter_"):
                    continue  # Already handled above
                attr_name = f"show_{key}" if not key.startswith("show_") else key
                if hasattr(style, attr_name):
                    setattr(style, attr_name, value)

        return style

    @classmethod
    def from_config_dict(cls, config: dict) -> "RenderStyle":
        """Create from a plain dict (e.g. user preferences or agent config)."""
        style = cls()
        for key, value in config.items():
            if hasattr(style, key):
                setattr(style, key, value)
        return style


# Friendly Chinese names for common tools
_TOOL_FRIENDLY_NAMES: Dict[str, str] = {
    "web_search": "搜索网页",
    "web_extract": "提取网页内容",
    "execute_shell_command": "执行命令",
    "browser_use": "浏览器操作",
    "read_file": "读取文件",
    "write_file": "写入文件",
    "edit_file": "编辑文件",
    "grep_search": "搜索文件内容",
    "glob_search": "查找文件",
    "desktop_screenshot": "截屏",
    "view_image": "查看图片",
    "view_video": "查看视频",
    "send_file_to_user": "发送文件",
    "get_current_time": "获取时间",
    "set_user_timezone": "设置时区",
    "list_agents": "查询智能体",
    "chat_with_agent": "与智能体对话",
    "submit_to_agent": "提交任务",
    "check_agent_task": "查看任务状态",
    "spawn_subagent": "创建子任务",
    "data_store": "数据存储",
    "data_ops": "数据操作",
    "text_processor": "文本处理",
    "get_token_usage": "查看用量",
    "memory_search": "记忆检索",
    "create_plan": "创建计划",
    "finish_plan": "完成计划",
}


class MessageRenderer:
    """Renders ResponseBlock objects according to a RenderStyle policy."""

    def __init__(self, style: RenderStyle = None):
        self.style = style or RenderStyle()

    def get_tool_action(self, tool_name: str) -> BlockRenderAction:
        """Determine how to render a tool_call block."""
        if self.style.show_tool_details:
            return BlockRenderAction.SHOW
        return BlockRenderAction.EMOJI_ONLY

    def get_thinking_action(self) -> BlockRenderAction:
        """Determine how to render a thinking block."""
        if self.style.show_thinking:
            return BlockRenderAction.SHOW
        if self.style.thinking_preview_len > 0:
            return BlockRenderAction.SUMMARIZE
        return BlockRenderAction.HIDE

    @staticmethod
    def _generate_tool_summary(tool_name: str, tool_args: dict) -> str:
        """Generate a human-readable summary of a tool call.

        Returns a short description of what the tool is doing,
        based on its parameters. Falls back to a generic description.
        """
        if not tool_args:
            return ""

        try:
            if tool_name == "execute_shell_command":
                cmd = tool_args.get("command", "")
                if len(cmd) > 60:
                    cmd = cmd[:60] + "…"
                return cmd

            if tool_name in ("read_file", "write_file", "send_file_to_user"):
                path = tool_args.get("file_path", "")
                if len(path) > 50:
                    path = "…" + path[-49:]
                start = tool_args.get("start_line")
                end = tool_args.get("end_line")
                if start or end:
                    return f"{path} (L{start or 1}-{end or 'end'})"
                return path

            if tool_name == "edit_file":
                path = tool_args.get("file_path", "")
                if len(path) > 40:
                    path = "…" + path[-39:]
                old = (tool_args.get("old_text") or "")[:25]
                if len(tool_args.get("old_text", "")) > 25:
                    old += "…"
                return f"{path}: \"{old}\" → …" if old else path

            if tool_name == "grep_search":
                pattern = tool_args.get("pattern", "")
                if len(pattern) > 40:
                    pattern = pattern[:40] + "…"
                path = tool_args.get("path", "")
                if path and len(path) > 30:
                    path = "…" + path[-29:]
                return f"\"{pattern}\"" + (f" in {path}" if path else "")

            if tool_name == "glob_search":
                return tool_args.get("pattern", "")

            if tool_name == "browser_use":
                action = tool_args.get("action", "")
                url = tool_args.get("url", "")
                text = tool_args.get("text", "")
                _action_labels = {
                    "open": "打开", "navigate": "导航", "snapshot": "快照",
                    "screenshot": "截图", "click": "点击", "type": "输入",
                    "start": "启动", "stop": "停止", "press_key": "按键",
                    "wait_for": "等待", "eval": "执行JS", "evaluate": "执行JS",
                }
                label = _action_labels.get(action, action)
                if url:
                    if len(url) > 50:
                        url = url[:50] + "…"
                    return f"{label} {url}"
                if text:
                    if len(text) > 30:
                        text = text[:30] + "…"
                    return f"{label} \"{text}\""
                return label

            if tool_name in ("web_search", "memory_search"):
                q = tool_args.get("query", "")
                if len(q) > 40:
                    q = q[:40] + "…"
                return f"\"{q}\""

            if tool_name in ("chat_with_agent", "submit_to_agent"):
                return f"→ {tool_args.get('to_agent', '')}"

            if tool_name == "spawn_subagent":
                task = tool_args.get("task", "")
                if len(task) > 50:
                    task = task[:50] + "…"
                return task

            if tool_name == "create_plan":
                return tool_args.get("name", "")

            if tool_name == "get_current_time":
                return ""

            if tool_name == "set_user_timezone":
                return tool_args.get("timezone_name", "")

            if tool_name == "get_token_usage":
                model = tool_args.get("model_name")
                if model:
                    return f"模型: {model}"
                days = tool_args.get("days", 30)
                return f"最近 {days} 天"

            if tool_name in ("view_image", "view_video"):
                return tool_args.get("image_path") or tool_args.get("video_path") or ""

            if tool_name == "desktop_screenshot":
                return ""

            if tool_name == "list_agents":
                return ""

            # Fallback: show first string parameter
            for v in tool_args.values():
                if isinstance(v, str) and v:
                    return v[:50] + ("…" if len(v) > 50 else "")
            return ""
        except Exception:
            return ""

    def render_tool_call(self, content: str, meta: dict = None) -> str:
        """Render a tool_call block based on style."""
        action = self.get_tool_action(meta.get("tool_name", "") if meta else "")
        tool_name = (meta or {}).get("tool_name", "工具")

        if action == BlockRenderAction.SHOW:
            return content
        elif action == BlockRenderAction.EMOJI_ONLY:
            emoji = self.style.tool_emoji_map.get(tool_name, self.style.tool_emoji)
            friendly = _TOOL_FRIENDLY_NAMES.get(tool_name, tool_name)
            summary = self._generate_tool_summary(
                tool_name, (meta or {}).get("tool_args", {}),
            )
            if summary:
                return f"{emoji} {friendly}: {summary}"
            return f"{emoji} {friendly}…"
        else:
            return ""

    def render_tool_output(self, content: str, meta: dict = None) -> str:
        """Render a tool_output block based on style."""
        action = self.get_tool_action(meta.get("tool_name", "") if meta else "")
        if action == BlockRenderAction.SHOW:
            return content
        else:
            return ""

    @staticmethod
    def _filter_tool_noise(content: str) -> str:
        """Remove tool execution noise from thinking content.

        Filters out paragraphs that are primarily about tool execution
        internals (e.g., "XX不可用", "XX大多数为空", tool call analysis)
        while preserving valuable reasoning content.
        """
        import re

        if not content or not content.strip():
            return content

        # Split into paragraphs (double newline or single newline for short lines)
        paragraphs = re.split(r'\n{2,}', content)
        if len(paragraphs) <= 1:
            # Single block — try splitting by single newline
            paragraphs = [p.strip() for p in content.split('\n') if p.strip()]
            if not paragraphs:
                return content

        # Tool noise patterns — lines/paragraphs matching these are filtered.
        # Only matches short paragraphs (<=100 chars) to avoid filtering
        # valuable reasoning that happens to mention tools.
        _NOISE_PATTERNS = [
            # Tool availability/result judgments (tool-centric phrases)
            r'工具.{0,5}不可用',
            r'工具.{0,5}失败',
            r'工具.{0,5}错误',
            r'工具.{0,5}返回.*?空',
            r'工具.{0,5}结果.*?空',
            r'工具.*?无法',
            r'调用.{0,5}工具.*?失败',
            r'执行.{0,5}工具.*?失败',
            r'尝试.{0,5}工具.*?失败',
            r'使用.{0,5}工具.*?失败',
            # Tool result summaries (short noise lines)
            r'^.{0,5}不可用。?$',
            r'^.{0,5}没有结果。?$',
            r'^.{0,5}大多数为空。?$',
            r'^.{0,5}返回空。?$',
            r'^.{0,5}返回了空。?$',
            r'^.{0,5}结果为空。?$',
            r'^.{0,5}调用失败。?$',
            r'^.{0,5}执行失败。?$',
            r'^.{0,5}获取失败。?$',
            r'^.{0,5}搜索.*?没有结果。?$',
            r'^.{0,5}搜索.*?为空。?$',
            r'^.{0,5}没有找到.*?结果。?$',
            r'^.{0,5}未找到.*?结果。?$',
            # Search/browse specific
            r'搜索.{0,10}没有结果',
            r'搜索.{0,10}失败',
            r'网页.{0,5}不可用',
            r'浏览器.{0,5}不可用',
            r'访问.{0,10}失败',
            r'打开.{0,10}失败',
            # Error descriptions (tool-context only)
            r'error.{0,5}tool',
            r'tool.{0,5}error',
            r'failed.{0,5}tool',
            r'tool.{0,5}failed',
            r'调用出错',
            r'执行出错',
            # Generic tool noise markers
            r'^\s*🔧',
            r'^\s*❌.*工具',
        ]
        _NOISE_RE = re.compile('|'.join(_NOISE_PATTERNS), re.IGNORECASE)

        filtered = []
        for para in paragraphs:
            para_stripped = para.strip()
            if not para_stripped:
                continue

            # Keep long paragraphs — they likely contain real reasoning
            if len(para_stripped) > 100:
                filtered.append(para_stripped)
                continue

            # Filter short paragraphs that match noise patterns
            if _NOISE_RE.search(para_stripped):
                continue

            filtered.append(para_stripped)

        return '\n\n'.join(filtered) if filtered else ''

    def render_thinking(self, content: str) -> str:
        """Render a thinking block based on style."""
        action = self.get_thinking_action()
        if action == BlockRenderAction.SHOW:
            return self._filter_tool_noise(content)
        elif action == BlockRenderAction.SUMMARIZE:
            filtered = self._filter_tool_noise(content)
            if not filtered:
                return ""
            preview = filtered[:self.style.thinking_preview_len]
            if len(filtered) > self.style.thinking_preview_len:
                preview += "…"
            return f"{self.style.thinking_emoji} {preview}"
        else:
            return ""  # Hidden

    def render_text(self, content: str) -> str:
        """Render a text block based on style."""
        if self.style.show_text:
            return content
        return ""

    def render_newline(self) -> str:
        """Render a newline separator based on style."""
        if self.style.show_newlines:
            return "\n"
        return ""

    # ── message_to_parts: aligned with QwenPaw ──────────────────────

    def message_to_parts(self, message: Any) -> List[Any]:
        """Convert a Message object into sendable OutgoingContentPart list.

        Handles: text, tool_call, tool_output, reasoning, media.
        Uses RenderStyle policy to decide visibility.
        """
        from agentscope_runtime.engine.schemas.agent_schemas import (
            MessageType,
            TextContent,
            ImageContent,
            VideoContent,
            AudioContent,
            FileContent,
            ContentType,
        )

        msg_type = getattr(message, "type", None)
        content = getattr(message, "content", None) or []
        s = self.style

        # Filter reasoning messages if configured
        if not s.show_thinking and msg_type == MessageType.REASONING:
            return []

        logger.debug(
            "renderer message_to_parts: msg_type=%s content_len=%s",
            msg_type, len(content),
        )

        # ── Tool call messages ──
        if msg_type in (
            MessageType.FUNCTION_CALL,
            MessageType.PLUGIN_CALL,
            MessageType.MCP_TOOL_CALL,
        ):
            if s.filter_tool_messages:
                return []
            parts = []
            for c in content:
                if getattr(c, "type", None) != ContentType.DATA:
                    continue
                data = getattr(c, "data", None) or {}
                name = data.get("name") or "tool"
                args = data.get("arguments") or "{}"
                if s.show_tool_details:
                    args_preview = args[:200] + "..." if len(args) > 200 else args
                else:
                    args_preview = "..."
                emoji = s.tool_emoji_map.get(name, s.tool_emoji)
                friendly = _TOOL_FRIENDLY_NAMES.get(name, name)
                text = f"{emoji} **{friendly}**\n```\n{args_preview}\n```"
                parts.append(TextContent(text=text))
            return parts or [TextContent(text=f"[{msg_type}]")]

        # ── Tool output messages ──
        if msg_type in (
            MessageType.FUNCTION_CALL_OUTPUT,
            MessageType.PLUGIN_CALL_OUTPUT,
            MessageType.MCP_TOOL_CALL_OUTPUT,
        ):
            if s.filter_tool_messages:
                # Still pass through media parts
                media_types = (ContentType.IMAGE, ContentType.AUDIO, ContentType.VIDEO, ContentType.FILE)
                media_parts = []
                for c in content:
                    if getattr(c, "type", None) != ContentType.DATA:
                        continue
                    data = getattr(c, "data", None) or {}
                    name = data.get("name") or "tool"
                    if name in s.internal_tools:
                        continue
                    output = data.get("output")
                    block_parts = self._extract_parts_from_output(output)
                    for p in block_parts:
                        if getattr(p, "type", None) in media_types:
                            media_parts.append(p)
                return media_parts

            parts = []
            for c in content:
                if getattr(c, "type", None) != ContentType.DATA:
                    continue
                data = getattr(c, "data", None) or {}
                name = data.get("name") or "tool"
                if name in s.internal_tools:
                    continue
                output = data.get("output")
                emoji = s.tool_emoji_map.get(name, s.tool_emoji)
                label = f"{emoji} **{_TOOL_FRIENDLY_NAMES.get(name, name)}**:"

                if isinstance(output, list):
                    # Structured output blocks (text, image, etc.)
                    block_parts = self._extract_parts_from_output(output)
                    if block_parts:
                        parts.append(TextContent(text=label))
                        parts.extend(block_parts)
                    else:
                        parts.append(TextContent(text=f"{label}\n`...`"))
                elif isinstance(output, str):
                    preview = output[:500] + "..." if len(output) > 500 else output
                    parts.append(TextContent(text=f"{label}\n```\n{preview}\n```"))
                elif output is not None:
                    raw = str(output)
                    preview = raw[:500] + "..." if len(raw) > 500 else raw
                    parts.append(TextContent(text=f"{label}\n```\n{preview}\n```"))
            return parts

        # ── Regular text/content message ──
        parts = []
        for c in content:
            ctype = getattr(c, "type", None)
            if ctype == ContentType.TEXT:
                text = getattr(c, "text", "")
                if text:
                    parts.append(TextContent(text=text))
            elif ctype == ContentType.REFUSAL:
                refusal = getattr(c, "refusal", "")
                if refusal:
                    parts.append(TextContent(text=refusal))
            elif ctype == ContentType.IMAGE:
                url = getattr(c, "image_url", None)
                if url:
                    parts.append(ImageContent(image_url=url))
            elif ctype == ContentType.VIDEO:
                url = getattr(c, "video_url", None)
                if url:
                    parts.append(VideoContent(video_url=url))
            elif ctype == ContentType.AUDIO:
                data = getattr(c, "data", None)
                if data:
                    parts.append(AudioContent(data=data))
            elif ctype == ContentType.FILE:
                url = getattr(c, "file_url", None) or getattr(c, "file_id", None)
                if url:
                    parts.append(FileContent(file_url=url))
        return parts

    def _extract_parts_from_output(self, output: Any) -> List[Any]:
        """Extract parts from structured tool output (list of blocks)."""
        from agentscope_runtime.engine.schemas.agent_schemas import (
            TextContent,
            ImageContent,
            VideoContent,
            AudioContent,
            FileContent,
        )

        if not isinstance(output, list):
            return []
        parts = []
        for block in output:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text" and block.get("text"):
                parts.append(TextContent(text=block["text"]))
            elif btype == "thinking":
                # Only show thinking if style allows
                if self.style.show_thinking and block.get("thinking"):
                    parts.append(TextContent(text=f"🤔 {block['thinking']}"))
            elif btype in ("image", "audio", "video", "file"):
                src = block.get("source") or {}
                stype = src.get("type")
                url = None
                if stype == "url" and src.get("url"):
                    url = src["url"]
                elif stype == "base64" and src.get("data"):
                    mt = src.get("media_type") or "application/octet-stream"
                    url = f"data:{mt};base64,{src['data']}"
                if url:
                    if btype == "image":
                        parts.append(ImageContent(image_url=url))
                    elif btype == "video":
                        parts.append(VideoContent(video_url=url))
                    elif btype == "audio":
                        parts.append(AudioContent(data=url))
                    else:
                        parts.append(FileContent(file_url=url))
        return parts
