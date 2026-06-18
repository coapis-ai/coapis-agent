# -*- coding: utf-8 -*-
# Copyright 2026 以太吃虾 & CoApis Contributors
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

"""Voice transcription settings routes (CoApis console compatible).

Handles audio mode, transcription provider type, provider selection,
and local Whisper status. These are persisted in DATA_DIR/config/voice.json.
"""

import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel

from ....constant import DATA_DIR

logger = logging.getLogger(__name__)

router = APIRouter(tags=["voice-transcription"])

# Persist voice config to DATA_DIR/config/voice.json
VOICE_CONFIG_PATH = DATA_DIR / "config" / "voice.json"


class VoiceConfig(BaseModel):
    audio_mode: str = "auto"
    transcription_provider_type: str = "disabled"
    transcription_provider_id: str = ""


def _load_voice_config() -> VoiceConfig:
    """Load voice config from file, or return defaults."""
    if VOICE_CONFIG_PATH.exists():
        try:
            data = json.loads(VOICE_CONFIG_PATH.read_text())
            return VoiceConfig(**data)
        except Exception as e:
            logger.warning(f"Failed to load voice config: {e}, using defaults")
    return VoiceConfig()


def _save_voice_config(cfg: VoiceConfig) -> None:
    """Save voice config to file."""
    VOICE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    VOICE_CONFIG_PATH.write_text(json.dumps(cfg.model_dump(), indent=2, ensure_ascii=False))


def _check_ffmpeg_installed() -> bool:
    """Check if ffmpeg is installed in container."""
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _check_whisper_installed() -> bool:
    """Check if openai-whisper is installed."""
    try:
        import whisper  # noqa: F401
        return True
    except ImportError:
        return False


# ── Audio Mode ──────────────────────────────────────────────────────

@router.get("/workspace/audio-mode")
async def get_audio_mode(request: Request) -> Dict[str, Any]:
    """Get audio mode setting."""
    cfg = _load_voice_config()
    return {"audio_mode": cfg.audio_mode}


@router.put("/workspace/audio-mode")
async def update_audio_mode(
    request: Request,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Update audio mode setting."""
    raw = payload.get("audio_mode")
    audio_mode = (str(raw) if raw is not None else "").strip().lower()
    valid = {"auto", "native", "off"}
    if audio_mode not in valid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid audio_mode '{audio_mode}'. Must be one of: {', '.join(sorted(valid))}",
        )
    cfg = _load_voice_config()
    cfg.audio_mode = audio_mode
    _save_voice_config(cfg)
    return {"audio_mode": audio_mode}


# ── Transcription Provider Type ─────────────────────────────────────

@router.get("/workspace/transcription-provider-type")
async def get_transcription_provider_type(request: Request) -> Dict[str, Any]:
    """Get transcription provider type setting."""
    cfg = _load_voice_config()
    return {"transcription_provider_type": cfg.transcription_provider_type}


@router.put("/workspace/transcription-provider-type")
async def update_transcription_provider_type(
    request: Request,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Set transcription provider type."""
    raw = payload.get("transcription_provider_type")
    provider_type = (str(raw) if raw is not None else "").strip().lower()
    valid = {"disabled", "whisper_api", "local_whisper"}
    if provider_type not in valid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid transcription_provider_type '{provider_type}'. Must be one of: {', '.join(sorted(valid))}",
        )
    cfg = _load_voice_config()
    cfg.transcription_provider_type = provider_type
    _save_voice_config(cfg)
    return {"transcription_provider_type": provider_type}


# ── Transcription Providers List ────────────────────────────────────

@router.get("/workspace/transcription-providers")
async def get_transcription_providers(request: Request) -> Dict[str, Any]:
    """List transcription-capable providers and configured selection."""
    cfg = _load_voice_config()
    # Build provider list from providers.json
    providers = _list_transcription_providers()
    return {
        "providers": providers,
        "configured_provider_id": cfg.transcription_provider_id,
    }


@router.get("/workspace/transcription-provider")
async def get_transcription_provider(request: Request) -> Dict[str, Any]:
    """Get configured transcription provider."""
    cfg = _load_voice_config()
    return {"provider_id": cfg.transcription_provider_id}


@router.put("/workspace/transcription-provider")
async def update_transcription_provider(
    request: Request,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Set transcription provider."""
    provider_id = (payload.get("provider_id") or "").strip()
    cfg = _load_voice_config()
    cfg.transcription_provider_id = provider_id
    _save_voice_config(cfg)
    return {"provider_id": provider_id}


# ── Local Whisper Status ────────────────────────────────────────────

@router.get("/workspace/local-whisper-status")
async def get_local_whisper_status(request: Request) -> Dict[str, Any]:
    """Get local Whisper installation status."""
    ffmpeg_ok = _check_ffmpeg_installed()
    whisper_ok = _check_whisper_installed()
    return {
        "available": ffmpeg_ok and whisper_ok,
        "ffmpeg_installed": ffmpeg_ok,
        "whisper_installed": whisper_ok,
    }


# ── Helpers ─────────────────────────────────────────────────────────

def _list_transcription_providers() -> List[Dict[str, Any]]:
    """List providers that support transcription (Whisper API compatible)."""
    from ....constant import WORKING_DIR

    providers_path = WORKING_DIR / "config" / "providers.json"
    if not providers_path.exists():
        return []

    try:
        data = json.loads(providers_path.read_text())
    except Exception:
        return []

    result = []
    for pid, pconf in data.items():
        # A provider supports transcription if it has a transcription_url or is a known Whisper-compatible endpoint
        base_url = (pconf.get("api_base") or "").strip()
        name = pconf.get("name") or pconf.get("display_name") or pid
        # Check if this provider has transcription capability
        has_transcription = (
            "transcription" in (pconf.get("type") or "").lower()
            or "whisper" in pid.lower()
            or "transcription_url" in pconf
        )
        if has_transcription or base_url:
            result.append({
                "id": pid,
                "name": name,
                "available": bool(base_url),
            })
    return result
