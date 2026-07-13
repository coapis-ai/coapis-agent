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

"""Setup and initialization utilities for agent configuration.

This module handles copying markdown configuration files to
the working directory.
"""
import logging
import shutil
from pathlib import Path

from ...constant import SUPPORTED_AGENT_LANGUAGES

logger = logging.getLogger(__name__)

_TEMPLATE_OVERRIDE_FILENAMES = {
    "AGENTS.md",
    "BOOTSTRAP.md",
    "PROFILE.md",
    "SOUL.md",
}


def normalize_agent_language(language: str) -> str:
    """Map *language* to a supported agent language"""
    if language in SUPPORTED_AGENT_LANGUAGES:
        return language
    return "en"


def detect_system_language() -> str:
    """Detect system language and map to supported agent language.
    
    Detection order:
    1. LANG environment variable (Linux/macOS)
    2. LC_ALL environment variable
    3. LANGUAGE environment variable
    4. Default to 'en'
    
    Returns:
        Language code in SUPPORTED_AGENT_LANGUAGES (e.g., 'en', 'zh', 'ru')
    """
    import os
    
    # Map locale codes to agent language codes
    LANG_MAP = {
        # Chinese variants
        "zh": "zh",
        "zh_cn": "zh",
        "zh_cn.utf-8": "zh",
        "zh_tw": "zh",
        "zh_hk": "zh",
        "zh_sg": "zh",
        # English variants
        "en": "en",
        "en_us": "en",
        "en_us.utf-8": "en",
        "en_gb": "en",
        "en_au": "en",
        "en_ca": "en",
        # Russian variants
        "ru": "ru",
        "ru_ru": "ru",
        "ru_ru.utf-8": "ru",
    }
    
    # Try environment variables
    # Priority: LC_ALL > LANGUAGE > LANG (following GNU gettext convention)
    for env_var in ["LC_ALL", "LANGUAGE", "LANG"]:
        lang_env = os.environ.get(env_var, "").lower().strip()
        if lang_env:
            # Extract language code (e.g., "zh_CN.UTF-8" -> "zh")
            # Format: language[_territory][.codeset] or language[:territory] (LANGUAGE)
            # LANGUAGE can be "zh_CN:en_US" format, take first part
            lang_env = lang_env.split(":")[0]  # Handle LANGUAGE format
            lang_code = lang_env.split("_")[0].split(".")[0]
            
            # Try exact match first
            if lang_env in LANG_MAP:
                detected = LANG_MAP[lang_env]
                if detected in SUPPORTED_AGENT_LANGUAGES:
                    return detected
            
            # Try language code match
            if lang_code in LANG_MAP:
                detected = LANG_MAP[lang_code]
                if detected in SUPPORTED_AGENT_LANGUAGES:
                    return detected
    
    # Default to English
    return "en"


def copy_md_files(
    language: str,
    skip_existing: bool = False,
    workspace_dir: Path | None = None,
    exclude_filenames: set[str] | None = None,
) -> list[str]:
    """Copy md files from agents/md_files to working directory.

    Args:
        language: Language code (e.g. 'en', 'zh')
        skip_existing: If True, skip files that already exist in working dir.
        workspace_dir: Target workspace directory. If None, uses WORKING_DIR.
        exclude_filenames: File names to skip while copying.

    Returns:
        List of copied file names.
    """
    from ...constant import WORKING_DIR

    # Use provided workspace_dir or default to WORKING_DIR
    target_dir = workspace_dir if workspace_dir is not None else WORKING_DIR

    # Get md_files directory path with language subdirectory
    # Updated to use data/packs/{language}/templates/user_level/
    from ...constant import DATA_PACKS_DIR
    md_files_dir = DATA_PACKS_DIR / language / "templates" / "user_level"

    if not md_files_dir.exists():
        logger.warning(
            "MD files directory not found: %s, falling back to 'en'",
            md_files_dir,
        )
        # Fallback to English if specified language not found
        md_files_dir = DATA_PACKS_DIR / "en" / "templates" / "user_level"
        if not md_files_dir.exists():
            logger.error("Default 'en' md files not found either")
            return []

    # Ensure target directory exists
    target_dir.mkdir(parents=True, exist_ok=True)

    # Copy all .md files to target directory
    copied_files: list[str] = []
    for md_file in md_files_dir.glob("*.md"):
        if exclude_filenames and md_file.name in exclude_filenames:
            continue
        target_file = target_dir / md_file.name
        if skip_existing and target_file.exists():
            logger.debug("Skipped existing md file: %s", md_file.name)
            continue
        try:
            shutil.copy2(md_file, target_file)
            logger.debug("Copied md file: %s", md_file.name)
            copied_files.append(md_file.name)
        except Exception as e:
            logger.error(
                "Failed to copy md file '%s': %s",
                md_file.name,
                e,
            )

    if copied_files:
        logger.debug(
            "Copied %d md file(s) [%s] to %s",
            len(copied_files),
            language,
            target_dir,
        )

    return copied_files


def _resolve_md_lang_dir(agents_root: Path, language: str) -> Path:
    """Return ``data/packs/{language}/templates/user_level``, falling back to ``en`` if missing."""
    from ...constant import DATA_PACKS_DIR
    md_lang_dir = DATA_PACKS_DIR / language / "templates" / "user_level"
    if not md_lang_dir.exists():
        logger.warning(
            "MD lang dir not found: %s, falling back to 'en'",
            md_lang_dir,
        )
        md_lang_dir = DATA_PACKS_DIR / "en" / "templates" / "user_level"
    return md_lang_dir


def _template_fallback_language_order(language: str) -> list[str]:
    ordered: list[str] = []
    for lang_opt in (language, "en", "zh", "ru"):
        if lang_opt not in ordered:
            ordered.append(lang_opt)
    return ordered


def _copy_template_md_files(
    template_root: Path,
    fallback_langs: list[str],
    workspace_dir: Path,
    only_if_missing: bool,
) -> list[str]:
    candidate_names: list[str] = []
    seen_names: set[str] = set()

    for lang_opt in fallback_langs:
        lang_dir = template_root / lang_opt
        if not lang_dir.exists():
            continue
        for template_file in lang_dir.glob("*.md"):
            if template_file.name in seen_names:
                continue
            seen_names.add(template_file.name)
            candidate_names.append(template_file.name)

    copied: list[str] = []
    for filename in candidate_names:
        dst_p = workspace_dir / filename
        if only_if_missing and dst_p.exists():
            continue
        source_p = None
        for lang_opt in fallback_langs:
            cand = template_root / lang_opt / filename
            if cand.exists():
                source_p = cand
                break
        if source_p is None:
            logger.warning(
                "Workspace template missing for %s (langs tried: %s)",
                filename,
                fallback_langs,
            )
            continue
        try:
            shutil.copy2(source_p, dst_p)
            copied.append(filename)
        except OSError as e:
            logger.warning(
                "Failed to copy workspace template file %s: %s",
                filename,
                e,
            )
    return copied


def _remove_bootstrap_from_workspace(workspace_dir: Path) -> None:
    bootstrap = workspace_dir / "BOOTSTRAP.md"
    if not bootstrap.exists():
        return
    try:
        bootstrap.unlink()
        logger.info(
            "Removed BOOTSTRAP.md from builtin QA workspace %s",
            workspace_dir,
        )
    except OSError as e:
        logger.warning("Could not remove BOOTSTRAP.md: %s", e)


def copy_template_md_files(
    template_id: str,
    language: str,
    workspace_dir: Path | str,
    *,
    only_if_missing: bool = True,
) -> list[str]:
    """Copy template-specific markdown files into an agent workspace.

    Files are read from ``md_files/<template_id>/<language>/`` with fallback
    order ``language`` → ``en`` → ``zh`` → ``ru`` on a per-file basis.

    Args:
        template_id: Template directory name under ``agents/md_files``.
        language: Language code (en/zh/ru).
        workspace_dir: Agent workspace root.
        only_if_missing: If True, skip targets that already exist.

    Returns:
        List of copied or overwritten file names.
    """
    workspace_dir = Path(workspace_dir).expanduser()
    workspace_dir.mkdir(parents=True, exist_ok=True)

    agents_root = Path(__file__).resolve().parent.parent
    template_root = agents_root / "md_files" / template_id
    if not template_root.exists():
        logger.warning(
            "Workspace template directory not found: %s",
            template_root,
        )
        return []

    copied_files = _copy_template_md_files(
        template_root,
        _template_fallback_language_order(language),
        workspace_dir,
        only_if_missing,
    )
    _remove_bootstrap_from_workspace(workspace_dir)
    return copied_files


def copy_workspace_md_files(
    language: str,
    workspace_dir: Path | str,
    *,
    md_template_id: str | None = None,
    only_if_missing: bool = True,
) -> list[str]:
    """Copy common workspace md files plus optional template overrides."""
    workspace_dir = Path(workspace_dir).expanduser()

    copied_files = copy_md_files(
        language,
        skip_existing=only_if_missing,
        workspace_dir=workspace_dir,
        exclude_filenames=(
            _TEMPLATE_OVERRIDE_FILENAMES if md_template_id else None
        ),
    )

    if not md_template_id:
        return copied_files

    copied_files.extend(
        copy_template_md_files(
            md_template_id,
            language,
            workspace_dir,
            only_if_missing=only_if_missing,
        ),
    )
    return copied_files


def copy_builtin_qa_md_files(
    language: str,
    workspace_dir: Path | str,
    *,
    only_if_missing: bool = True,
) -> list[str]:
    """Backward-compatible wrapper for builtin QA workspace templates."""
    return copy_workspace_md_files(
        language,
        workspace_dir,
        md_template_id="qa",
        only_if_missing=only_if_missing,
    )
