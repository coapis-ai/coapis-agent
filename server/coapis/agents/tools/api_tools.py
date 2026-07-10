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
"""API tools — unified tool for mock API servers and schema validation.

Merges: api_mock + schema_validate into one tool.
"""
from __future__ import annotations
import json, os, time, re, hashlib
from pathlib import Path
from .registry import register_tool


def _mock_server_endpoints(config: str, port: int = 8899) -> dict:
    """Parse JSON config and describe mock endpoints."""
    try:
        endpoints = json.loads(config) if isinstance(config, str) else config
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON config: {e}", "status": "failed"}

    result_endpoints = []
    for ep in (endpoints if isinstance(endpoints, list) else [endpoints]):
        path = ep.get("path", "/")
        method = ep.get("method", "GET").upper()
        status = ep.get("status", 200)
        body = ep.get("body", {})
        delay = ep.get("delay", 0)
        result_endpoints.append({"path": path, "method": method, "status": status, "delay_ms": delay * 1000, "body": body})
    return {"endpoints": result_endpoints, "count": len(result_endpoints), "status": "ok", "note": "Mock server definition parsed (HTTP server not started inline)"}


def _validate_schema(data: str, schema: str) -> dict:
    """Validate data against JSON Schema."""
    try:
        obj = json.loads(data) if isinstance(data, str) else data
    except json.JSONDecodeError as e:
        return {"valid": False, "error": f"Invalid data JSON: {e}"}
    try:
        sch = json.loads(schema) if isinstance(schema, str) else schema
    except json.JSONDecodeError as e:
        return {"valid": False, "error": f"Invalid schema JSON: {e}"}

    errors = []

    def _check(obj, sch, path=""):
        if not isinstance(sch, dict):
            return
        if "type" in sch:
            expected = sch["type"]
            if expected == "object" and not isinstance(obj, dict):
                errors.append({"path": path, "message": f"Expected object, got {type(obj).__name__}"})
            elif expected == "array" and not isinstance(obj, list):
                errors.append({"path": path, "message": f"Expected array, got {type(obj).__name__}"})
            elif expected == "string" and not isinstance(obj, str):
                errors.append({"path": path, "message": f"Expected string, got {type(obj).__name__}"})
            elif expected == "number" and not isinstance(obj, (int, float)):
                errors.append({"path": path, "message": f"Expected number, got {type(obj).__name__}"})
            elif expected == "integer" and not isinstance(obj, int):
                errors.append({"path": path, "message": f"Expected integer, got {type(obj).__name__}"})
            elif expected == "boolean" and not isinstance(obj, bool):
                errors.append({"path": path, "message": f"Expected boolean, got {type(obj).__name__}"})
        if "properties" in sch and isinstance(obj, dict):
            for k, v in sch["properties"].items():
                if k in obj:
                    _check(obj[k], v, f"{path}.{k}" if path else k)
        if "required" in sch and isinstance(obj, dict):
            for r in sch["required"]:
                if r not in obj:
                    errors.append({"path": path, "message": f"Missing required field: {r}"})
        if "items" in sch and isinstance(obj, list):
            for i, item in enumerate(obj[:5]):
                _check(item, sch["items"], f"{path}[{i}]")

    _check(obj, sch)
    return {"valid": len(errors) == 0, "errors": errors, "status": "ok"}


def _validate_openapi(spec_text: str) -> dict:
    """Basic OpenAPI spec validation."""
    try:
        spec = json.loads(spec_text) if isinstance(spec_text, str) else spec_text
    except json.JSONDecodeError as e:
        return {"valid": False, "error": f"Invalid JSON: {e}"}

    issues = []
    if "openapi" not in spec and "swagger" not in spec:
        issues.append({"severity": "error", "message": "Missing 'openapi' or 'swagger' version field"})
    if "info" not in spec:
        issues.append({"severity": "error", "message": "Missing 'info' object"})
    if "paths" not in spec:
        issues.append({"severity": "error", "message": "Missing 'paths' object"})
    else:
        paths = spec.get("paths", {})
        for path, methods in paths.items():
            if not path.startswith("/"):
                issues.append({"severity": "warning", "message": f"Path '{path}' should start with /"})
            for method, detail in methods.items():
                if method.lower() in ("get", "post", "put", "delete", "patch"):
                    if "responses" not in detail:
                        issues.append({"severity": "warning", "message": f"{method.upper()} {path}: missing 'responses'"})

    return {"valid": len([i for i in issues if i["severity"] == "error"]) == 0, "issues": issues, "total": len(issues), "status": "ok"}


async def api_tools(
    action: str = "validate",
    config: str = "",
    data: str = "",
    schema: str = "",
    port: int = 8899,
) -> dict:
    """API 开发辅助工具。

    Args:
        action: mock(定义 Mock 端点) / validate(JSON Schema 校验) / openapi(OpenAPI 校验)
        config: Mock 端点 JSON 配置 (mock 时)
        data: 待校验数据 JSON (validate 时)
        schema: JSON Schema (validate 时)
        port: Mock 服务端口 (mock 时)
    """
    if action == "mock":
        if not config.strip():
            return {"error": "config 不能为空"}
        return {"action": "mock", **_mock_server_endpoints(config, port)}
    elif action == "validate":
        if not data.strip() or not schema.strip():
            return {"error": "data 和 schema 不能为空"}
        return {"action": "validate", **_validate_schema(data, schema)}
    elif action == "openapi":
        if not config.strip():
            return {"error": "OpenAPI spec 不能为空"}
        return {"action": "openapi", **_validate_openapi(config)}
    else:
        return {"error": f"未知 action: {action}，支持 mock/validate/openapi"}
