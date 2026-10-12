"""Tests for the skill/runtime dependency self-check."""
import frontmatter

from coapis.utils.deps_check import (
    auto_install,
    check_dependencies,
    find_skill_dirs,
    format_warnings,
    frontmatter_packages,
    is_installed,
    parse_requirements,
)


def test_parse_requirements_strips_versions_comments_and_flags(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text(
        "python-docx>=1.1.0\n"
        "openpyxl>=3.1.0  # excel\n"
        "pandas\n"
        "# comment line\n"
        "-e .\n"
        "--index-url https://x\n"
        "scikit-learn==1.5\n",
        encoding="utf-8",
    )
    assert parse_requirements(req) == [
        "python-docx",
        "openpyxl",
        "pandas",
        "scikit-learn",
    ]


def test_is_installed_finds_stdlib_and_misses_fake():
    # importlib.metadata has no dist for stdlib, so the import probe must catch it.
    assert is_installed("json") is True
    assert is_installed("definitely-not-a-real-package-xyz") is False


def test_is_installed_uses_pip_dist_name_not_import_name(monkeypatch):
    # python-pptx: dist name is python-pptx, import name is pptx.
    seen = []

    def fake_version(name):
        seen.append(name)
        if name == "python-pptx":
            return "1.0.2"
        raise Exception("not found")

    import importlib.metadata

    monkeypatch.setattr(importlib.metadata, "version", fake_version)
    assert is_installed("python-pptx") is True
    assert seen == ["python-pptx"]


def test_find_skill_dirs_only_under_skills(tmp_path):
    ws = tmp_path / "workspaces"
    skill = ws / "alice" / "skills" / "xlsx"
    skill.mkdir(parents=True)
    # Not a skill dir: must be ignored.
    (ws / "alice" / "files" / "not_a_skill").mkdir(parents=True)

    found = find_skill_dirs(ws)
    assert [d.name for d in found] == ["xlsx"]


def test_frontmatter_packages_reads_requires_block(tmp_path):
    skill_md = tmp_path / "SKILL.md"
    # Real format: metadata.<namespace>.requires.packages
    post = frontmatter.Post(
        "# body",
        name="xlsx",
        metadata={"coapis": {"requires": {"packages": [{"name": "openpyxl"}]}}},
    )
    skill_md.write_text(frontmatter.dumps(post), encoding="utf-8")
    assert frontmatter_packages(skill_md) == ["openpyxl"]


def test_frontmatter_packages_accepts_plain_string_packages(tmp_path):
    skill_md = tmp_path / "SKILL.md"
    post = frontmatter.Post(
        "# body",
        name="xlsx",
        metadata={"coapis": {"requires": {"packages": ["python-pptx"]}}},
    )
    skill_md.write_text(frontmatter.dumps(post), encoding="utf-8")
    assert frontmatter_packages(skill_md) == ["python-pptx"]


def test_frontmatter_packages_empty_when_no_requires(tmp_path):
    skill_md = tmp_path / "SKILL.md"
    post = frontmatter.Post("# body", name="xlsx", version="1.0.0")
    skill_md.write_text(frontmatter.dumps(post), encoding="utf-8")
    assert frontmatter_packages(skill_md) == []


def test_check_dependencies_covers_both_declaration_channels(
    tmp_path, monkeypatch
):
    ws = tmp_path / "workspaces"
    skill = ws / "alice" / "skills" / "xlsx"
    skill.mkdir(parents=True)
    (skill / "requirements.txt").write_text(
        "fakepkg-from-reqs>=1.0\n", encoding="utf-8"
    )
    post = frontmatter.Post(
        "# body",
        name="xlsx",
        metadata={"coapis": {"requires": {"packages": ["fakepkg-from-frontmatter"]}}},
    )
    (skill / "SKILL.md").write_text(frontmatter.dumps(post), encoding="utf-8")

    # Control availability so the test does not depend on the env.
    monkeypatch.setattr(
        "coapis.utils.deps_check.is_installed",
        lambda pkg: pkg == "openpyxl",
    )
    missing = check_dependencies(ws)
    assert "fakepkg-from-reqs" in missing
    assert "fakepkg-from-frontmatter" in missing
    assert any("requirements.txt" in r for r in missing["fakepkg-from-reqs"])
    assert any("frontmatter" in r for r in missing["fakepkg-from-frontmatter"])
    assert "openpyxl" not in missing


def test_startup_check_adds_shared_runtime_before_probing(tmp_path, monkeypatch):
    # A library that lives only in shared_runtime must not be reported missing,
    # so the check has to put shared_runtime on sys.path before probing.
    calls = []
    monkeypatch.setattr(
        "coapis.agents.runtime_dependency._ensure_shared_runtime_on_pythonpath",
        lambda: calls.append("added"),
    )
    monkeypatch.setattr(
        "coapis.utils.deps_check.check_dependencies",
        lambda ws: {},
    )
    from coapis.utils.deps_check import run_startup_dependency_check

    run_startup_dependency_check(tmp_path)
    assert calls == ["added"]


def test_format_warnings_is_readable():
    lines = format_warnings({"fakepkg": ["declared by skill 's1'"]})
    assert len(lines) == 1
    assert "fakepkg missing" in lines[0]


def test_auto_install_is_off_by_default(monkeypatch):
    monkeypatch.delenv("COAPIS_AUTO_INSTALL_DEPS", raising=False)
    assert auto_install({"definitely-not-real-xyz": ["x"]}) == []


def test_auto_install_enabled_flag_is_honoured(monkeypatch):
    monkeypatch.setenv("COAPIS_AUTO_INSTALL_DEPS", "1")
    calls = []

    class FakeProc:
        returncode = 0
        stderr = ""

    def fake_run(cmd, capture_output, text, timeout):
        calls.append(cmd)
        return FakeProc()

    import subprocess

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = auto_install({"fakepkg": ["x"]})
    assert calls, "flag on must attempt an install"
    assert calls[0][-1] == "fakepkg"
    assert result == ["fakepkg installed"]


def test_auto_install_reports_failure_not_silently(monkeypatch):
    monkeypatch.setenv("COAPIS_AUTO_INSTALL_DEPS", "1")

    class FailProc:
        returncode = 1
        stderr = "no matching distribution"

    import subprocess

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, capture_output, text, timeout: FailProc(),
    )
    result = auto_install({"fakepkg": ["x"]})
    assert "install failed" in result[0]
