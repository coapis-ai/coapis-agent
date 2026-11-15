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

"""检查点服务（B5-A 最小版）：创建 / 预览 / 恢复。

与台账的对接是**单向读台账、单向走台账公开入口**，不另立版本体系：

* 作用域根、相对路径口径来自 ``file_ledger``（见 ``paths.py``）；
* 恢复成功后逐文件调 ``file_ledger.record_file_event(source="restore")``——
  它是 fire-and-forget 的公开入口，绝不抛；版本号由
  ``resource_ledger.register`` 按 size/mtime 变化推进，检查点不数自己的版本；
* 预览里附带台账的 ``upload_version``（该文件第几版），口径与上传提示语同源。

恢复的两条红线：

1. **无 confirm 不放行**（``ConfirmRequiredError`` -> HTTP 400）；
2. **恢复前必留底**：先对当下工作区生成 ``kind=pre_restore`` 的检查点，
   再动盘；缺任何内容块则整体中止，绝不"半恢复"。
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

from .models import (
    DIFF_CHANGED,
    DIFF_EXTRA,
    DIFF_MISSING,
    DIFF_UNCHANGED,
    KIND_MANUAL,
    KIND_PRE_RESTORE,
    Checkpoint,
    DiffResult,
    RestoreOutcome,
    RestorePlan,
)
from .paths import (
    CheckpointPathError,
    FileEntry,
    ScopeForbiddenError,
    default_forbidden_roots,
    guard_scope_root,
    hash_file,
    normalize_rel,
    safe_join,
    scan_entries,
    validate_username,
    workspace_files_root,
)
from .storage import BlobMissingError, CheckpointStore, new_checkpoint_id

logger = logging.getLogger(__name__)

#: 单次快照的文件数上限（防止把整棵数据卷当工作区卷进来）。
MAX_FILES = int(os.getenv("COAPIS_CHECKPOINTS_MAX_FILES", "5000") or 5000)

_PRE_RESTORE_NOTE = "恢复前自动检查点（执行恢复前对当下工作区留底）"


class ConfirmRequiredError(ValueError):
    """恢复类破坏性操作缺少显式授权。"""


class CheckpointNotFoundError(KeyError):
    """检查点不存在（或不属于当前作用域）。"""


class CheckpointIntegrityError(RuntimeError):
    """仓库不完整：索引指向的内容块缺失，恢复整体中止。"""


class TooManyFilesError(RuntimeError):
    """作用域文件数越界——通常意味着作用域选错了。"""


class CheckpointService:
    """一个用户的检查点服务（按用户名隔离，天然多租户）。"""

    def __init__(
        self,
        username: str,
        *,
        workspaces_dir: Path | str | None = None,
        store_root: Path | str | None = None,
        scope_root: Path | str | None = None,
    ) -> None:
        from ..constant import WORKSPACES_DIR as _WS

        self.username = validate_username(username)
        self.workspaces_dir = Path(workspaces_dir or _WS)
        self.scope_root = Path(
            scope_root
            if scope_root is not None
            else workspace_files_root(self.username, self.workspaces_dir)
        )
        self.scope_root = guard_scope_root(
            self.scope_root,
            workspaces_dir=self.workspaces_dir,
            forbidden=default_forbidden_roots(),
        )
        self.store = CheckpointStore(
            Path(store_root)
            if store_root is not None
            else self.workspaces_dir / self.username / "checkpoints"
        )

    # ── 创建 ──────────────────────────────────────────────────────────
    def create_checkpoint(
        self,
        *,
        session: Optional[str] = None,
        note: str = "",
        kind: str = KIND_MANUAL,
        pre_restore_of: Optional[str] = None,
        dry_run: bool = False,
    ) -> Checkpoint:
        """对当下工作区做只读指纹快照。``dry_run=True`` 时**不落任何东西**。"""
        entries = scan_entries(self.scope_root)
        if len(entries) > MAX_FILES:
            raise TooManyFilesError(
                "作用域内文件 %d 个，超过上限 %d（COAPIS_CHECKPOINTS_MAX_FILES）"
                "——作用域可能选错，检查点只覆盖工作区文件目录"
                % (len(entries), MAX_FILES)
            )
        cp = Checkpoint(
            checkpoint_id=new_checkpoint_id(),
            username=self.username,
            created_at=time.time(),
            files={e.rel: e.to_dict() for e in entries},
            session=session,
            note=str(note or ""),
            kind=str(kind or KIND_MANUAL),
            store_root=str(self.store.root),
        )
        cp.pre_restore_of = pre_restore_of
        for entry in entries:
            self.store.put_file(
                entry.sha256,
                safe_join(self.scope_root, entry.rel),
                dry_run=dry_run,
            )
        self.store.write_manifest(cp, dry_run=dry_run)
        self.store.append_index(cp, dry_run=dry_run)
        return cp

    # ── 列出 ──────────────────────────────────────────────────────────
    def list_checkpoints(
        self,
        *,
        session: Optional[str] = None,
        limit: int = 50,
    ) -> list[Checkpoint]:
        items = self.store.iter_checkpoints()
        if session is not None:
            items = [c for c in items if c.session == session]
        limit = max(1, min(int(limit or 50), 200))
        return items[:limit]

    def get_checkpoint(self, checkpoint_id: str) -> Checkpoint:
        try:
            cp = self.store.load_checkpoint(str(checkpoint_id))
        except ValueError as exc:
            # 调用方传的 id 千奇百怪（前端拼错、扫描器乱试）都是「不存在」，
            # 不是服务端故障 —— 统一成 404 语义，绝不让它冒成 500。
            raise CheckpointNotFoundError(
                "检查点不存在: %s（%s）" % (checkpoint_id, exc)
            ) from exc
        if cp is None:
            raise CheckpointNotFoundError(
                "检查点不存在: %s" % checkpoint_id
            )
        return cp

    # ── 预览（只读） ──────────────────────────────────────────────────
    def preview_restore(
        self, checkpoint_id: str, *, with_ledger_version: bool = True
    ) -> RestorePlan:
        """算出"要回滚哪些文件、哈希怎么差"。**不写任何东西**。"""
        cp = self.get_checkpoint(checkpoint_id)
        current = {e.rel: e for e in scan_entries(self.scope_root)}
        diffs: list[DiffResult] = []
        for rel in sorted(set(cp.files) | set(current)):
            snap = cp.files.get(rel)
            now = current.get(rel)
            if snap is not None and now is None:
                diffs.append(
                    DiffResult(
                        rel=rel,
                        kind=DIFF_MISSING,
                        sha_checkpoint=str(snap.get("sha256")),
                        size_checkpoint=int(snap.get("size") or 0),
                    )
                )
                continue
            if snap is None and now is not None:
                diffs.append(
                    DiffResult(
                        rel=rel,
                        kind=DIFF_EXTRA,
                        sha_current=now.sha256,
                        size_current=now.size,
                    )
                )
                continue
            assert snap is not None and now is not None
            if str(snap.get("sha256")) == now.sha256:
                diffs.append(
                    DiffResult(
                        rel=rel,
                        kind=DIFF_UNCHANGED,
                        sha_checkpoint=now.sha256,
                        sha_current=now.sha256,
                        size_checkpoint=int(snap.get("size") or 0),
                        size_current=now.size,
                    )
                )
            else:
                diffs.append(
                    DiffResult(
                        rel=rel,
                        kind=DIFF_CHANGED,
                        sha_checkpoint=str(snap.get("sha256")),
                        sha_current=now.sha256,
                        size_checkpoint=int(snap.get("size") or 0),
                        size_current=now.size,
                    )
                )

        missing: list[str] = []
        for d in diffs:
            if not d.will_restore:
                continue
            digest = str(d.sha_checkpoint or "")
            if digest and not self.store.has_blob(digest):
                missing.append(digest)
        missing = sorted(set(missing))
        plan = RestorePlan(
            checkpoint_id=cp.checkpoint_id,
            username=self.username,
            diffs=diffs,
            missing_blobs=missing,
            dry_run=True,
            created_at=time.time(),
            reason=(
                "内容块缺失，恢复将整体中止" if missing else "计划可执行"
            ),
        )
        if with_ledger_version:
            plan.ledger_versions = self._ledger_versions(
                [d.rel for d in plan.to_restore]
            )
        return plan

    # ── 恢复 ──────────────────────────────────────────────────────────
    def restore(
        self,
        checkpoint_id: str,
        *,
        confirm: bool = False,
        session: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> RestoreOutcome:
        """执行回滚。**必须 confirm=True**，且先自动生成恢复前检查点。"""
        if confirm is not True:
            raise ConfirmRequiredError(
                "恢复是破坏性操作，必须显式授权：请求体里带 \"confirm\": true"
            )
        cp = self.get_checkpoint(checkpoint_id)
        plan = self.preview_restore(checkpoint_id)
        if not plan.writable:
            raise CheckpointIntegrityError(
                "检查点 %s 的内容块缺失 %d 个，恢复已整体中止（不做半恢复）: %s"
                % (
                    cp.checkpoint_id,
                    len(plan.missing_blobs),
                    ", ".join(plan.missing_blobs[:3]),
                )
            )

        # 红线：动手之前先对当下工作区留底
        pre = self.create_checkpoint(
            session=session,
            note=_PRE_RESTORE_NOTE,
            kind=KIND_PRE_RESTORE,
            pre_restore_of=cp.checkpoint_id,
            dry_run=False,
        )

        restored: list[str] = []
        skipped: list[str] = []
        total = 0
        for d in plan.diffs:
            if not d.will_restore:
                skipped.append(d.rel)
                continue
            digest = str(d.sha_checkpoint or "")
            data = self.store.read_blob(digest)
            target = safe_join(self.scope_root, d.rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_file(target, data)
            if hash_file(target) != digest:
                raise CheckpointIntegrityError(
                    "写后校验失败: %s（期望 %s）" % (d.rel, digest)
                )
            restored.append(d.rel)
            total += len(data)

        registered = self._register_ledger(restored, session, chat_id)
        outcome = RestoreOutcome(
            checkpoint_id=cp.checkpoint_id,
            pre_restore_checkpoint_id=pre.checkpoint_id,
            restored=restored,
            skipped=skipped,
            ledger_registered=registered,
            total_bytes=total,
        )
        logger.info(
            "检查点恢复完成: user=%s cp=%s pre=%s restored=%d",
            self.username,
            cp.checkpoint_id,
            pre.checkpoint_id,
            len(restored),
        )
        return outcome

    # ── 台账对接 ──────────────────────────────────────────────────────
    def _ledger_versions(self, rels: list[str]) -> dict[str, int]:
        """台账口径的"第几版"（``upload_version``）。台账不可用时返回空表。"""
        if not rels:
            return {}
        out: dict[str, int] = {}
        try:
            from ..foundation.file_ledger import get_file_ledger

            ledger = get_file_ledger()
            for rel in rels[:200]:
                abs_path = str(safe_join(self.scope_root, rel))
                out[rel] = int(ledger.upload_version(self.username, abs_path))
        except Exception as exc:  # pragma: no cover - 台账缺失只降级
            logger.debug("检查点预览取台账版次失败（忽略）: %s", exc)
            return {}
        return out

    def _register_ledger(
        self,
        rels: list[str],
        session: Optional[str],
        chat_id: Optional[str],
    ) -> list[str]:
        """恢复落盘的文件逐条回灌台账（``source="restore"``，fire-and-forget）。

        版次推进由 ``resource_ledger.register`` 负责——检查点数自己的版本号
        就是第二套真相，坚决不数。
        """
        if not rels:
            return []
        done: list[str] = []
        try:
            from ..foundation.file_ledger import record_file_event
        except Exception as exc:  # pragma: no cover - 台账模块缺失
            logger.debug("台账模块不可用（忽略）: %s", exc)
            return done
        for rel in rels:
            try:
                abs_path = str(safe_join(self.scope_root, rel))
                ok = record_file_event(
                    self.username,
                    abs_path,
                    source="restore",
                    session_id=session,
                    chat_id=chat_id,
                )
                if ok:
                    done.append(rel)
            except Exception as exc:  # pragma: no cover - 单条失败不连坐
                logger.debug("检查点恢复回灌台账失败 %s: %s", rel, exc)
        return done


def _atomic_write_file(target: Path, data: bytes) -> None:
    """恢复落盘：临时文件 + ``os.replace``，不留半截文件。"""
    import uuid

    tmp = target.parent / (".tmp-restore-%s-%s" % (os.getpid(),
                                                   uuid.uuid4().hex))
    try:
        with open(str(tmp), "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(str(tmp), str(target))
    finally:
        if tmp.exists():
            try:
                os.unlink(str(tmp))
            except OSError:  # pragma: no cover
                pass


__all__ = [
    "CheckpointIntegrityError",
    "CheckpointNotFoundError",
    "CheckpointPathError",
    "CheckpointService",
    "ConfirmRequiredError",
    "ScopeForbiddenError",
    "TooManyFilesError",
    "BlobMissingError",
]
