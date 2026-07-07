"""Parse ReMeLight ToolResponse into usable text snippets."""
import logging
from typing import Any

logger = logging.getLogger(__name__)


def parse_reme_response(response: Any) -> list[str]:
    """Extract text snippets from ReMeLight ToolResponse.

    ReMeLight's memory_search() returns ToolResponse whose content
    is a list of TextBlock dicts: [{"type": "text", "text": "..."}]

    The text contains formatted search results with file paths,
    line numbers, and content snippets.

    Args:
        response: ToolResponse object or dict-like with 'content' attribute

    Returns:
        List of non-empty text snippets extracted from the response
    """
    if response is None:
        return []

    snippets: list[str] = []

    # Get content blocks
    content = getattr(response, "content", None)
    if content is None and isinstance(response, dict):
        content = response.get("content", [])

    if not content:
        return []

    for block in content:
        # TextBlock is a dict with "type" and "text" keys
        if isinstance(block, dict):
            text = block.get("text", "")
        elif hasattr(block, "text"):
            text = block.text
        else:
            text = str(block)

        if text and len(text.strip()) > 10:
            snippets.append(text.strip())

    return snippets


def parse_reme_search_results(text: str) -> list[dict]:
    """Parse ReMeLight search result text into structured snippets.

    ReMeLight returns results in format:
        [file_path:line_number]
        content snippet...

    Args:
        text: Raw text from ToolResponse

    Returns:
        List of dicts with keys: path, line, content
    """
    import re

    results = []
    # Split by result markers (typically "[/path:line]" patterns)
    sections = re.split(r'\n(?=\[)', text)

    for section in sections:
        section = section.strip()
        if not section:
            continue

        # Try to extract path:line header
        header_match = re.match(r'\[([^\]]+)\]\s*\n?(.*)', section, re.DOTALL)
        if header_match:
            location = header_match.group(1)
            content = header_match.group(2).strip()

            # Parse path:line
            path_parts = location.rsplit(':', 1)
            path = path_parts[0]
            line = int(path_parts[1]) if len(path_parts) > 1 and path_parts[1].isdigit() else 0

            if content:
                results.append({
                    "path": path,
                    "line": line,
                    "content": content,
                })
        elif section:
            # No header, treat as raw content
            results.append({
                "path": "",
                "line": 0,
                "content": section,
            })

    return results
