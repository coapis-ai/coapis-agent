# -*- coding: utf-8 -*-
"""统一访问控制存储 — 频道白名单/黑名单/待审批管理。

借鉴 CoApis AccessControlStore 模式，适配 CoApis 多用户隔离场景：
- 每个用户 workspace 有独立的 access_control.json
- 线程安全的持久化存储
- 支持白名单/黑名单/待审批三种状态
- 从现有 _allow_from 配置自动迁移
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

ACCESS_CONTROL_FILE = "access_control.json"


class PendingEntry:
    """待审批用户条目。"""

    __slots__ = ("user_id", "channel", "timestamp", "first_message", "remark")

    def __init__(
        self,
        user_id: str,
        channel: str,
        timestamp: float,
        first_message: str = "",
        remark: str = "",
    ):
        self.user_id = user_id
        self.channel = channel
        self.timestamp = timestamp
        self.first_message = first_message
        self.remark = remark

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "channel": self.channel,
            "timestamp": self.timestamp,
            "first_message": self.first_message,
            "remark": self.remark,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PendingEntry":
        return cls(
            user_id=data["user_id"],
            channel=data["channel"],
            timestamp=data.get("timestamp", 0.0),
            first_message=data.get("first_message", ""),
            remark=data.get("remark", ""),
        )


class ChannelACL:
    """单个频道的访问控制数据。

    whitelist/blacklist: Dict[str, str]，key=user_id, value=remark（备注）。
    兼容旧格式 List[str]（自动迁移为 dict）。
    """

    def __init__(
        self,
        whitelist: Optional[Dict[str, str]] = None,
        blacklist: Optional[Dict[str, str]] = None,
        pending: Optional[List[PendingEntry]] = None,
    ):
        self.whitelist: Dict[str, str] = whitelist or {}
        self.blacklist: Dict[str, str] = blacklist or {}
        self.pending: List[PendingEntry] = pending or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "whitelist": self.whitelist,
            "blacklist": self.blacklist,
            "pending": [p.to_dict() for p in self.pending],
        }

    @classmethod
    def _parse_list_or_dict(cls, raw: Any) -> Dict[str, str]:
        """解析 whitelist/blacklist，兼容旧 list 格式。"""
        if isinstance(raw, dict):
            return {str(k): str(v) for k, v in raw.items()}
        if isinstance(raw, list):
            return {str(item): "" for item in raw}
        return {}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChannelACL":
        return cls(
            whitelist=cls._parse_list_or_dict(data.get("whitelist", {})),
            blacklist=cls._parse_list_or_dict(data.get("blacklist", {})),
            pending=[
                PendingEntry.from_dict(p) for p in data.get("pending", [])
            ],
        )


class AccessControlStore:
    """线程安全的 per-workspace 访问控制持久化存储。"""

    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()
        self._data: Dict[str, ChannelACL] = {}
        self._last_mtime: float = 0.0
        self._load()

    # ── 持久化 ─────────────────────────────────────────────────

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            self._last_mtime = self._path.stat().st_mtime
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._data = {k: ChannelACL.from_dict(v) for k, v in raw.items()}
        except Exception:
            logger.exception("Failed to load access_control.json from %s", self._path)

    def _reload_if_stale(self) -> None:
        """如果文件被外部更新（如 workspace 热重载），重新加载。"""
        try:
            if not self._path.exists():
                return
            current_mtime = self._path.stat().st_mtime
            if current_mtime > self._last_mtime:
                self._load()
        except OSError:
            pass

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = {k: v.to_dict() for k, v in self._data.items()}
            self._path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            self._last_mtime = self._path.stat().st_mtime
        except Exception:
            logger.exception("Failed to save access_control.json to %s", self._path)

    def _acl(self, channel: str) -> ChannelACL:
        """获取或创建频道 ACL（需在 _lock 内调用）。"""
        if channel not in self._data:
            self._data[channel] = ChannelACL()
        return self._data[channel]

    # ── 访问检查 ───────────────────────────────────────────────

    def check_access(
        self,
        channel: str,
        user_id: str,
        is_group: bool = False,
        dm_policy: str = "open",
        group_policy: str = "open",
        allow_from: Optional[List[str]] = None,
    ) -> tuple[bool, str]:
        """检查用户是否被允许访问。

        优先级：黑名单 > 白名单 > allow_from > policy

        Returns:
            (allowed, error_message)
        """
        with self._lock:
            self._reload_if_stale()
            acl = self._data.get(channel)

            # 黑名单 — 最高优先级
            if acl and user_id in acl.blacklist:
                return False, "您已被加入黑名单，请联系管理员。"

            # 白名单 — 直接放行
            if acl and user_id in acl.whitelist:
                return True, ""

            # 兼容旧 allow_from 配置
            if allow_from and user_id not in allow_from:
                return False, "您不在允许列表中。"

            # 策略检查
            if is_group and group_policy == "closed":
                return False, "群聊消息已关闭。"
            if not is_group and dm_policy == "closed":
                return False, "私聊消息已关闭。"

            # 待审批模式：如果频道配置了 pending_approval，添加到待审批
            # （由调用方决定是否启用 pending 模式）

            return True, ""

    # ── 白名单管理 ─────────────────────────────────────────────

    def add_to_whitelist(
        self,
        channel: str,
        user_id: str,
        remark: str = "",
    ) -> None:
        with self._lock:
            acl = self._acl(channel)
            acl.whitelist[user_id] = remark
            acl.blacklist.pop(user_id, None)
            acl.pending = [
                p
                for p in acl.pending
                if not (p.user_id == user_id and p.channel == channel)
            ]
            self._save()

    def remove_from_whitelist(self, channel: str, user_id: str) -> None:
        with self._lock:
            self._acl(channel).whitelist.pop(user_id, None)
            self._save()

    def set_whitelist(self, channel: str, user_ids: List[str]) -> None:
        with self._lock:
            acl = self._acl(channel)
            new_wl = {uid: acl.whitelist.get(uid, "") for uid in user_ids}
            acl.whitelist = new_wl
            self._save()

    def get_whitelist(self, channel: str) -> Dict[str, str]:
        with self._lock:
            self._reload_if_stale()
            acl = self._data.get(channel)
            return dict(acl.whitelist) if acl else {}

    # ── 黑名单管理 ─────────────────────────────────────────────

    def add_to_blacklist(
        self,
        channel: str,
        user_id: str,
        remark: str = "",
    ) -> None:
        with self._lock:
            acl = self._acl(channel)
            acl.blacklist[user_id] = remark
            acl.whitelist.pop(user_id, None)
            acl.pending = [
                p
                for p in acl.pending
                if not (p.user_id == user_id and p.channel == channel)
            ]
            self._save()

    def remove_from_blacklist(self, channel: str, user_id: str) -> None:
        with self._lock:
            self._acl(channel).blacklist.pop(user_id, None)
            self._save()

    def set_blacklist(self, channel: str, user_ids: List[str]) -> None:
        with self._lock:
            acl = self._acl(channel)
            new_bl = {uid: acl.blacklist.get(uid, "") for uid in user_ids}
            acl.blacklist = new_bl
            self._save()

    def get_blacklist(self, channel: str) -> Dict[str, str]:
        with self._lock:
            self._reload_if_stale()
            acl = self._data.get(channel)
            return dict(acl.blacklist) if acl else {}

    # ── 待审批管理 ─────────────────────────────────────────────

    def add_pending(
        self,
        channel: str,
        user_id: str,
        first_message: str = "",
    ) -> None:
        with self._lock:
            acl = self._acl(channel)
            for existing in acl.pending:
                if existing.user_id == user_id and existing.channel == channel:
                    return
            acl.pending.append(
                PendingEntry(
                    user_id=user_id,
                    channel=channel,
                    timestamp=time.time(),
                    first_message=first_message[:200],
                ),
            )
            self._save()

    def get_all_pending(self) -> List[Dict[str, Any]]:
        with self._lock:
            self._reload_if_stale()
            result: List[Dict[str, Any]] = []
            for acl in self._data.values():
                result.extend(p.to_dict() for p in acl.pending)
            result.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
            return result

    def approve_pending(
        self,
        channel: str,
        user_id: str,
        remark: str = "",
    ) -> bool:
        """批准待审批用户，加入白名单。"""
        with self._lock:
            acl = self._acl(channel)
            effective_remark = remark
            if not effective_remark:
                for entry in acl.pending:
                    if entry.user_id == user_id and entry.channel == channel:
                        effective_remark = entry.remark or f"approved from pending"
                        break
            acl.pending = [
                p
                for p in acl.pending
                if not (p.user_id == user_id and p.channel == channel)
            ]
            acl.whitelist[user_id] = effective_remark
            self._save()
            return True

    def reject_pending(
        self,
        channel: str,
        user_id: str,
        remark: str = "",
    ) -> bool:
        """拒绝待审批用户，加入黑名单。"""
        with self._lock:
            acl = self._acl(channel)
            effective_remark = remark
            if not effective_remark:
                for entry in acl.pending:
                    if entry.user_id == user_id and entry.channel == channel:
                        effective_remark = entry.remark
                        break
            acl.pending = [
                p
                for p in acl.pending
                if not (p.user_id == user_id and p.channel == channel)
            ]
            acl.blacklist[user_id] = effective_remark or "rejected"
            acl.whitelist.pop(user_id, None)
            self._save()
            return True

    def dismiss_pending(self, channel: str, user_id: str) -> bool:
        """移除待审批（不加入任何列表）。"""
        with self._lock:
            acl = self._acl(channel)
            before = len(acl.pending)
            acl.pending = [
                p
                for p in acl.pending
                if not (p.user_id == user_id and p.channel == channel)
            ]
            if len(acl.pending) < before:
                self._save()
                return True
            return False

    # ── 备注管理 ───────────────────────────────────────────────

    def update_remark(
        self,
        channel: str,
        user_id: str,
        remark: str,
    ) -> bool:
        with self._lock:
            acl = self._acl(channel)
            if user_id in acl.whitelist:
                acl.whitelist[user_id] = remark
                self._save()
                return True
            if user_id in acl.blacklist:
                acl.blacklist[user_id] = remark
                self._save()
                return True
            return False

    # ── 从旧配置迁移 ──────────────────────────────────────────

    def import_allow_from(
        self,
        channel: str,
        allow_from: Set[str],
    ) -> None:
        """将旧 allow_from 配置导入白名单。"""
        if not allow_from:
            return
        with self._lock:
            acl = self._acl(channel)
            imported = 0
            for uid in allow_from:
                if uid not in acl.whitelist:
                    acl.whitelist[uid] = "migrated from allow_from"
                    imported += 1
            if imported:
                self._save()
                logger.info(
                    "Imported %d allow_from entries to whitelist for channel %s",
                    imported,
                    channel,
                )

    # ── 摘要 ──────────────────────────────────────────────────

    def get_summary(self) -> Dict[str, Any]:
        """返回所有频道的 ACL 摘要。"""
        with self._lock:
            self._reload_if_stale()
            result = {}
            for ch, acl in self._data.items():
                result[ch] = {
                    "whitelist_count": len(acl.whitelist),
                    "blacklist_count": len(acl.blacklist),
                    "pending_count": len(acl.pending),
                }
            return result

    def get_channel_detail(self, channel: str) -> Dict[str, Any]:
        """返回单个频道的完整 ACL 详情。"""
        with self._lock:
            self._reload_if_stale()
            acl = self._data.get(channel)
            if acl is None:
                return {
                    "whitelist": {},
                    "blacklist": {},
                    "pending": [],
                }
            return acl.to_dict()


# ── Per-workspace store 注册表 ──────────────────────────────────

_stores: Dict[str, AccessControlStore] = {}
_stores_lock = threading.Lock()


def get_access_control_store(
    workspace_dir: Path,
) -> AccessControlStore:
    """获取或创建指定 workspace 的 AccessControlStore。"""
    with _stores_lock:
        key = str(workspace_dir.resolve())
        if key not in _stores:
            path = workspace_dir / ACCESS_CONTROL_FILE
            _stores[key] = AccessControlStore(path)
        return _stores[key]


def clear_store_cache() -> None:
    """清空 store 缓存（测试用）。"""
    with _stores_lock:
        _stores.clear()
