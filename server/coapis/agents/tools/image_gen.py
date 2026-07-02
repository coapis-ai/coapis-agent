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

"""Image generation tool — text-to-image via FAL API or local fallback."""

from __future__ import annotations

import base64
import json
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from .registry import register_tool

logger = logging.getLogger(__name__)

# Supported image sizes
_SIZES = {
    "1024x1024": (1024, 1024),
    "1024x1792": (1024, 1792),
    "1792x1024": (1792, 1024),
    "512x512": (512, 512),
    "768x768": (768, 768),
}


def _get_output_dir() -> Path:
    """Get the output directory for generated images."""
    try:
        from ...config.context import get_current_workspace_dir
        ws = get_current_workspace_dir()
        if ws:
            out = Path(ws) / "files"
        else:
            out = Path.cwd() / "files"
    except Exception:
        out = Path.cwd() / "files"
    out.mkdir(parents=True, exist_ok=True)
    return out


async def _fal_generate(prompt: str, width: int, height: int) -> dict[str, Any]:
    """Try FAL API for image generation."""
    api_key = os.environ.get("FAL_KEY") or os.environ.get("FAL_API_KEY")
    if not api_key:
        return {"error": "FAL API key 未配置（设置 FAL_KEY 环境变量）"}

    try:
        import httpx
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                "https://fal.run/fal-ai/flux/schnell",
                headers={
                    "Authorization": f"Key {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "prompt": prompt,
                    "image_size": {"width": width, "height": height},
                    "num_images": 1,
                },
            )
            if resp.status_code != 200:
                return {"error": f"FAL API 返回 {resp.status_code}: {resp.text[:200]}"}
            data = resp.json()
            images = data.get("images", [])
            if not images:
                return {"error": "FAL API 未返回图像"}
            return {"url": images[0].get("url", ""), "backend": "fal"}
    except ImportError:
        return {"error": "httpx 未安装，无法调用 FAL API（pip install httpx）"}
    except Exception as e:
        return {"error": f"FAL API 调用失败: {e}"}


async def _local_fallback(prompt: str, width: int, height: int) -> dict[str, Any]:
    """Local fallback: generate a placeholder SVG."""
    out_dir = _get_output_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"gen_{timestamp}.svg"
    filepath = out_dir / filename

    # Generate a simple SVG with the prompt text
    escaped = prompt.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Wrap text lines at ~30 chars
    words = escaped.split()
    lines = []
    current_line = []
    for word in words:
        current_line.append(word)
        if len(" ".join(current_line)) > 30:
            lines.append(" ".join(current_line))
            current_line = []
    if current_line:
        lines.append(" ".join(current_line))

    text_blocks = []
    for i, line in enumerate(lines[:8]):
        y = 100 + i * 30
        text_blocks.append(
            f'<text x="50%" y="{y}" text-anchor="middle" '
            f'font-family="Arial" font-size="16" fill="#333">{line}</text>'
        )

    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="100%" height="100%" fill="#f0f0f0"/>
  <rect x="20" y="20" width="{width-40}" height="{height-40}" rx="10" fill="#e0e0e0" stroke="#ccc"/>
  <text x="50%" y="60" text-anchor="middle" font-family="Arial" font-size="20" font-weight="bold" fill="#666">🎨 Placeholder</text>
  <text x="50%" y="85" text-anchor="middle" font-family="Arial" font-size="12" fill="#999">FAL API 未配置</text>
  {chr(10).join(text_blocks)}
</svg>"""

    filepath.write_text(svg, encoding="utf-8")
    return {
        "path": str(filepath),
        "filename": filename,
        "backend": "local_placeholder",
        "note": "FAL API 未配置，生成占位 SVG。配置 FAL_KEY 环境变量可获取真实图像。",
    }


async def image_gen(
    prompt: str = "",
    size: str = "1024x1024",
    style: str = "photographic",
) -> dict[str, Any]:
    """文本生成图像。

    Args:
        prompt: 图像描述（英文效果最佳）
        size: 图像尺寸，可选 1024x1024/1024x1792/1792x1024/512x512/768x768
        style: 风格提示（photographic/illustration/anime/watercolor）

    Returns:
        生成结果（path/url/backend）
    """
    if not prompt.strip():
        return {"error": "prompt 不能为空"}

    # Parse size
    if size not in _SIZES:
        size = "1024x1024"
    width, height = _SIZES[size]

    # Try FAL API first
    result = await _fal_generate(prompt.strip(), width, height)
    if "url" in result:
        # Download and save
        try:
            import httpx
            out_dir = _get_output_dir()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            ext = "png"
            filename = f"gen_{timestamp}.{ext}"
            filepath = out_dir / filename

            async with httpx.AsyncClient(timeout=60) as client:
                img_resp = await client.get(result["url"])
                if img_resp.status_code == 200:
                    filepath.write_bytes(img_resp.content)
                    result["path"] = str(filepath)
                    result["filename"] = filename
                    del result["url"]
                else:
                    return {"error": f"图像下载失败: HTTP {img_resp.status_code}"}
        except Exception as e:
            return {"error": f"图像下载失败: {e}"}

    if "error" in result:
        # Fallback to local placeholder
        fallback = await _local_fallback(prompt.strip(), width, height)
        fallback["fal_error"] = result["error"]
        return fallback

    return result
