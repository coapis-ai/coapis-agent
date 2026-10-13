# -*- coding: utf-8 -*-
"""Skill/runtime dependency self-check.

Two declaration channels exist for skill dependencies and they do not agree:

* ``RuntimeDependencyManager`` (``agents/runtime_dependency.py``) pre-checks and
  auto-installs, but it reads requirements only from ``SKILL.md`` frontmatter
  via ``skills_manager.get_skill_requirements``.
* Real skills in the workspaces declare dependencies in a
  ``requirements.txt`` next to ``SKILL.md`` (e.g.
  ``skills/attribute-structure-processor/requirements.txt`` declares
  ``python-docx``, ``openpyxl``, ``pandas``) and their frontmatter has no
  ``requires`` block at all.

So the existing mechanism is blind to those skills: it reports zero
requirements, never pre-checks, never installs, and the skill fails only when a
user invokes it. This module closes that gap by checking **both** channels, and
by verifying availability the way the runtime sees it (``importlib.metadata`` on
the pip distribution name, which is what ``RuntimeDependencyManager`` uses).

It is deliberately probe-only: no package is imported, so the check costs
milliseconds and cannot crash the server. Auto-install is opt-in via
``COAPIS_AUTO_INSTALL_DEPS=1`` — installing at startup means a network install
inside the container, which is not a safe default for a production image.
"""
from __future__ import annotations

import importlib.util
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Libraries the platform tells agents are available. A knowledge entry in a
# workspace lists exactly this set (python-docx, PyPDF2, pdfplumber, reportlab,
# openpyxl, pandas, xlrd/xlwt, python-pptx); when one is absent the agent
# writes code that fails at runtime because it believes the library exists.
PLATFORM_OPTIONAL_DEPS = {
    "python-pptx": "PPT generation (pptx)",
    "openpyxl": "Excel generation (openpyxl)",
    "python-docx": "Word generation (docx)",
    "pandas": "tabular data processing (pandas)",
    "pymupdf4llm": "PDF parsing to Markdown (pymupdf4llm)",
    "PyPDF2": "PDF merge/split (PyPDF2)",
    "pdfplumber": "PDF text/table extraction (pdfplumber)",
    "xlrd": "legacy .xls reading (xlrd)",
    "xlwt": "legacy .xls writing (xlwt)",
}


def is_installed(name: str) -> bool:
    """True if a package is available to the running interpreter.

    Checks the pip distribution name first (``importlib.metadata``), which is
    what ``RuntimeDependencyManager._is_package_installed`` uses, then falls
    back to an import-name probe for packages whose import name differs
    (``PIL``, ``fitz``) or that are vendored on ``sys.path`` without metadata.
    """
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as pkg_version

    try:
        pkg_version(name)
        return True
    except PackageNotFoundError:
        pass
    except Exception:  # odd metadata for an unusual name
        pass

    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def parse_requirements(path: Path) -> list[str]:
    """Return package names declared in a requirements.txt (versions stripped)."""
    packages: list[str] = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return packages
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):  # skip flags like -e, --index-url
            continue
        name = re.split(r"[<>=!~\[\]]", line, maxsplit=1)[0].strip()
        if name:
            packages.append(name)
    return packages


def frontmatter_packages(skill_md: Path) -> list[str]:
    """Package names declared in a SKILL.md frontmatter ``requires`` block.

    Reuses ``skills_manager._extract_requirements`` so the frontmatter is
    interpreted with the same rules the runtime uses.
    """
    try:
        import frontmatter
    except ImportError:
        return []
    try:
        post = frontmatter.load(str(skill_md))
    except Exception:
        return []
    try:
        from ..agents.skills_manager import _extract_requirements

        reqs = _extract_requirements(post.to_dict())
        return [p.name for p in reqs.require_packages if p.name]
    except Exception:
        return []


def find_skill_dirs(workspaces_dir: Path) -> list[Path]:
    """Every ``workspaces/*/skills/<skill>`` directory."""
    if not workspaces_dir.is_dir():
        return []
    dirs: list[Path] = []
    for ws in sorted(workspaces_dir.iterdir()):
        skills = ws / "skills"
        if skills.is_dir():
            dirs.extend(sorted(d for d in skills.iterdir() if d.is_dir()))
    return dirs


def check_dependencies(workspaces_dir: Path) -> dict[str, list[str]]:
    """Report missing dependencies as ``{package: [reason, ...]}``."""
    missing: dict[str, list[str]] = {}

    def record(pkg: str, reason: str) -> None:
        if not is_installed(pkg):
            missing.setdefault(pkg, []).append(reason)

    for pkg, feature in PLATFORM_OPTIONAL_DEPS.items():
        record(pkg, f"platform feature: {feature}")

    for skill_dir in find_skill_dirs(workspaces_dir):
        skill_name = skill_dir.name
        req_file = skill_dir / "requirements.txt"
        if req_file.is_file():
            for pkg in parse_requirements(req_file):
                record(pkg, f"declared by skill '{skill_name}' requirements.txt")
        for pkg in frontmatter_packages(skill_dir / "SKILL.md"):
            record(pkg, f"declared by skill '{skill_name}' frontmatter")

    return missing


def format_warnings(missing: dict[str, list[str]]) -> list[str]:
    lines = []
    for pkg, reasons in sorted(missing.items()):
        uniq = sorted(set(reasons))
        lines.append(f"{pkg} missing — {'; '.join(uniq)}")
    return lines


def auto_install(missing: dict[str, list[str]]) -> list[str]:
    """Install missing packages with pip. Opt-in via COAPIS_AUTO_INSTALL_DEPS=1."""
    if not missing:
        return []
    if os.getenv("COAPIS_AUTO_INSTALL_DEPS", "0") != "1":
        return []
    import subprocess
    import sys

    results = []
    for pkg in sorted(missing):
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--no-warn-reminder", pkg],
                capture_output=True,
                text=True,
                timeout=180,
            )
            if proc.returncode == 0:
                results.append(f"{pkg} installed")
            else:
                results.append(f"{pkg} install failed: {proc.stderr.strip()[:120]}")
        except Exception as exc:
            results.append(f"{pkg} install failed: {exc}")
    return results


def run_startup_dependency_check(workspaces_dir: Path) -> None:
    """Log missing dependencies; auto-install only when explicitly enabled."""
    # Probe in the same environment the runtime uses: shared_runtime
    # site-packages is where skill libraries get installed, and it is added to
    # sys.path lazily by RuntimeDependencyManager, so make sure it is visible
    # before probing (otherwise a library that IS available gets reported as
    # missing).
    try:
        from ..agents.runtime_dependency import _ensure_shared_runtime_on_pythonpath

        _ensure_shared_runtime_on_pythonpath()
    except Exception:
        logger.debug("shared_runtime path not added before dependency probe", exc_info=True)

    missing = check_dependencies(workspaces_dir)
    if not missing:
        logger.debug("Dependency self-check: all declared libraries present")
        return

    warnings = format_warnings(missing)
    logger.warning(
        "Dependency self-check found %d missing package(s):\n  %s",
        len(missing),
        "\n  ".join(warnings),
    )
    installed = auto_install(missing)
    if installed:
        logger.warning("Auto-install results:\n  %s", "\n  ".join(installed))
    else:
        logger.warning(
            "Auto-install disabled (set COAPIS_AUTO_INSTALL_DEPS=1 to enable). "
            "Skills whose libraries are missing will fail when invoked.",
        )
