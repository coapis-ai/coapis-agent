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

"""Crypto operations — hashing, HMAC, encoding/decoding utilities.

Provides safe crypto primitives for verification and integrity checks.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


def _get_workspace() -> Path:
    try:
        from ...config.context import get_current_workspace_dir
        ws = get_current_workspace_dir()
        if ws:
            return Path(ws)
    except Exception:
        pass
    return Path.cwd()


async def crypto_ops(
    action: str = "hash",
    text: str = "",
    algorithm: str = "sha256",
    secret: str = "",
    signature: str = "",
    file_path: str = "",
    encoding: str = "utf-8",
    output_format: str = "hex",
) -> dict[str, Any]:
    """加密工具。

    Args:
        action: 操作类型 (hash/hmac_sign/hmac_verify/base64_encode/base64_decode/file_hash)
        text: 输入文本
        algorithm: 哈希算法 (md5/sha1/sha256/sha512)
        secret: HMAC 密钥
        signature: 待验证的签名（hmac_verify 时使用）
        file_path: 文件路径（file_hash 时使用）
        encoding: 文本编码，默认 utf-8
        output_format: 输出格式 (hex/base64)

    Returns:
        计算结果
    """
    if action == "hash":
        if not text.strip() and not file_path.strip():
            return {"error": "text 或 file_path 不能为空"}
        algo = algorithm.lower().strip()
        h = hashlib.new(algo)
        if file_path.strip():
            fp = Path(file_path.strip())
            if not fp.is_absolute():
                fp = _get_workspace() / fp
            if not fp.exists():
                return {"error": f"文件不存在: {file_path}"}
            with open(str(fp), "rb") as f:
                while chunk := f.read(8192):
                    h.update(chunk)
        else:
            h.update(text.encode(encoding))

        digest = h.hexdigest() if output_format == "hex" else base64.b64encode(h.digest()).decode("ascii")
        return {
            "action": "hash",
            "algorithm": algo,
            "digest": digest,
            "length": len(h.digest()),
            "output_format": output_format,
        }

    elif action == "file_hash":
        if not file_path.strip():
            return {"error": "file_path 不能为空"}
        fp = Path(file_path.strip())
        if not fp.is_absolute():
            fp = _get_workspace() / fp
        if not fp.exists():
            return {"error": f"文件不存在: {file_path}"}

        results = {}
        for algo in ("md5", "sha1", "sha256"):
            h = hashlib.new(algo)
            with open(str(fp), "rb") as f:
                while chunk := f.read(8192):
                    h.update(chunk)
            results[algo] = h.hexdigest()

        return {
            "action": "file_hash",
            "file": str(fp),
            "size": fp.stat().st_size,
            "hashes": results,
        }

    elif action == "hmac_sign":
        if not text.strip():
            return {"error": "text 不能为空"}
        if not secret.strip():
            return {"error": "secret 不能为空"}

        algo = algorithm.lower().strip()
        sig = hmac.new(secret.encode(encoding), text.encode(encoding), getattr(hashlib, algo)).hexdigest()
        return {
            "action": "hmac_sign",
            "algorithm": algo,
            "signature": sig,
        }

    elif action == "hmac_verify":
        if not text.strip():
            return {"error": "text 不能为空"}
        if not secret.strip():
            return {"error": "secret 不能为空"}
        if not signature.strip():
            return {"error": "signature 不能为空"}

        algo = algorithm.lower().strip()
        expected = hmac.new(secret.encode(encoding), text.encode(encoding), getattr(hashlib, algo)).hexdigest()
        valid = hmac.compare_digest(expected, signature.strip())
        return {
            "action": "hmac_verify",
            "algorithm": algo,
            "valid": valid,
            "expected": expected if not valid else "",
        }

    elif action == "base64_encode":
        if not text.strip():
            return {"error": "text 不能为空"}
        encoded = base64.b64encode(text.encode(encoding)).decode("ascii")
        return {
            "action": "base64_encode",
            "result": encoded,
            "length": len(encoded),
        }

    elif action == "base64_decode":
        if not text.strip():
            return {"error": "text 不能为空"}
        try:
            decoded = base64.b64decode(text.encode("ascii")).decode(encoding)
            return {
                "action": "base64_decode",
                "result": decoded,
                "length": len(decoded),
            }
        except Exception as e:
            return {"error": f"解码失败: {e}"}

    else:
        return {"error": f"未知操作: {action}，支持 hash/file_hash/hmac_sign/hmac_verify/base64_encode/base64_decode"}
