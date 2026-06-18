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

"""Internationalization (i18n) module - multi-language support.

Provides:
- Translation management
- Language detection and switching
- Translation API for frontend
- Built-in translations for common UI strings
"""

import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

# Supported languages
SUPPORTED_LANGUAGES = {
    "en": {"name": "English", "native_name": "English"},
    "zh": {"name": "Chinese", "native_name": "中文"},
    "zh-CN": {"name": "Simplified Chinese", "native_name": "简体中文"},
    "zh-TW": {"name": "Traditional Chinese", "native_name": "繁體中文"},
}

# Built-in translations
BUILTIN_TRANSLATIONS: Dict[str, Dict[str, str]] = {
    # Common UI strings
    "common.welcome": {
        "en": "Welcome to CoApis",
        "zh": "欢迎使用 CoApis",
        "zh-CN": "欢迎使用 CoApis",
        "zh-TW": "歡迎使用 CoApis",
    },
    "common.settings": {
        "en": "Settings",
        "zh": "设置",
        "zh-CN": "设置",
        "zh-TW": "設定",
    },
    "common.save": {
        "en": "Save",
        "zh": "保存",
        "zh-CN": "保存",
        "zh-TW": "儲存",
    },
    "common.cancel": {
        "en": "Cancel",
        "zh": "取消",
        "zh-CN": "取消",
        "zh-TW": "取消",
    },
    "common.delete": {
        "en": "Delete",
        "zh": "删除",
        "zh-CN": "删除",
        "zh-TW": "刪除",
    },
    "common.search": {
        "en": "Search",
        "zh": "搜索",
        "zh-CN": "搜索",
        "zh-TW": "搜尋",
    },
    "common.loading": {
        "en": "Loading...",
        "zh": "加载中...",
        "zh-CN": "加载中...",
        "zh-TW": "載入中...",
    },
    "common.error": {
        "en": "Error",
        "zh": "错误",
        "zh-CN": "错误",
        "zh-TW": "錯誤",
    },
    "common.success": {
        "en": "Success",
        "zh": "成功",
        "zh-CN": "成功",
        "zh-TW": "成功",
    },
    # Navigation
    "nav.dashboard": {
        "en": "Dashboard",
        "zh": "仪表板",
        "zh-CN": "仪表板",
        "zh-TW": "儀表板",
    },
    "nav.chat": {
        "en": "Chat",
        "zh": "聊天",
        "zh-CN": "聊天",
        "zh-TW": "聊天",
    },
    "nav.skills": {
        "en": "Skills",
        "zh": "技能",
        "zh-CN": "技能",
        "zh-TW": "技能",
    },
    "nav.files": {
        "en": "Files",
        "zh": "文件",
        "zh-CN": "文件",
        "zh-TW": "檔案",
    },
    "nav.settings": {
        "en": "Settings",
        "zh": "设置",
        "zh-CN": "设置",
        "zh-TW": "設定",
    },
    # Messages
    "msg.welcome": {
        "en": "Hello! How can I help you today?",
        "zh": "你好！今天我能帮你什么？",
        "zh-CN": "你好！今天我能帮你什么？",
        "zh-TW": "你好！今天我能幫你什麼？",
    },
    "msg.no_results": {
        "en": "No results found",
        "zh": "未找到结果",
        "zh-CN": "未找到结果",
        "zh-TW": "未找到結果",
    },
    "msg.unauthorized": {
        "en": "Unauthorized access",
        "zh": "未授权访问",
        "zh-CN": "未授权访问",
        "zh-TW": "未授權訪問",
    },
}


class I18nManager:
    """Manages translations and language preferences."""

    def __init__(self):
        self._translations = dict(BUILTIN_TRANSLATIONS)
        self._user_preferences: Dict[str, str] = {}  # user_id -> language

    def translate(
        self,
        key: str,
        lang: str = "en",
        **kwargs,
    ) -> str:
        """Translate a key to specified language.

        Args:
            key: Translation key (e.g., "common.welcome")
            lang: Target language code
            **kwargs: Variables to interpolate (e.g., name="John")

        Returns:
            Translated string
        """
        # Fallback to English if language not supported
        if lang not in SUPPORTED_LANGUAGES:
            lang = "en"

        # Get translation
        trans = self._translations.get(key, {})
        result = trans.get(lang, trans.get("en", key))

        # Interpolate variables
        if kwargs:
            try:
                result = result.format(**kwargs)
            except (KeyError, IndexError, ValueError):
                pass  # Keep original if interpolation fails

        return result

    def get_available_languages(self) -> Dict[str, Dict[str, str]]:
        """Get list of supported languages."""
        return SUPPORTED_LANGUAGES

    def get_user_language(self, user_id: str) -> str:
        """Get user's preferred language."""
        return self._user_preferences.get(user_id, "en")

    def set_user_language(self, user_id: str, lang: str):
        """Set user's preferred language."""
        if lang not in SUPPORTED_LANGUAGES:
            raise ValueError(f"Unsupported language: {lang}")
        self._user_preferences[user_id] = lang

    def add_translation(self, key: str, translations: Dict[str, str]):
        """Add or update a translation."""
        self._translations[key] = translations

    def get_all_translations(self, lang: str = "en") -> Dict[str, str]:
        """Get all translations for a language."""
        result = {}
        for key, trans in self._translations.items():
            result[key] = trans.get(lang, trans.get("en", key))
        return result


# Global i18n manager
i18n_manager = I18nManager()


# ---- API Router ----

router = APIRouter(prefix="/api/i18n", tags=["Internationalization"])


@router.get("/languages")
async def get_languages():
    """Get list of supported languages."""
    return i18n_manager.get_available_languages()


@router.get("/translations")
async def get_translations(lang: str = "en"):
    """Get all translations for a language."""
    if lang not in SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported language: {lang}. Supported: {', '.join(SUPPORTED_LANGUAGES.keys())}",
        )
    return i18n_manager.get_all_translations(lang)


@router.get("/translate")
async def translate(key: str, lang: str = "en"):
    """Translate a single key."""
    return {
        "key": key,
        "lang": lang,
        "translation": i18n_manager.translate(key, lang),
    }


@router.post("/language")
async def set_language(request: Request):
    """Set user's preferred language."""
    user_info = getattr(request.state, "user_info", None)
    if not user_info:
        raise HTTPException(status_code=401, detail="Not authenticated")

    body = await request.json()
    lang = body.get("language", "en")

    try:
        i18n_manager.set_user_language(
            user_info.get("username") or user_info.get("sub", "anonymous"),
            lang,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"ok": True, "language": lang}


@router.get("/language")
async def get_language(request: Request):
    """Get user's preferred language."""
    user_info = getattr(request.state, "user_info", None)
    if not user_info:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user_id = user_info.get("username") or user_info.get("sub", "anonymous")
    lang = i18n_manager.get_user_language(user_id)

    return {"language": lang}


@router.post("/translations")
async def add_translation(request: Request):
    """Add or update a translation (admin only)."""
    # TODO: Add admin role check
    body = await request.json()
    key = body.get("key")
    translations = body.get("translations")

    if not key or not translations:
        raise HTTPException(status_code=400, detail="key and translations are required")

    i18n_manager.add_translation(key, translations)
    return {"ok": True}
