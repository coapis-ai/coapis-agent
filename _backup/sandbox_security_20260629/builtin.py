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

"""Built-in tools - Core tools available to all agents.

Includes: file_read, file_write, shell_execute, memory_search, etc.
"""

import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Any

from .registry import ToolRegistry

logger = logging.getLogger(__name__)


def register_builtin_tools(registry: ToolRegistry):
    """Register all built-in tools.
    
    Note: Call with await (e.g., await register_builtin_tools(registry))
    """
    import asyncio
    
    # These are sync functions that wrap async operations
    registry._tools["file_read"] = type(registry._tools.get("file_read", registry._tools.get("dummy")) or type('ToolInfo', (), {
        'name': 'file_read', 'description': 'Read a file and return its contents',
        'func': file_read, 'parameters': {
            "path": {"description": "File path to read", "type": "string"},
            "start_line": {"description": "Start line (1-based)", "type": "integer"},
            "end_line": {"description": "End line (1-based)", "type": "integer"},
        }, 'allowed': True, 'tags': [], 'is_async': True
    })())
    
    # Simple approach: just set them directly
    from .registry import ToolInfo
    registry._tools["file_read"] = ToolInfo(name="file_read", description="Read a file and return its contents",
        func=file_read, parameters={
            "path": {"description": "File path to read", "type": "string"},
            "start_line": {"description": "Start line (1-based)", "type": "integer"},
            "end_line": {"description": "End line (1-based)", "type": "integer"},
        })
    registry._tools["file_write"] = ToolInfo(name="file_write", description="Write content to a file",
        func=file_write, parameters={
            "path": {"description": "File path to write", "type": "string"},
            "content": {"description": "Content to write", "type": "string"},
        })
    registry._tools["shell_execute"] = ToolInfo(name="shell_execute", description="Execute a shell command and return output",
        func=shell_execute, parameters={
            "command": {"description": "Shell command to execute", "type": "string"},
            "timeout": {"description": "Timeout in seconds", "type": "number"},
        })
    registry._tools["memory_search"] = ToolInfo(name="memory_search", description="Search memory files for relevant content",
        func=memory_search, parameters={
            "query": {"description": "Search query", "type": "string"},
            "max_results": {"description": "Max results to return", "type": "integer"},
        })
    registry._tools["list_files"] = ToolInfo(name="list_files", description="List files in a directory",
        func=list_files, parameters={
            "path": {"description": "Directory path", "type": "string"},
            "recursive": {"description": "List recursively", "type": "boolean"},
        })

    logger.info("Registered built-in tools")


async def file_read(path: str, start_line: int = None, end_line: int = None) -> str:
    """Read a file and return its contents.

    Args:
        path: Path to the file to read (relative or absolute).
        start_line: First line to read (1-based, inclusive). Omit to start from beginning.
        end_line: Last line to read (1-based, inclusive). Omit to read to end.

    Returns:
        File content as string, or error message if file not found.
    """
    filepath = Path(path)
    if not filepath.exists():
        return f"File not found: {path}"

    content = filepath.read_text()
    if start_line or end_line:
        lines = content.split("\n")
        start = (start_line or 1) - 1
        end = end_line or len(lines)
        content = "\n".join(lines[start:end])

    return content


async def file_write(path: str, content: str) -> str:
    """Write content to a file, creating parent directories if needed.

    Args:
        path: Path to the file to write (relative or absolute).
        content: The text content to write to the file.

    Returns:
        Confirmation message with byte count and path.
    """
    filepath = Path(path)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content)
    return f"Written {len(content)} bytes to {path}"


async def shell_execute(command: str, timeout: float = 60.0) -> str:
    """Execute a shell command and return its output.

    Args:
        command: Shell command string to execute (e.g. 'ls -la', 'python3 script.py').
        timeout: Maximum time in seconds before the command is killed. Default 60s.

    Returns:
        Combined stdout+stderr output, or error/status message.
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout or ""
        if result.stderr:
            output += f"\nSTDERR: {result.stderr}"
        return output or "Command executed successfully"
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s"
    except Exception as e:
        return f"Error: {e}"


async def memory_search(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """Search memory files for relevant past notes and context.

    Args:
        query: Search query to find in memory files (semantic or keyword match).
        max_results: Maximum number of results to return. Default 5.

    Returns:
        List of memory search results with file path, line number, and content.
    """
    # This will be connected to MemoryManager in workspace
    return [{"query": query, "results": []}]


async def list_files(path: str, recursive: bool = False) -> List[str]:
    """List files in a directory."""
    filepath = Path(path)
    if not filepath.exists():
        return []

    if recursive:
        return [str(p) for p in filepath.rglob("*") if p.is_file()]
    else:
        return [str(p) for p in filepath.iterdir() if p.is_file()]
