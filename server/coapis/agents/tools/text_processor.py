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

"""Text processor — encoding/decoding, text statistics, regex replacement.

Provides structured text manipulation without shell commands.
"""

from __future__ import annotations

import base64
import html
import json
import logging
import re
import urllib.parse
from collections import Counter
from typing import Any

from .registry import register_tool

logger = logging.getLogger(__name__)


def _text_stats(text: str) -> dict[str, Any]:
    """Compute text statistics."""
    lines = text.split("\n")
    words = text.split()
    chars = len(text)
    non_space = len(text.replace(" ", "").replace("\n", "").replace("\t", ""))

    # Character frequency
    char_freq = Counter(text.lower())
    top_chars = [{"char": c, "count": n} for c, n in char_freq.most_common(10)]

    return {
        "characters": chars,
        "characters_no_space": non_space,
        "lines": len(lines),
        "words": len(words),
        "avg_word_length": round(sum(len(w) for w in words) / max(len(words), 1), 2),
        "avg_line_length": round(sum(len(l) for l in lines) / max(len(lines), 1), 2),
        "top_characters": top_chars,
    }


async def text_processor(
    action: str = "stats",
    text: str = "",
    pattern: str = "",
    replacement: str = "",
    encoding: str = "utf-8",
    format: str = "",
) -> dict[str, Any]:
    """文本处理。

    Args:
        action: 操作类型 (stats/encode/decode/replace/transform/extract)
        text: 输入文本
        pattern: 正则模式（replace/extract 时使用）
        replacement: 替换文本（replace 时使用）
        encoding: 编码类型（base64_encode/base64_decode 时使用）
        format: 格式类型（encode/decode 时指定：base64/url/html/hex）

    Returns:
        处理结果
    """
    if not text.strip() and action not in ("stats",):
        return {"error": "text 不能为空"}

    if action == "stats":
        result = _text_stats(text)
        return {"action": "stats", **result}

    elif action == "encode":
        fmt = format.strip().lower()
        if fmt == "base64":
            encoded = base64.b64encode(text.encode(encoding)).decode("ascii")
            return {"action": "encode", "format": "base64", "result": encoded, "length": len(encoded)}
        elif fmt == "url":
            encoded = urllib.parse.quote(text, safe="")
            return {"action": "encode", "format": "url", "result": encoded, "length": len(encoded)}
        elif fmt == "html":
            encoded = html.escape(text)
            return {"action": "encode", "format": "html", "result": encoded, "length": len(encoded)}
        elif fmt == "hex":
            encoded = text.encode(encoding).hex()
            return {"action": "encode", "format": "hex", "result": encoded, "length": len(encoded)}
        else:
            return {"error": f"不支持的格式: {format}，支持 base64/url/html/hex"}

    elif action == "decode":
        fmt = format.strip().lower()
        try:
            if fmt == "base64":
                decoded = base64.b64decode(text.encode("ascii")).decode(encoding)
                return {"action": "decode", "format": "base64", "result": decoded, "length": len(decoded)}
            elif fmt == "url":
                decoded = urllib.parse.unquote(text)
                return {"action": "decode", "format": "url", "result": decoded, "length": len(decoded)}
            elif fmt == "html":
                decoded = html.unescape(text)
                return {"action": "decode", "format": "html", "result": decoded, "length": len(decoded)}
            elif fmt == "hex":
                decoded = bytes.fromhex(text).decode(encoding)
                return {"action": "decode", "format": "hex", "result": decoded, "length": len(decoded)}
            else:
                return {"error": f"不支持的格式: {format}，支持 base64/url/html/hex"}
        except Exception as e:
            return {"error": f"解码失败: {e}"}

    elif action == "replace":
        if not pattern.strip():
            return {"error": "pattern 不能为空"}
        count = 0
        def replacer(m):
            nonlocal count
            count += 1
            return replacement
        result = re.sub(pattern, replacer, text)
        return {
            "action": "replace",
            "pattern": pattern,
            "replacement": replacement,
            "replacements": count,
            "result": result,
            "length": len(result),
        }

    elif action == "transform":
        fmt = format.strip().lower()
        if fmt == "upper":
            return {"action": "transform", "format": "upper", "result": text.upper()}
        elif fmt == "lower":
            return {"action": "transform", "format": "lower", "result": text.lower()}
        elif fmt == "title":
            return {"action": "transform", "format": "title", "result": text.title()}
        elif fmt == "strip":
            return {"action": "transform", "format": "strip", "result": text.strip()}
        elif fmt == "reverse":
            return {"action": "transform", "format": "reverse", "result": text[::-1]}
        elif fmt == "capitalize":
            return {"action": "transform", "format": "capitalize", "result": text.capitalize()}
        elif fmt == "swapcase":
            return {"action": "transform", "format": "swapcase", "result": text.swapcase()}
        else:
            return {"error": f"不支持的变换: {format}，支持 upper/lower/title/strip/reverse/capitalize/swapcase"}

    elif action == "extract":
        if not pattern.strip():
            return {"error": "pattern 不能为空"}
        matches = re.findall(pattern, text)
        return {
            "action": "extract",
            "pattern": pattern,
            "matches": matches,
            "count": len(matches),
        }

    else:
        return {"error": f"未知操作: {action}，支持 stats/encode/decode/replace/transform/extract"}
