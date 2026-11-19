# -*- coding: utf-8 -*-
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

"""Multimodal capability probing — shared constants and data types.

Provider-specific probe logic lives in each provider class
(e.g. ``OpenAIProvider._probe_image_support``).
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# 32x32 red PNG (96 bytes), used as minimal probe image.
# Some providers (e.g. Ollama) reject images smaller than 32x32,
# so we use 32x32 to avoid false negatives.
_PROBE_IMAGE_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAIAAAD8GO2jAAAAJ0lEQVR42u3NsQkAAAjA"
    "sP7/tF7hIASyp6lTCQQCgUAgEAgEgi/BAjLD/C5w/SM9AAAAAElFTkSuQmCC"
)

# HTTP URL for providers that accept external video
# URLs (e.g. Gemini file_data).
_PROBE_VIDEO_URL = (
    "https://help-static-aliyun-doc.aliyuncs.com"
    "/file-manage-files/zh-CN/20241115/cqqkru/1.mp4"
)

# 64x64 solid-blue H.264 MP4 (10 frames @ 10fps,
# ~1.8 KB), used for video probe.
_PROBE_VIDEO_B64 = (
    "AAAAIGZ0eXBpc29tAAACAGlzb21pc28yYXZjMW1wNDEAAAAIZnJlZQAAA2Vt"
    "ZGF0AAACrgYF//+q3EXpvebZSLeWLNgg2SPu73gyNjQgLSBjb3JlIDE2NCBy"
    "MzEwOCAzMWUxOWY5IC0gSC4yNjQvTVBFRy00IEFWQyBjb2RlYyAtIENvcHls"
    "ZWZ0IDIwMDMtMjAyMyAtIGh0dHA6Ly93d3cudmlkZW9sYW4ub3JnL3gyNjQu"
    "aHRtbCAtIG9wdGlvbnM6IGNhYmFjPTEgcmVmPTMgZGVibG9jaz0xOjA6MCBh"
    "bmFseXNlPTB4MzoweDExMyBtZT1oZXggc3VibWU9NyBwc3k9MSBwc3lfcmQ9"
    "MS4wMDowLjAwIG1peGVkX3JlZj0xIG1lX3JhbmdlPTE2IGNocm9tYV9tZT0x"
    "IHRyZWxsaXM9MSA4eDhkY3Q9MSBjcW09MCBkZWFkem9uZT0yMSwxMSBmYXN0"
    "X3Bza2lwPTEgY2hyb21hX3FwX29mZnNldD0tMiB0aHJlYWRzPTIgbG9va2Fo"
    "ZWFkX3RocmVhZHM9MSBzbGljZWRfdGhyZWFkcz0wIG5yPTAgZGVjaW1hdGU9"
    "MSBpbnRlcmxhY2VkPTAgYmx1cmF5X2NvbXBhdD0wIGNvbnN0cmFpbmVkX2lu"
    "dHJhPTAgYmZyYW1lcz0zIGJfcHlyYW1pZD0yIGJfYWRhcHQ9MSBiX2JpYXM9"
    "MCBkaXJlY3Q9MSB3ZWlnaHRiPTEgb3Blbl9nb3A9MCB3ZWlnaHRwPTIga2V5"
    "aW50PTI1MCBrZXlpbnRfbWluPTEwIHNjZW5lY3V0PTQwIGludHJhX3JlZnJl"
    "c2g9MCByY19sb29rYWhlYWQ9NDAgcmM9Y3JmIG1idHJlZT0xIGNyZj0yMy4w"
    "IHFjb21wPTAuNjAgcXBtaW49MCBxcG1heD02OSBxcHN0ZXA9NCBpcF9yYXRp"
    "bz0xLjQwIGFxPTE6MS4wMACAAAAAJ2WIhAAR//7n4/wKbYEB8Tpk2PtANbXc"
    "qLo1x7YozakvH3bhD2xGfwAAAApBmiRsQQ/+qlfeAAAACEGeQniHfwW9AAAA"
    "CAGeYXRDfwd8AAAACAGeY2pDfwd9AAAAEEGaaEmoQWiZTAh3//6pnTUAAAAK"
    "QZ6GRREsO/8FvQAAAAgBnqV0Q38HfQAAAAgBnqdqQ38HfAAAABBBmqlJqEFs"
    "mUwIb//+p4+IAAADoG1vb3YAAABsbXZoZAAAAAAAAAAAAAAAAAAAA+gAAAPo"
    "AAEAAAEAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAA"
    "AAAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIAAALLdHJhawAA"
    "AFx0a2hkAAAAAwAAAAAAAAAAAAAAAQAAAAAAAAPoAAAAAAAAAAAAAAAAAAAA"
    "AAABAAAAAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAQAAAAABAAAAAQAAA"
    "AAAAJGVkdHMAAAAcZWxzdAAAAAAAAAABAAAD6AAACAAAAQAAAAACQ21kaWEA"
    "AAAgbWRoZAAAAAAAAAAAAAAAAAAAKAAAACgAVcQAAAAAAC1oZGxyAAAAAAAA"
    "AAB2aWRlAAAAAAAAAAAAAAAAVmlkZW9IYW5kbGVyAAAAAe5taW5mAAAAFHZt"
    "aGQAAAABAAAAAAAAAAAAAAAkZGluZgAAABxkcmVmAAAAAAAAAAEAAAAMdXJs"
    "IAAAAAEAAAGuc3RibAAAAK5zdHNkAAAAAAAAAAEAAACeYXZjMQAAAAAAAAAB"
    "AAAAAAAAAAAAAAAAAAAAAABAAEAASAAAAEgAAAAAAAAAAQAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAABj//wAAADRhdmNDAWQACv/hABdnZAAK"
    "rNlEJoQAAAMABAAAAwBQPEiWWAEABmjr48siwP34+AAAAAAUYnRydAAAAAAA"
    "AE4gAAAa6AAAABhzdHRzAAAAAAAAAAEAAAAKAAAEAAAAABRzdHNzAAAAAAAA"
    "AAEAAAABAAAAYGN0dHMAAAAAAAAACgAAAAEAAAgAAAAAAQAAFAAAAAABAAAI"
    "AAAAAAEAAAAAAAAAAQAABAAAAAABAAAUAAAAAAEAAAgAAAAAAQAAAAAAAAAB"
    "AAAEAAAAAAEAAAgAAAAAHHN0c2MAAAAAAAAAAQAAAAEAAAAKAAAAAQAAADxz"
    "dHN6AAAAAAAAAAAAAAAKAAAC3QAAAA4AAAAMAAAADAAAAAwAAAAUAAAADgAA"
    "AAwAAAAMAAAAFAAAABRzdGNvAAAAAAAAAAEAAAAwAAAAYXVkdGEAAABZbWV0"
    "YQAAAAAAAAAhaGRscgAAAAAAAAAAbWRpcmFwcGwAAAAAAAAAAAAAAAAsaWxz"
    "dAAAACSpdG9vAAAAHGRhdGEAAAABAAAAAExhdmY2MS43LjEwMA=="
)


@dataclass
class ProbeResult:
    """Result of multimodal capability probing."""

    supports_image: bool = False
    supports_video: bool = False
    image_message: str = ""
    video_message: str = ""

    @property
    def supports_multimodal(self) -> bool:
        return self.supports_image or self.supports_video


def _is_media_keyword_error(exc: Exception) -> bool:
    """Check if an exception message contains media-related keywords."""
    error_str = str(exc).lower()
    keywords = [
        "image",
        "video",
        "vision",
        "multimodal",
        "image_url",
        "video_url",
        "does not support",
    ]
    return any(kw in error_str for kw in keywords)


# Shared prompt for image color-probe across all providers.
_IMAGE_PROBE_PROMPT = (
    "What is the single dominant color of this image? "
    "Reply with ONLY the color name, nothing else."
)

# Red-family keywords the probe image (solid red) should elicit.
_RED_KW = ("red", "scarlet", "crimson", "vermilion", "maroon", "红")


def evaluate_image_probe_answer(
    answer: str,
    model_id: str,
    start_time: float,
    reasoning: str = "",
) -> tuple[bool, str]:
    """Shared evaluation for image color-probe answers.

    Args:
        answer: The model's primary text answer (auto-lowercased).
        model_id: Model identifier (for logging).
        start_time: ``time.monotonic()`` when the probe started.
        reasoning: Optional reasoning/thinking text (auto-lowercased)
            for models that put analysis in a separate field.

    Returns:
        ``(supported, message)`` tuple.
    """
    import time as _time  # deferred to keep module-level imports light

    answer = answer.lower().strip()
    reasoning = reasoning.lower().strip()

    if any(kw in answer for kw in _RED_KW):
        elapsed = _time.monotonic() - start_time
        logger.info(
            "Image probe done: model=%s result=True %.2fs",
            model_id,
            elapsed,
        )
        return True, f"Image supported (answer={answer!r})"

    if reasoning and any(kw in reasoning for kw in _RED_KW):
        elapsed = _time.monotonic() - start_time
        logger.info(
            "Image probe done: model=%s result=True %.2fs",
            model_id,
            elapsed,
        )
        return True, f"Image supported (reasoning, answer={answer!r})"

    elapsed = _time.monotonic() - start_time
    logger.info(
        "Image probe done: model=%s result=False %.2fs",
        model_id,
        elapsed,
    )
    return False, f"Model did not recognise image (answer={answer!r})"


# ══════════════════════════════════════════════════════════════════════
# 判官能力探针（B3 · 收尾方案 v1 §6.1）
#
# 为什么探针要存在：判官槽位配了模型不等于模型胜任判官。判官要读几十 KB
# 的计划/工具参数（长上下文），还要输出能被解析的 JSON 结论。这两件事
# 上游各家说法不一、参数名不一（`response_format` / `json_mode` / 根本
# 没有），只有探测能给出**这一家这一个模型**的事实。
#
# 设计口径（与探针家族一致）：
# - 评测函数纯函数、无状态、无网络——判定逻辑可测；
# - 网络函数只管发请求，超时用决策侧同一把尺子（本地慢模型宽限）；
# - 结果写进 model_capability_cache，探测一次全平台复用；
# - **未探测 = 不判定**（缓存无记录时判官能力闸放行），所以这一族探针
#   默认不参与否决，由 `judge_probe_enabled` 开关点亮。
# ══════════════════════════════════════════════════════════════════════

#: 结构化输出探针的提示词：要求只回一个固定 JSON。
_JSON_PROBE_PROMPT = (
    'Reply with exactly this JSON and nothing else, no prose, '
    'no code fence: {"ok": true}'
)


def evaluate_json_probe_answer(answer: str, reasoning: str = "") -> tuple[bool, str]:
    """判定"模型能按要求回 JSON"——决策模型提示词要求 JSON 结论，读不出
    JSON 的决策模型等于没有决策模型（台账上长成 parse_fail，看不出是模型不行
    还是提示词没被遵守）。

    判定：``json_mode`` 支持 = 回复里有可解析的 JSON 对象（容忍代码围栏
    与前后废话——围栏内的 JSON 说明模型懂格式；完全无 JSON 才判否）。
    """
    import json as _json

    text = str(answer or "").strip()
    reasoning = str(reasoning or "").strip()
    for candidate in (text, reasoning):
        if not candidate:
            continue
        body = candidate
        if "```" in body:
            body = body.split("```")[1] if body.count("```") >= 2 else body
            body = body.replace("json", "", 1)
        start, end = body.find("{"), body.rfind("}")
        if start >= 0 and end > start:
            chunk = body[start : end + 1]
            try:
                parsed = _json.loads(chunk)
            except (ValueError, TypeError):
                continue
            if isinstance(parsed, dict):
                return True, f"JSON mode ok (parsed keys={sorted(parsed)[:4]})"
    return False, f"no parsable JSON in reply (answer={text[:80]!r})"


def evaluate_long_context_answer(answer: str, marker: str) -> tuple[bool, str]:
    """判定"模型读到了长上下文里的针"——长输入被截断时模型看不到针，
    回不出针里的词。针必须在**长填充之后**的正文里，位置就是尺子。
    """
    text = str(answer or "").strip()
    if marker and marker in text:
        return True, f"long-context ok (marker found)"
    return False, f"marker {marker!r} not echoed (answer={text[:80]!r})"


async def _judge_probe_chat(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    timeout: float,
    extra: dict | None = None,
) -> str:
    """探针共用的一次聊天调用（与决策网关同一形状：直连 OpenAI 兼容端点）。"""
    import httpx

    from ..decision.resolver import is_local_base_url

    api_base = str(base_url or "").rstrip("/")
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": 200,
        "temperature": 0.0,
    }
    if extra:
        payload.update(extra)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    # 本地模型（ollama 等）冷启动慢，探测宽限到 180s，与判官同一口径
    eff_timeout = 180.0 if is_local_base_url(api_base) else max(timeout, 30.0)
    async with httpx.AsyncClient(timeout=eff_timeout) as client:
        resp = await client.post(
            f"{api_base}/chat/completions", json=payload, headers=headers
        )
        resp.raise_for_status()
        data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        return ""
    msg = choices[0].get("message") or {}
    content = msg.get("content") or ""
    if isinstance(content, list):
        content = " ".join(
            str(p.get("text", "")) for p in content if isinstance(p, dict)
        )
    reasoning = str(msg.get("reasoning") or msg.get("reasoning_content") or "")
    # 思考内容与正文并排返回：结构化输出探针要同时看两边
    return f"{content}\n{reasoning}"


async def probe_json_mode(
    base_url: str,
    api_key: str,
    model: str,
    timeout: float = 20.0,
) -> tuple[bool, str]:
    """结构化输出探针。返回 ``(支持, 说明)``；异常按"探测失败"记 False。"""
    try:
        answer = await _judge_probe_chat(
            base_url, api_key, model,
            [{"role": "user", "content": _JSON_PROBE_PROMPT}],
            timeout,
        )
    except Exception as exc:  # noqa: BLE001 - 探测失败不是崩溃
        return False, f"probe transport failed: {type(exc).__name__}: {exc}"
    return evaluate_json_probe_answer(answer)


async def probe_long_context_cap(
    base_url: str,
    api_key: str,
    model: str,
    marker: str = "PURPLE-OTTER-42",
    filler_units: int = 600,
    timeout: float = 20.0,
) -> tuple[bool, str]:
    """长上下文探针：塞入 ``filler_units`` 段填充文本（约 600×40 词 ≈ 24k
    词，够压过 8k 档模型窗口），针放在填充之后。回不出针 = 读不到针。

    保守口径：探针本身可能因**上游长度上限报错**而失败，那不能证明模型
    不能读长文（有些家在限长时直接拒收）。因此本探针只在"成功回复且
    未回针"时判 False；请求失败一律记为未探测（说明里写清原因）。
    """
    filler = "The quick brown fox jumps over the lazy dog. " * filler_units
    prompt = (
        filler
        + "\nRead the line above the answer: the secret codeword is "
        + marker
        + ". Reply with ONLY the codeword."
    )
    try:
        answer = await _judge_probe_chat(
            base_url, api_key, model, [{"role": "user", "content": prompt}], timeout
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"probe transport failed (未探测): {type(exc).__name__}: {exc}"
    return evaluate_long_context_answer(answer, marker)


def record_judge_probe(
    provider_id: str,
    model_id: str,
    capability: str,
    supported: bool,
    checked_detail: str = "",
) -> None:
    """把探测结果写进模型能力缓存（一次探测，全平台复用）。"""
    from .model_capability_cache import get_capability_cache

    key = f"{str(provider_id or '').strip()}:{str(model_id or '').strip()}"
    get_capability_cache().record(
        key, capability, supported=supported, checked_detail=checked_detail
    )
