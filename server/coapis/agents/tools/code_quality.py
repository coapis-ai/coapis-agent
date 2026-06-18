# -*- coding: utf-8 -*-
# Copyright 2026 以太吃虾 & CoApis Contributors
# Licensed under the Apache License, Version 2.0
"""Code quality — unified tool for code formatting, documentation generation, and review.

Merges: code_formatter + code_docgen + code_review into one tool with action switching.
"""
from __future__ import annotations
from .registry import register_tool
import subprocess, json, ast, os, re, tempfile


def _format_code(code: str, language: str = "python") -> dict:
    """Format code with black (Python) or prettier (JS/TS)."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=f".{language}", delete=False) as f:
        f.write(code)
        tmp = f.name
    try:
        if language == "python":
            r = subprocess.run(["python3", "-m", "black", "--quiet", tmp],
                             capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                formatted = open(tmp).read()
                return {"formatted": formatted, "language": language, "status": "ok"}
            return {"error": r.stderr.strip(), "status": "failed"}
        elif language in ("javascript", "typescript", "js", "ts"):
            r = subprocess.run(["npx", "prettier", "--write", tmp],
                             capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                formatted = open(tmp).read()
                return {"formatted": formatted, "language": language, "status": "ok"}
            return {"error": r.stderr.strip(), "status": "failed"}
        return {"error": f"Unsupported language: {language}", "status": "failed"}
    finally:
        os.unlink(tmp)


def _generate_docs(code: str, language: str = "python") -> dict:
    """Generate documentation from code."""
    if language != "python":
        return {"error": "Only Python doc generation supported", "status": "failed"}
    try:
        tree = ast.parse(code)
        docs = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                sig_parts = []
                for arg in node.args.args:
                    name = arg.arg
                    if name == "self":
                        continue
                    ann = ast.unparse(arg.annotation) if arg.annotation else ""
                    sig_parts.append(f"{name}: {ann}" if ann else name)
                sig = ", ".join(sig_parts)
                doc = ast.get_docstring(node) or "(no docstring)"
                docs.append({"name": node.name, "signature": f"({sig})", "docstring": doc})
            elif isinstance(node, ast.ClassDef):
                doc = ast.get_docstring(node) or "(no docstring)"
                methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                docs.append({"name": node.name, "docstring": doc, "methods": methods})
        return {"docs": docs, "count": len(docs), "status": "ok"}
    except SyntaxError as e:
        return {"error": f"Syntax error: {e}", "status": "failed"}


def _review_code(code: str, language: str = "python") -> dict:
    """Lightweight code review with common checks."""
    issues = []
    lines = code.split("\n")
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if len(stripped) > 120:
            issues.append({"line": i, "severity": "warning", "rule": "line-length", "message": f"Line too long ({len(stripped)} chars)"})
        if "eval(" in stripped or "exec(" in stripped:
            issues.append({"line": i, "severity": "error", "rule": "dangerous-exec", "message": "Use of eval/exec detected"})
        if "TODO" in stripped or "FIXME" in stripped or "HACK" in stripped:
            issues.append({"line": i, "severity": "info", "rule": "todo-comment", "message": "TODO/FIXME comment found"})
        if stripped.startswith("except:") or stripped.startswith("except Exception"):
            issues.append({"line": i, "severity": "warning", "rule": "bare-except", "message": "Bare except clause"})
        if "=" in stripped and "==" not in stripped and "!=" not in stripped and "<=" not in stripped and ">=" not in stripped:
            if re.match(r'^\s*\w+\s*=\s*\w+\s*=\s*', stripped):
                issues.append({"line": i, "severity": "warning", "rule": "chained-assignment", "message": "Chained assignment"})
    if language == "python":
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    if len(node.args.args) > 7:
                        issues.append({"line": node.lineno, "severity": "warning", "rule": "too-many-args",
                                       "message": f"Function '{node.name}' has {len(node.args.args)} args (>7)"})
                    if len(node.body) > 50:
                        issues.append({"line": node.lineno, "severity": "warning", "rule": "function-too-long",
                                       "message": f"Function '{node.name}' has {len(node.body)} lines (>50)"})
        except SyntaxError:
            pass
    return {"issues": issues, "total": len(issues), "status": "ok"}


@register_tool(
    name="code_quality",
    description="代码质量工具：统一格式化(format)、文档生成(docgen)、代码审查(review)。支持 Python/JS/TS。",
    category="builtin",
    tags=["code", "quality", "format", "review", "documentation"],
    scene="coding",
)
async def code_quality(
    action: str = "review",
    code: str = "",
    language: str = "python",
) -> dict:
    """代码质量工具。

    Args:
        action: 操作类型 - format(格式化) / docgen(文档生成) / review(代码审查)
        code: 要处理的代码
        language: 语言 (python/javascript/typescript)
    """
    if not code.strip():
        return {"error": "code 不能为空"}

    if action == "format":
        return {"action": "format", **_format_code(code, language)}
    elif action == "docgen":
        return {"action": "docgen", **_generate_docs(code, language)}
    elif action == "review":
        return {"action": "review", **_review_code(code, language)}
    else:
        return {"error": f"未知 action: {action}，支持 format/docgen/review"}
