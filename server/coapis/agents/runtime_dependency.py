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

"""Runtime dependency manager: pre-check, auto-install, and recovery for tool/skill dependencies."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel

from .skills_manager import PackageRequirement, SkillRequirements

logger = logging.getLogger(__name__)


class _InstallResult(BaseModel):
    ok: bool
    hint: str = ""


def _shared_runtime_dir() -> Path:
    return Path(os.environ.get("COAPIS_SHARED_RUNTIME_DIR", "/opt/coapis/shared_runtime"))


def _ensure_shared_runtime_on_pythonpath() -> None:
    """Add shared runtime site-packages to sys.path if missing."""
    shared_dir = _shared_runtime_dir()
    candidate = shared_dir / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    if candidate.is_dir() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))
        logger.debug("Added shared runtime site-packages to sys.path: %s", candidate)


class RuntimeDependencyManager:
    """Singleton-style manager for runtime dependency pre-check and auto-install."""

    def __init__(self) -> None:
        self._install_cache: dict[str, bool] = {}

    async def ensure_for_tool(self, tool_name: str) -> _InstallResult:
        deps = _get_tool_dependencies(tool_name)
        return await self._ensure_dependencies(deps)

    async def ensure_for_skill(self, skill_name: str) -> _InstallResult:
        deps = _get_skill_dependencies(skill_name)
        return await self._ensure_dependencies(deps)

    async def _ensure_dependencies(self, deps: list[PackageRequirement]) -> _InstallResult:
        if not deps:
            return _InstallResult(ok=True)

        missing: list[PackageRequirement] = []
        for dep in deps:
            cache_key = f"{dep.manager}:{dep.name}:{dep.version or ''}"
            if cache_key in self._install_cache:
                if not self._install_cache[cache_key] and dep.required:
                    return _InstallResult(ok=False, hint=f"依赖 {dep.name} 安装失败（缓存）。")
                continue
            if not _is_package_installed(dep):
                missing.append(dep)

        for dep in missing:
            installed = await _install_dependency(dep)
            self._install_cache[f"{dep.manager}:{dep.name}:{dep.version or ''}"] = installed
            if not installed and dep.required:
                return _InstallResult(ok=False, hint=f"依赖 {dep.name} 安装失败，请检查网络或手动安装后重试。")

        _ensure_shared_runtime_on_pythonpath()
        return _InstallResult(ok=True)


def _get_tool_dependencies(tool_name: str) -> list[PackageRequirement]:
    from .tools.registry import get_registered_tool
    reg = get_registered_tool(tool_name)
    if not reg or not getattr(reg, "dependencies", None):
        return []
    out: list[PackageRequirement] = []
    for dep in reg.dependencies:
        if isinstance(dep, dict):
            out.append(
                PackageRequirement(
                    name=str(dep.get("name", "")),
                    manager=str(dep.get("manager", "pip")),
                    version=dep.get("version"),
                    required=bool(dep.get("required", True)),
                    reason=str(dep.get("reason", "")),
                ),
            )
    return out


def _get_skill_dependencies(skill_name: str) -> list[PackageRequirement]:
    from .skills_manager import get_skill_requirements
    reqs = get_skill_requirements(skill_name)
    return list(reqs.require_packages or [])


def _is_package_installed(dep: PackageRequirement) -> bool:
    manager = dep.manager
    name = dep.name
    version = dep.version
    try:
        if manager == "pip":
            from importlib.metadata import version as pkg_version, PackageNotFoundError
            try:
                pkg_version(name)
                if version:
                    installed = pkg_version(name)
                    return installed == version
                return True
            except PackageNotFoundError:
                return False
        if manager == "npm":
            return _npm_package_exists(name, version)
    except Exception:
        return False
    return False


def _package_from_import_error(err: ImportError) -> Optional[PackageRequirement]:
    message = str(err)
    if "No module named" in message:
        raw = message.split("No module named", 1)[-1].strip().strip("\"'.")
        if raw:
            return PackageRequirement(name=raw, manager="pip", required=True, reason=str(err))
    if "cannot import name" in message or "cannot import" in message:
        parts = [p.strip() for p in message.split("'") if p.strip()]
        if parts:
            return PackageRequirement(name=parts[0], manager="pip", required=True, reason=str(err))
    return None


async def _install_dependency_from_error(err: ImportError, tool_name: str) -> bool:
    dep = _package_from_import_error(err)
    if dep is None:
        return False
    if not dep.name:
        return False
    logger.warning(
        "Auto-recovering missing dependency for %s: %s",
        tool_name,
        dep.name,
    )
    return await _install_dependency(dep)


def _npm_package_exists(name: str, version: Optional[str], *, global_root: Optional[Path] = None) -> bool:
    try:
        root = global_root or Path("/usr/local/lib/node_modules")
        pkg_dir = root / name.replace("@", "").replace("/", "-")
        return pkg_dir.is_dir()
    except Exception:
        return False


async def _install_dependency(dep: PackageRequirement) -> bool:
    manager = dep.manager
    name = dep.name
    version = dep.version
    try:
        from .tools.install_dependency import install_dependency
        resp = await install_dependency(
            package=name,
            manager=manager,  # type: ignore[arg-type]
            version=version,
        )
        text_blocks = getattr(resp, "content", [])
        text = ""
        for block in text_blocks:
            text += getattr(block, "text", "")
        return "成功安装" in text or resp is not None
    except Exception as e:
        logger.warning("Auto-install failed for %s: %s", name, e)
        return False


_manager = RuntimeDependencyManager()
