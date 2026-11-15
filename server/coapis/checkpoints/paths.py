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

"""检查点作用域规则（B5-A 最小版）。

**口径以台账为准，不自立门户**：

* 工作区文件的根 = ``FileLedgerService._files_root``
  （``workspaces/<user>/files``）——与巡检 ``reconcile()`` 扫的根逐字一致；
* 相对路径归一 = ``FileLedgerService._normalize_rel``——同一把尺子，检查点里
  的 key 与台账 ``file_records.file_path`` 同源可对账。

排除项三类，缺一不可：

1. **数据卷里的系统目录**（``system/``、``logs/``、``audit_log/``、``tmp/``、
   ``media/``、``models/``、``plugins/``、``custom_channels/``、
   ``local_models/``）——它们不是用户产物，把运行时状态写进快照再去"恢复"，
   等于拿历史覆盖当下运行时；
2. **密钥**（``.secret/``、``*.key``、``*.pem``、``.env`` …）——快照是明文
   副本，进快照就是把密钥抄了第二份；
3. **噪声**（``.git``、各级缓存、``*.db``、``checkpoints/`` 自身）。

本模块全部是纯函数（除读盘/算哈希外无副作用），根目录一律显式传参，
便于单测，也便于在测试里完全脱离真实数据卷。
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Optional, Sequence

from ..foundation.file_ledger import FileLedgerService

# --------------------------------------------------------------------------- #
# 排除词表
# --------------------------------------------------------------------------- #

#: 任意层级命中即整棵剪掉的目录名。
EXCLUDE_DIR_NAMES = frozenset(
    {
        # 版本控制
        ".git",
        ".svn",
        ".hg",
        # 缓存 / 构建产物
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        ".cache",
        "cache",
        "caches",
        "node_modules",
        ".venv",
        "venv",
        "dist",
        "build",
        # 编辑器
        ".idea",
        ".vscode",
        # 密钥 / 凭据目录
        ".secret",
        ".ssl",
        "certs",
        # 回收站
        ".trash",
        # 检查点自己的仓库（快照不得把自己卷进快照）
        "checkpoints",
    }
)

#: 精确文件名黑名单（凭据类）。
EXCLUDE_FILE_NAMES = frozenset(
    {
        ".env",
        ".env.local",
        ".env.production",
        ".netrc",
        ".npmrc",
        ".pypirc",
        ".git-credentials",
        "id_rsa",
        "id_ed25519",
        "id_ecdsa",
        ".DS_Store",
    }
)

#: 后缀黑名单（密钥 / 证书 / 数据库 / 日志 / 字节码）。
EXCLUDE_SUFFIXES = frozenset(
    {
        ".key",
        ".pem",
        ".p12",
        ".pfx",
        ".jks",
        ".keystore",
        ".crt",
        ".der",
        ".db",
        ".sqlite",
        ".sqlite3",
        ".db-wal",
        ".db-shm",
        ".log",
        ".pyc",
        ".pyo",
    }
)


# --------------------------------------------------------------------------- #
# 异常
# --------------------------------------------------------------------------- #


class CheckpointPathError(ValueError):
    """作用域/路径不合法（越界、指向数据卷系统目录、用户名非法）。"""


class PathEscapeError(CheckpointPathError):
    """相对路径逃出作用域根——恢复时绝不写这种路径。"""


class ScopeForbiddenError(CheckpointPathError):
    """作用域根落在禁止快照的目录里（数据卷系统目录 / 密钥目录）。"""


# --------------------------------------------------------------------------- #
# 纯函数：作用域
# --------------------------------------------------------------------------- #


def workspace_files_root(
    username: str, workspaces_dir: Path | str
) -> Path:
    """用户工作区文件根 = ``workspaces/<user>/files``（台账同源）。

    直接调台账自己的 ``_files_root``，不复制路径拼法——台账挪根时这里自动跟。
    """
    return FileLedgerService(workspaces_dir=Path(workspaces_dir))._files_root(
        str(username)
    )


def normalize_rel(path: Path | str, root: Path | str) -> Optional[str]:
    """把绝对路径归一成作用域内的 POSIX 相对路径；越界返回 None。

    复用台账的 ``_normalize_rel``（同一把尺子）。
    """
    return FileLedgerService._normalize_rel(Path(path), Path(root))


def is_excluded(rel_path: str) -> bool:
    """相对路径是否命中排除规则（纯函数，不读盘）。"""
    rel = str(rel_path).replace("\\", "/").strip("/")
    if not rel:
        return True
    parts = rel.split("/")
    for part in parts[:-1]:
        if part in EXCLUDE_DIR_NAMES:
            return True
    name = parts[-1]
    if name in EXCLUDE_FILE_NAMES:
        return True
    lowered = name.lower()
    for suffix in EXCLUDE_SUFFIXES:
        if lowered.endswith(suffix):
            return True
    return False


def iter_workspace_files(root: Path | str) -> Iterator[Path]:
    """遍历作用域根下的文件，按排除规则剪枝（含目录级剪枝，不深入 .git）。"""
    root = Path(root)
    if not root.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(str(root)):
        # 目录级剪枝：原地改 dirnames，os.walk 就不下去
        dirnames[:] = sorted(
            d for d in dirnames if d not in EXCLUDE_DIR_NAMES
        )
        for fname in sorted(filenames):
            p = Path(dirpath) / fname
            rel = normalize_rel(p, root)
            if rel is None or is_excluded(rel):
                continue
            if not p.is_file():  # 断链 / 特殊文件
                continue
            yield p


# --------------------------------------------------------------------------- #
# 纯函数：指纹
# --------------------------------------------------------------------------- #


def hash_file(path: Path | str, *, chunk_size: int = 1 << 16) -> str:
    """sha256 分块哈希（沿用 ``tunnel/binary_manager`` 的范式）。"""
    digest = hashlib.sha256()
    with open(str(path), "rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class FileEntry:
    """一个工作区文件的快照条目（检查点里的最小事实）。"""

    rel: str
    sha256: str
    size: int
    mtime: float

    def to_dict(self) -> dict:
        return {
            "rel": self.rel,
            "sha256": self.sha256,
            "size": int(self.size),
            "mtime": float(self.mtime),
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "FileEntry":
        return cls(
            rel=str(raw["rel"]),
            sha256=str(raw["sha256"]),
            size=int(raw.get("size") or 0),
            mtime=float(raw.get("mtime") or 0.0),
        )


def scan_entries(root: Path | str) -> list[FileEntry]:
    """扫作用域根，产出排除后的 (相对路径, 哈希, 大小, mtime) 列表。"""
    root = Path(root)
    out: list[FileEntry] = []
    for p in iter_workspace_files(root):
        rel = normalize_rel(p, root)
        if rel is None:
            continue
        try:
            stat = p.stat()
        except OSError:  # 竞态删除
            continue
        out.append(
            FileEntry(
                rel=rel,
                sha256=hash_file(p),
                size=int(stat.st_size),
                mtime=float(stat.st_mtime),
            )
        )
    out.sort(key=lambda e: e.rel)
    return out


# --------------------------------------------------------------------------- #
# 纯函数：安全
# --------------------------------------------------------------------------- #


def safe_join(root: Path | str, rel_path: str) -> Path:
    """把相对路径安全拼到作用域根下；越界 / 绝对路径 / 符号链外逃全部抛错。"""
    root = Path(root)
    rel = str(rel_path)
    if not rel:
        raise PathEscapeError("空相对路径")
    candidate = Path(rel.replace("\\", "/"))
    if candidate.is_absolute():
        raise PathEscapeError("恢复路径必须是相对路径: %s" % rel)
    if any(part == ".." for part in candidate.parts):
        raise PathEscapeError("恢复路径不得包含 '..': %s" % rel)
    target = root / candidate
    try:
        resolved = target.resolve()
    except (OSError, RuntimeError):
        raise PathEscapeError("路径解析失败: %s" % rel)
    root_resolved = root.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise PathEscapeError(
            "路径越出检查点作用域: %s (根=%s)" % (rel, root_resolved)
        )
    return target


def is_secret_path(path: Path | str) -> bool:
    """路径本身是否属于密钥/凭据类（按词表判断，纯函数）。"""
    p = Path(str(path))
    if p.name in EXCLUDE_FILE_NAMES:
        return True
    lowered = p.name.lower()
    if any(lowered.endswith(s) for s in EXCLUDE_SUFFIXES if s in (
        ".key", ".pem", ".p12", ".pfx", ".jks", ".keystore", ".crt", ".der"
    )):
        return True
    return any(part in EXCLUDE_DIR_NAMES for part in p.parts[:-1])


def forbidden_roots(
    *,
    working_dir: Path | str,
    system_dir: Path | str,
    secret_dir: Path | str,
    log_dir: Path | str,
    audit_log_dir: Path | str,
    tmp_dir: Path | str,
    backup_dir: Path | str,
    media_dir: Path | str,
    models_dir: Path | str,
    plugins_dir: Path | str,
    custom_channels_dir: Path | str,
    local_models_dir: Path | str,
) -> list[Path]:
    """数据卷里禁止作为检查点作用域的目录（显式传参，可单测）。"""
    return [
        Path(working_dir),
        Path(system_dir),
        Path(secret_dir),
        Path(log_dir),
        Path(audit_log_dir),
        Path(tmp_dir),
        Path(backup_dir),
        Path(media_dir),
        Path(models_dir),
        Path(plugins_dir),
        Path(custom_channels_dir),
        Path(local_models_dir),
    ]


def guard_scope_root(
    root: Path | str,
    *,
    workspaces_dir: Path | str,
    forbidden: Sequence[Path | str] = (),
) -> Path:
    """确认作用域根合法：必须在用户工作区内，且不在任何禁止目录内。

    抛 ``ScopeForbiddenError`` 而不是静默跳过——"恢复"是破坏性动作，
    作用域含糊绝不能放行。
    """
    root = Path(root).expanduser()
    try:
        resolved = root.resolve()
    except (OSError, RuntimeError) as exc:
        raise ScopeForbiddenError("作用域根无法解析: %s" % exc)
    ws = Path(workspaces_dir).expanduser().resolve()
    if resolved != ws and ws not in resolved.parents:
        raise ScopeForbiddenError(
            "检查点作用域必须在用户工作区内: 根=%s 工作区=%s" % (resolved, ws)
        )
    for bad in forbidden:
        bad_p = Path(bad).expanduser()
        try:
            bad_resolved = bad_p.resolve()
        except (OSError, RuntimeError):
            continue
        if resolved == bad_resolved or bad_resolved in resolved.parents:
            raise ScopeForbiddenError(
                "检查点作用域落在禁止目录内（数据卷系统目录/密钥目录）: "
                "根=%s 命中=%s" % (resolved, bad_resolved)
            )
    return resolved


def default_forbidden_roots() -> list[Path]:
    """按运行时常量给出禁止目录（运行期取真值，不在 import 期固化）。"""
    from ..constant import (
        AUDIT_LOG_DIR,
        BACKUP_DIR,
        CUSTOM_CHANNELS_DIR,
        DEFAULT_LOCAL_PROVIDER_DIR,
        DEFAULT_MEDIA_DIR,
        LOG_DIR,
        MODELS_DIR,
        PLUGINS_DIR,
        SECRET_DIR,
        SYSTEM_DIR,
        TMP_DIR,
        WORKING_DIR,
    )

    return forbidden_roots(
        working_dir=WORKING_DIR,
        system_dir=SYSTEM_DIR,
        secret_dir=SECRET_DIR,
        log_dir=LOG_DIR,
        audit_log_dir=AUDIT_LOG_DIR,
        tmp_dir=TMP_DIR,
        backup_dir=BACKUP_DIR,
        media_dir=DEFAULT_MEDIA_DIR,
        models_dir=MODELS_DIR,
        plugins_dir=PLUGINS_DIR,
        custom_channels_dir=CUSTOM_CHANNELS_DIR,
        local_models_dir=DEFAULT_LOCAL_PROVIDER_DIR,
    )


def validate_username(username: str) -> str:
    """用户名必须是干净的一层目录名（挡掉 ``../``、绝对路径、空名）。"""
    name = str(username or "").strip()
    if not name:
        raise CheckpointPathError("用户名为空")
    if "/" in name or "\\" in name:
        raise CheckpointPathError("用户名含路径分隔符: %s" % name)
    if name in (".", ".."):
        raise CheckpointPathError("非法用户名: %s" % name)
    if name.startswith("."):
        raise CheckpointPathError("非法用户名: %s" % name)
    return name
