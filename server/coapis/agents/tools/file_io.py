# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
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
from typing import Optional

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from .registry import register_tool
from .utils import (
    truncate_text_output,
    read_file_safe,
    DEFAULT_MAX_BYTES,
)
from ...config.context import (
    get_current_workspace_dir,
    get_current_folder_ref,
    get_current_recent_max_bytes,
)
from ...constant import WORKING_DIR, TRUNCATION_NOTICE_MARKER


def _resolve_file_path(file_path: str) -> str:
    """Resolve file path for READ operations: use absolute path as-is,
    resolve relative path from current workspace/files/ or WORKING_DIR/files/.

    Note: This is for reading files. For writing, use _resolve_write_path.
    
    Path resolution rules:
    1. Absolute paths → used as-is
    2. Relative paths → resolved from workspace/files/
       (consistent with write_file behavior)

    Args:
        file_path: The input file path (absolute or relative).

    Returns:
        The resolved absolute file path as string.
    """
    path = Path(file_path).expanduser()
    if path.is_absolute():
        return str(path)
    else:
        # 目录引用激活时，相对路径在被引用的目录内解析——这是「目录引用 =
        # 设置对话工作目录」的真实语义；否则相对路径仍从 workspace/files/
        # 根解析，智能体只能自己补目录前缀（实测会先失败一次）。
        folder_ref = get_current_folder_ref()
        if folder_ref is not None:
            return str(Path(folder_ref) / file_path)
        # Use current workspace_dir from context, fallback to WORKING_DIR
        workspace_dir = get_current_workspace_dir() or WORKING_DIR
        # 确保 workspace_dir 是 Path 对象
        workspace_dir = Path(workspace_dir)
        # 用户文件存储在 workspace/files/ 目录
        files_dir = workspace_dir / "files"
        # 读取侧同样接受带 files/ 前缀的写法：写工具回报的相对路径就是
        # ``files/2026-10/x.md`` 这种形态，模型抄回来时必须命中同一文件，
        # 否则会解析成 files/files/... 而"写了却读不到"。
        rel_in = Path(file_path)
        if rel_in.parts[:1] == ("files",):
            rel_in = (
                Path(*rel_in.parts[1:]) if len(rel_in.parts) > 1 else Path(".")
            )
        target = files_dir / rel_in
        # 读写口径对称：写侧把裸文件名重排进 files/{月}/{日期}_{任务}/ 并回报
        # 完整相对路径，模型经常只抄回裸文件名。精确路径不存在时按
        # "本会话目录 → 当月 → files 根"兜底，否则"刚写的文件读不到"。
        if not target.exists() and len(rel_in.parts) == 1 and rel_in.name:
            try:
                from ..context.session_dir import find_loose_file
                from ...config.session_context import get_current_chat_id

                hit = find_loose_file(
                    files_dir,
                    rel_in.name,
                    chat_id=get_current_chat_id(),
                )
            except Exception:  # noqa: BLE001 - 兜底失败就按原路径报错
                hit = None
            if hit is not None:
                return str(hit)
        return str(target)


async def _resolve_write_path(file_path: str) -> str:
    """Resolve file path for WRITE operations.

    Priority rules:
    1. Absolute paths → used as-is
    2. Active folder reference → inside the referenced directory
       (the user picked that directory; the system must not re-layout it)
    3. Relative paths → ``files/{YYYY-MM}/{YYYY-MM-DD}_{任务}/<name>``

       目录由系统按会话身份决定（见 ``agents/context/session_dir.py``）：
       模型只给文件名，"放哪个目录"不再是它的决定。无会话身份时退化为
       月层平铺，与历史行为一致。

    Args:
        file_path: The input file path (absolute or relative).

    Returns:
        The resolved absolute file path as string.
    """
    path = Path(file_path).expanduser()
    if path.is_absolute():
        return str(path)

    # 目录引用激活时写入落在被引用的目录内，与读取保持一致，避免读写
    # 落在不同目录导致智能体「写了却读不到」。
    folder_ref = get_current_folder_ref()
    if folder_ref is not None:
        ref_dir = Path(folder_ref)
        ref_dir.mkdir(parents=True, exist_ok=True)
        return str(ref_dir / file_path)

    workspace_dir = get_current_workspace_dir() or WORKING_DIR
    # 确保 workspace_dir 是 Path 对象
    workspace_dir = Path(workspace_dir)
    files_dir = workspace_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    # Reads report paths under the "files/" prefix, so the model habitually
    # echoes that prefix back when writing ("files/notes.md").  Joining it
    # verbatim yields "files/files/notes.md", which fails for a new file and
    # silently targets the wrong place for an existing one.  Drop the
    # redundant leading segment.
    rel = Path(file_path)
    if rel.parts[:1] == ("files",):
        rel = Path(*rel.parts[1:]) if len(rel.parts) > 1 else Path(".")

    from ..context.session_dir import (
        flatten_rel_path,
        scratch_dir_target,
        session_write_dir,
        system_dir_target,
    )
    from ...config.session_context import (
        get_current_chat_id,
        get_current_username,
    )

    # 系统/治理目录：落在工作区根，绝不进 files/、更不进会话目录。
    # 依据：治理模块本来就写 {workspace}/tool_results，技能/记忆/会话状态
    # 同理；混进会话目录会把系统缓存当成"我的空间"里的用户产出。
    sys_target = system_dir_target(rel, workspace_dir)
    if sys_target is not None:
        sys_target.parent.mkdir(parents=True, exist_ok=True)
        return str(sys_target)

    # 临时区固定 files/.temp —— cleanup_manager 的清理规则只认这个路径
    # （保留 1 天、每小时扫）。落进会话目录的 .temp 清理扫不到，提示词里
    # "默认写 .temp、自动清理"的承诺就落空了。
    scratch = scratch_dir_target(rel, files_dir)
    if scratch is not None:
        scratch.parent.mkdir(parents=True, exist_ok=True)
        return str(scratch)

    # 用户自建目录引用（files/季度报告/x.md）：目录已存在就尊重原路径，
    # 不重排进会话目录 —— 用户建的主题目录是显式分类，系统不覆盖。
    if len(rel.parts) >= 2 and (files_dir / rel.parts[0]).is_dir():
        return str(files_dir / rel)

    try:
        session_dir = await session_write_dir(
            files_dir,
            get_current_chat_id(),
            get_current_username(),
        )
    except Exception:  # noqa: BLE001 - 目录解析绝不能阻断写文件
        session_dir = files_dir

    target = session_dir / flatten_rel_path(rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    return str(target)


def _get_encoding_for_file(file_path: str) -> str:
    """Determine the appropriate encoding for a file based on its type.

    For cross-platform compatibility, especially with Windows Excel/Notepad:
    - CSV/TSV/TXT files: Use UTF-8-BOM (Windows Excel needs BOM to detect UTF-8)
    - All other files: Use UTF-8 (safer default, no BOM)

    Args:
        file_path: Path to the file

    Returns:
        Encoding string: "utf-8-sig" or "utf-8"
    """
    suffix = Path(file_path).suffix.lower()

    # Files that need BOM for Windows compatibility
    if suffix in {".csv", ".tsv", ".tab", ".txt", ".log"}:
        return "utf-8-sig"

    # Default: UTF-8 without BOM (safe for all other files)
    # This includes: .sh, .yaml, .json, .py, .js, .md, etc.
    return "utf-8"


def _display_path_for_model(abs_path: str) -> str:
    """给模型看的路径：工作区内 → 相对路径（``files/x.md``），工作区外 → 原样。

    答案侧的预览/下载链接由系统注入（采集器 + 会话资源读接口），模型只需要
    说出文件名。把服务器绝对路径抄进回答有两个害处：泄漏服务器目录结构，
    且前端正文链接没有 token，用户点了必 401。
    """
    try:
        workspace_dir = Path(get_current_workspace_dir() or WORKING_DIR)
        return Path(abs_path).relative_to(workspace_dir).as_posix()
    except Exception:
        return abs_path


def _ledger_record(abs_path: str, source: str) -> None:
    """Fire-and-forget file-ledger hook (never raises).

    Attributes the write to the current session context (username /
    session_id / agent_id). Failures are swallowed — the ledger must
    never break the message path.
    """
    try:
        from ...config.context import get_current_username
        from ...config.session_context import (
            get_current_agent_id,
            get_current_chat_id,
            get_current_session_id,
        )
        from ...foundation.file_ledger import record_file_event

        record_file_event(
            get_current_username(),
            abs_path,
            session_id=get_current_session_id(),
            chat_id=get_current_chat_id(),
            agent_id=get_current_agent_id(),
            source=source,
            # 登记**文件名含扩展名**。此前登记的是 stem（`a.txt` → `a`），
            # 前端一列名字里看不出文件类型，且无法从 title 反推真实文件。
            title=Path(abs_path).name or None,
        )
    except Exception:
        pass


@register_tool(
    name="read_file",
    description="读取文件内容。必需参数：file_path（文件路径）。可选参数：start_line、end_line（行号范围）。",
    category="builtin",
    tags=['file', 'read'],
)
async def read_file(  # pylint: disable=too-many-return-statements
    file_path: str,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
) -> ToolResponse:
    """读取文件内容。相对路径从 workspace/files/ 目录解析。

    ⚠️ 注意：参数名是 file_path（不是 path）

    Args:
        file_path: 文件路径（必需）。可以是绝对路径或相对路径。
        start_line: 起始行号（可选，1-based，包含）。默认读取全文。
        end_line: 结束行号（可选，1-based，包含）。默认读取全文。
    
    示例：
        读取全文：{"file_path": "/apps/ai/config.json"}
        读取部分：{"file_path": "report.txt", "start_line": 1, "end_line": 10}
    """

    # Convert start_line/end_line to int if they are strings
    if start_line is not None:
        try:
            start_line = int(start_line)
        except (ValueError, TypeError):
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=f"Error: start_line must be an integer, got {start_line!r}.",
                    ),
                ],
            )

    if end_line is not None:
        try:
            end_line = int(end_line)
        except (ValueError, TypeError):
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=f"Error: end_line must be an integer, got {end_line!r}.",
                    ),
                ],
            )

    file_path = _resolve_file_path(file_path)

    # ── WorkspaceGuard: path isolation check ──
    try:
        from ..security.workspace_guard import check_path
        check_path(file_path, operation="read")
    except ValueError as e:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"权限拒绝: {e}",
                ),
            ],
        )

    if not os.path.exists(file_path):
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: The file {file_path} does not exist.",
                ),
            ],
        )

    if not os.path.isfile(file_path):
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: The path {file_path} is not a file.",
                ),
            ],
        )

    try:
        content = await read_file_safe(file_path)
        all_lines = content.split("\n")
        total = len(all_lines)

        # Determine read range
        s = max(1, start_line if start_line is not None else 1)
        e = min(total, end_line if end_line is not None else total)

        if s > total:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=f"Error: start_line {s} exceeds file length ({total} lines).",
                    ),
                ],
            )

        if s > e:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=f"Error: start_line ({s}) > end_line ({e}).",
                    ),
                ],
            )

        # Extract selected lines
        selected_content = "\n".join(all_lines[s - 1 : e])

        # Apply smart truncation (consistent with shell output format)
        max_bytes = get_current_recent_max_bytes() or DEFAULT_MAX_BYTES
        text = truncate_text_output(
            selected_content,
            start_line=s,
            total_lines=total,
            file_path=file_path,
            max_bytes=max_bytes,
        )

        # Add continuation hint if partial read without truncation.
        # Use TRUNCATION_NOTICE_MARKER format so ToolResultCompactor can
        # re-truncate with the correct start_line when compacting old messages.
        if text == selected_content and e < total:
            content_bytes = len(text.encode("utf-8"))
            notice = (
                TRUNCATION_NOTICE_MARKER + f"\nThe output above was truncated."
                f"\nThe full content is saved to the file "
                f"and contains {total} lines in total."
                f"\nThis excerpt starts at line {s} and "
                f"covers the next {content_bytes} bytes."
                "\nIf the current content is not enough, "
                f"call `read_file` with file_path={file_path} "
                f"start_line={e + 1} to read more."
            )
            text = text + notice

        return ToolResponse(
            content=[TextBlock(type="text", text=text)],
        )

    except Exception as e:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: Read file failed due to \n{e}",
                ),
            ],
        )


@register_tool(
    name="write_file",
    description=(
        "写入文件内容。必需参数：file_path（文件路径）、content（文件内容）。"
        "file_path 只需给文件名（如 report.md）——产出目录由系统按当前会话"
        "自动规划，无需自行设计目录结构，也不要指定绝对路径。"
    ),
    category="builtin",
    tags=['file', 'write'],
)
async def write_file(
    file_path: str,
    content: str,
) -> ToolResponse:
    """写入文件内容。相对路径保存到 workspace/files/ 目录。

    ⚠️ 注意：参数名是 file_path（不是 path）

    Args:
        file_path: 文件路径（必需）。相对路径会保存到 workspace/files/ 目录。
        content: 文件内容（必需）。支持文本内容。
    
    示例：
        {"file_path": "report.txt", "content": "报告内容..."}
        {"file_path": "/apps/ai/data/output.txt", "content": "输出数据..."}
    """

    if not file_path:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text="Error: No `file_path` provided.",
                ),
            ],
        )

    file_path = await _resolve_write_path(file_path)

    # ── WorkspaceGuard: path isolation check ──
    try:
        from ..security.workspace_guard import check_path
        check_path(file_path, operation="write")
    except ValueError as e:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"权限拒绝: {e}",
                ),
            ],
        )

    encoding = _get_encoding_for_file(file_path)

    try:
        with open(file_path, "w", encoding=encoding) as file:
            file.write(content)

        _ledger_record(file_path, "write_file")

        _shown = _display_path_for_model(file_path)
        _hint = (
            "（回答里引用该文件请用这个相对路径，不要写绝对路径；"
            "预览与下载链接由系统提供）"
            if _shown != file_path
            else ""
        )
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Wrote {len(content)} bytes to {_shown}.{_hint}",
                ),
            ],
        )
    except Exception as e:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: Write file failed due to \n{e}",
                ),
            ],
        )


# pylint: disable=too-many-return-statements
@register_tool(
    name="edit_file",
    description="查找替换文件内容。必需参数：file_path（文件路径）、old_text（原文本）、new_text（新文本）。",
    category="builtin",
    tags=['file', 'edit'],
)
async def edit_file(
    file_path: str,
    old_text: str,
    new_text: str,
) -> ToolResponse:
    """查找替换文件内容。相对路径从 workspace/files/ 目录解析。

    ⚠️ 注意：参数名是 file_path（不是 path）

    Args:
        file_path: 文件路径（必需）。
        old_text: 要查找的原文本（必需）。精确匹配。
        new_text: 替换的新文本（必需）。
    
    示例：
        {"file_path": "config.txt", "old_text": "debug=false", "new_text": "debug=true"}
    """

    if not file_path:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text="Error: No `file_path` provided.",
                ),
            ],
        )

    resolved_path = await _resolve_write_path(file_path)

    # ── WorkspaceGuard: path isolation check ──
    try:
        from ..security.workspace_guard import check_path
        check_path(resolved_path, operation="write")
    except ValueError as e:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"权限拒绝: {e}",
                ),
            ],
        )

    if not os.path.exists(resolved_path):
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: The file {resolved_path} does not exist.",
                ),
            ],
        )

    if not os.path.isfile(resolved_path):
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: The path {resolved_path} is not a file.",
                ),
            ],
        )

    try:
        content = await read_file_safe(resolved_path)
    except Exception as e:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: Read file failed due to \n{e}",
                ),
            ],
        )

    if old_text not in content:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: The text to replace was not found in {file_path}.",
                ),
            ],
        )

    new_content = content.replace(old_text, new_text)
    write_response = await write_file(
        file_path=resolved_path,
        content=new_content,
    )

    if write_response.content and len(write_response.content) > 0:
        write_text = write_response.content[0].get("text", "")
        if write_text.startswith("Error:"):
            return write_response
        _ledger_record(resolved_path, "edit_file")

    return ToolResponse(
        content=[
            TextBlock(
                type="text",
                text=f"Successfully replaced text in {file_path}.",
            ),
        ],
    )


@register_tool(
    name="append_file",
    description="追加内容到文件末尾。必需参数：file_path（文件路径）、content（追加内容）。",
    category="builtin",
    tags=["file", "append"],
)
async def append_file(
    file_path: str,
    content: str,
) -> ToolResponse:
    """追加内容到文件末尾。相对路径从 workspace/files/ 目录解析。

    ⚠️ 注意：参数名是 file_path（不是 path）

    Args:
        file_path: 文件路径（必需）。
        content: 追加的内容（必需）。
    
    示例：
        {"file_path": "log.txt", "content": "新的日志条目\\n"}
    """

    if not file_path:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text="Error: No `file_path` provided.",
                ),
            ],
        )

    file_path = await _resolve_write_path(file_path)
    encoding = _get_encoding_for_file(file_path)

    try:
        with open(file_path, "a", encoding=encoding) as file:
            file.write(content)

        _ledger_record(file_path, "append_file")

        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Appended {len(content)} bytes to {file_path}.",
                ),
            ],
        )
    except Exception as e:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: Append file failed due to \n{e}",
                ),
            ],
        )
