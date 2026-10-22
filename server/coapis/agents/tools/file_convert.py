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

"""``convert_file`` — one-shot format conversion at delivery.

Markdown is the process and default deliverable format. This tool exists for
the single case where the user *explicitly* asked for another format (docx
today), so the agent converts once at delivery instead of shelling out to a
CLI that is not in the image (no pandoc/libreoffice).
"""

from __future__ import annotations

from pathlib import Path

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from ...utils.md_converter import (
    MdConversionError,
    SUPPORTED_TARGETS,
    convert_file as _convert,
)
from .file_io import _resolve_file_path, _resolve_write_path
from .registry import register_tool


def _text(msg: str) -> ToolResponse:
    return ToolResponse(content=[TextBlock(type="text", text=msg)])


@register_tool(
    name="convert_file",
    description=(
        "把已写好的 markdown 文件转换成用户明确要求的格式"
        "（当前支持 docx 与 pdf，中文可直接渲染）。"
        "必需参数：path（源文件）、target_format（目标格式，docx/pdf）。"
        "仅在用户明确指定格式时使用；过程中不要调用。"
        "生成 docx/pdf 一律用本工具，不要用 python3 -c 内联脚本"
        "（内联解释器需要审批）。"
    ),
    category="builtin",
    tags=["file", "convert", "docx", "pdf"],
)
async def convert_file(
    path: str,
    target_format: str = "docx",
    out_path: str = "",
) -> ToolResponse:
    """把 markdown 文件转换成指定格式。

    Args:
        path: 源 markdown 文件路径（相对路径从 workspace/files/ 解析）。
        target_format: 目标格式，默认 docx。支持 docx / pdf。
        out_path: 输出路径（可选）。默认与源文件同目录、同名换扩展名。

    Returns:
        转换结果说明。成功后请用 send_file_to_user 把文件发给用户。
    """
    try:
        src = Path(_resolve_file_path(path))
    except Exception as exc:  # pylint: disable=broad-except
        return _text(f"源文件路径无法解析：{exc}")

    dest = Path(await _resolve_write_path(out_path)) if out_path else None

    try:
        result = _convert(src, target_format, dest)
    except MdConversionError as exc:
        return _text(f"转换失败：{exc}")
    except Exception as exc:  # pylint: disable=broad-except
        return _text(f"转换失败：{type(exc).__name__}: {exc}")

    size = result.stat().st_size
    return _text(
        f"已转换：{src.name} → {result.name}（{size} 字节）。\n"
        f"输出路径：{result}\n"
        "请用 send_file_to_user 把文件发送给用户。",
    )


def supported_targets() -> tuple:
    """Exposed for tests and for the tool description/prompt wiring."""
    return SUPPORTED_TARGETS
