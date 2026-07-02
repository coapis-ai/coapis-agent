# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
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

"""Archive operations — zip/tar/gz compress and decompress.

Wraps Python's zipfile and tarfile modules for safe archive management.
"""

from __future__ import annotations

import logging
import tarfile
import zipfile
from pathlib import Path
from typing import Any

from .registry import register_tool

logger = logging.getLogger(__name__)

_MAX_ARCHIVE_SIZE = 500 * 1024 * 1024  # 500MB


def _get_workspace() -> Path:
    try:
        from ...config.context import get_current_workspace_dir
        ws = get_current_workspace_dir()
        if ws:
            return Path(ws)
    except Exception:
        pass
    return Path.cwd()


def _get_files_dir() -> Path:
    """Get workspace/files/ directory (for writing output files)."""
    d = _get_workspace() / "files"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _resolve(path_str: str) -> Path | None:
    p = Path(path_str.strip())
    if p.is_absolute():
        return p if p.exists() else None
    ws = _get_workspace()
    resolved = ws / p
    return resolved if resolved.exists() else None


async def archive_ops(
    action: str = "list",
    source: str = "",
    dest: str = "",
    format: str = "zip",
    compression: str = "deflate",
    password: str = "",
    flatten: bool = False,
) -> dict[str, Any]:
    """压缩解压。

    Args:
        action: 操作类型 (compress/decompress/list)
        source: 源文件/目录路径
        dest: 目标路径
        format: 格式 (zip/tar/tar.gz/tar.bz2)
        compression: 压缩方式 (deflate/none) 仅 zip
        password: 密码（仅 zip 支持）
        flatten: 解压时是否扁平化（去掉目录结构）
    """
    ws = _get_workspace()

    if action == "list":
        if not source.strip():
            return {"error": "source 不能为空"}
        src = _resolve(source)
        if not src:
            return {"error": f"文件不存在: {source}"}

        # Try zip first (common format)
        try:
            with zipfile.ZipFile(str(src), "r") as zf:
                entries = []
                for info in zf.infolist():
                    entries.append({
                        "name": info.filename,
                        "size": info.file_size,
                        "compressed": info.compress_size,
                        "is_dir": info.is_dir(),
                    })
                return {
                    "action": "list", "format": "zip",
                    "entries": entries, "count": len(entries),
                    "total_size": sum(e["size"] for e in entries),
                }
        except (zipfile.BadZipFile, OSError):
            pass  # Not a zip file, try tar

        # Try tar
        try:
            with tarfile.open(str(src)) as tf:
                entries = []
                for member in tf.getmembers():
                    entries.append({
                        "name": member.name,
                        "size": member.size,
                        "is_dir": member.isdir(),
                    })
                return {
                    "action": "list", "format": "tar",
                    "entries": entries, "count": len(entries),
                    "total_size": sum(e["size"] for e in entries),
                }
        except (tarfile.TarError, OSError):
            pass

        return {"error": f"无法识别的归档格式: {src.name}"}

    elif action == "compress":
        if not source.strip():
            return {"error": "source 不能为空"}
        src = _resolve(source)
        if not src:
            return {"error": f"路径不存在: {source}"}

        dest_path = _get_files_dir() / dest.strip() if dest.strip() else None
        fmt = format.strip().lower()

        if fmt == "zip":
            if dest_path is None:
                dest_path = src.parent / f"{src.name}.zip"
            try:
                with zipfile.ZipFile(str(dest_path), "w") as zf:
                    if src.is_file():
                        zf.write(str(src), src.name)
                    elif src.is_dir():
                        for f in sorted(src.rglob("*")):
                            if f.is_file():
                                arcname = f.relative_to(src.parent)
                                zf.write(str(f), str(arcname))
                return {
                    "action": "compress", "format": "zip",
                    "source": str(src), "dest": str(dest_path),
                    "size": dest_path.stat().st_size,
                    "success": True,
                }
            except Exception as e:
                return {"error": f"压缩失败: {e}"}

        elif fmt.startswith("tar"):
            suffix = ".tar"
            mode = "w"
            if fmt in ("tar.gz", "tar.gz2"):
                suffix = ".tar.gz"
                mode = "w:gz"
            elif fmt == "tar.bz2":
                suffix = ".tar.bz2"
                mode = "w:bz2"
            elif fmt == "tar.xz":
                suffix = ".tar.xz"
                mode = "w:xz"

            if dest_path is None:
                dest_path = src.parent / f"{src.name}{suffix}"
            try:
                with tarfile.open(str(dest_path), mode) as tf:
                    if src.is_file():
                        tf.add(str(src), arcname=src.name)
                    elif src.is_dir():
                        tf.add(str(src), arcname=src.name)
                return {
                    "action": "compress", "format": fmt,
                    "source": str(src), "dest": str(dest_path),
                    "size": dest_path.stat().st_size,
                    "success": True,
                }
            except Exception as e:
                return {"error": f"压缩失败: {e}"}
        else:
            return {"error": f"不支持的压缩格式: {fmt}，支持 zip/tar/tar.gz/tar.bz2"}

    elif action == "decompress":
        if not source.strip():
            return {"error": "source 不能为空"}
        src = _resolve(source)
        if not src:
            return {"error": f"文件不存在: {source}"}

        dest_dir = _get_files_dir() / dest.strip() if dest.strip() else src.parent

        if src.suffix.lower() == ".zip":
            try:
                dest_dir.mkdir(parents=True, exist_ok=True)
                count = 0
                with zipfile.ZipFile(str(src), "r") as zf:
                    for info in zf.infolist():
                        if flatten and not info.is_dir():
                            # Flatten: extract to dest_dir with just filename
                            target = dest_dir / Path(info.filename).name
                        else:
                            target = dest_dir / info.filename
                            if info.is_dir():
                                target.mkdir(parents=True, exist_ok=True)
                                continue
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(info) as src_file, open(str(target), "wb") as dst_file:
                            dst_file.write(src_file.read())
                        count += 1
                return {
                    "action": "decompress", "format": "zip",
                    "source": str(src), "dest": str(dest_dir),
                    "files_extracted": count, "success": True,
                }
            except zipfile.BadZipFile:
                return {"error": "无效的 ZIP 文件"}
            except Exception as e:
                return {"error": f"解压失败: {e}"}

        elif src.suffix in (".tar",) or src.name.endswith((".tar.gz", ".tar.bz2", ".tar.xz")):
            try:
                dest_dir.mkdir(parents=True, exist_ok=True)
                with tarfile.open(str(src)) as tf:
                    if flatten:
                        members = []
                        for m in tf.getmembers():
                            if not m.isdir():
                                m.name = Path(m.name).name
                                members.append(m)
                        tf.extractall(str(dest_dir), members=members)
                    else:
                        tf.extractall(str(dest_dir))
                return {
                    "action": "decompress", "format": "tar",
                    "source": str(src), "dest": str(dest_dir),
                    "success": True,
                }
            except Exception as e:
                return {"error": f"解压失败: {e}"}
        else:
            return {"error": f"不支持的压缩格式: {src.suffix}"}

    else:
        return {"error": f"未知操作: {action}，支持 compress/decompress/list"}
