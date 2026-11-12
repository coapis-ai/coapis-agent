# -*- coding: utf-8 -*-
"""版本更新查询接口 — 「只查询、只展示」，更新动作仍由管理员在部署端执行。

设计约束（v16 方案 F7，小蜜蜂拍板）：
- **永不阻断**：无网络 / gitee 超时 / 解析失败一律降级为 offline/error 应答，
  不影响聊天与页面加载，前端据此静默处理；
- **只读**：本接口不执行任何升级动作；
- **服务器侧缓存**（TTL 6 小时，失败也记入）：避免每次页面加载都打 gitee API
  被限流；缓存命中时零外呼；
- gitee 地址**只此一处**（本模块），全仓不得再有第二份。

releases.json（更新要点说明，可选）放在**包目录内**（与 __version__.py 同级，
随包挂载进容器），运维可直接编辑该文件补充 notes。
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import APIRouter

from ...__version__ import __version__

logger = logging.getLogger(__name__)

router = APIRouter(tags=["update"])

GITEE_REPO = "ouerlai/coapis-agent"
GITEE_RELEASES_API = f"https://gitee.com/api/v5/repos/{GITEE_REPO}/releases"
GITEE_TAGS_API = f"https://gitee.com/api/v5/repos/{GITEE_REPO}/tags"
GITEE_RELEASES_PAGE = f"https://gitee.com/{GITEE_REPO}/releases"
_HTTP_TIMEOUT_S = 5.0
_CACHE_TTL_S = 6 * 3600.0

# 服务器侧缓存（进程内）：成功与失败都记录，失败时保留上一次成功数据
_cache: dict[str, Any] = {"ts": 0.0, "ok": None}

# 更新要点说明文件：包目录内（部署侧可直接编辑，缺失则用通用标题）
# 本文件位于 coapis/app/routers/ 下，包根是 parents[2]（coapis/）
RELEASES_NOTES_FILE = Path(__file__).resolve().parents[2] / "releases.json"


def parse_version(v: str) -> tuple:
    """'2.0.25-beta.1' -> (2, 0, 25, 1)；缺省段补 0，非数字段截断。"""
    parts = re.split(r"[.\-]", str(v).strip().lstrip("v"))
    nums: list[int] = []
    for p in parts:
        m = re.match(r"\d+", p or "")
        if not m:
            break
        nums.append(int(m.group()))
    while len(nums) < 4:
        nums.append(0)
    return tuple(nums[:4])


def _ver_key(v: str) -> tuple:
    """比较用排序键：正式版排在同号 beta 之前（beta.N 取 N，正式版取哨兵大值）。"""
    t = list(parse_version(v))
    m = re.search(r"beta[.\-]?(\d+)", str(v).lower())
    t[3] = int(m.group(1)) if m else 10**9
    return tuple(t)


def _load_notes() -> dict:
    """读取 releases.json（{版本: {notes:[...]}}）；任何异常按空处理。"""
    try:
        with open(RELEASES_NOTES_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 - 更新要点缺失属正常情形
        return {}


def _fetch_latest() -> dict:
    """调 gitee API 取最新 release；任何失败都返回 status，不抛异常。"""
    try:
        resp = httpx.get(
            GITEE_RELEASES_API,
            timeout=_HTTP_TIMEOUT_S,
            params={"per_page": 10, "order": "desc"},
        )
    except httpx.TimeoutException:
        return {"status": "offline", "message": "检查更新超时，请稍后再试"}
    except Exception as exc:  # noqa: BLE001 - 网络异常属常态，不可阻断主流程
        logger.debug("更新检查失败（不阻断）: %s", exc)
        return {"status": "offline", "message": "无法连接更新服务器"}

    if resp.status_code != 200:
        fb = _latest_from_tags()
        if fb is not None:
            return fb
        return {"status": "error", "message": f"gitee API 返回 {resp.status_code}"}

    try:
        releases = resp.json()
        if not isinstance(releases, list) or not releases:
            fb = _latest_from_tags()
            if fb is not None:
                return fb
            return {"status": "error", "message": "gitee API 返回空列表"}
        releases.sort(key=lambda r: _ver_key(r.get("tag_name", "0")), reverse=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("更新检查结果解析失败: %s", exc)
        return {"status": "error", "message": "更新检查结果解析失败"}

    top = releases[0]
    tag = str(top.get("tag_name", "")).lstrip("v")
    if not tag:
        return {"status": "error", "message": "最新发布版标签为空"}

    notes_data = _load_notes()
    entry = notes_data.get(tag) or {}
    notes = list(entry.get("notes") or [])
    for line in (top.get("name") or "", top.get("body") or ""):
        line = (line or "").strip()
        if line and line not in notes:
            notes.append(line)

    return {
        "status": "ok",
        "installed_version": __version__,
        "has_update": _ver_key(tag) > _ver_key(__version__),
        "latest": {
            "version": tag,
            "title": top.get("name") or "",
            "release_date": (top.get("created_at") or "")[:10],
            "url": top.get("html_url") or GITEE_RELEASES_PAGE,
            "notes": notes[:8],
        },
    }


def _latest_from_tags() -> Optional[dict]:
    """releases 列表不可用时的兜底：从 git 标签取最新版（信息少但没有盲区）。"""
    try:
        resp = httpx.get(
            GITEE_TAGS_API,
            timeout=_HTTP_TIMEOUT_S,
            params={"per_page": 100},
        )
        if resp.status_code != 200:
            return None
        names = [
            str(t.get("name", "")).lstrip("v")
            for t in resp.json()
            if isinstance(t, dict) and str(t.get("name", "")).lstrip("v")[:1].isdigit()
        ]
        if not names:
            return None
        tag = max(names, key=_ver_key)
    except Exception as exc:  # noqa: BLE001
        logger.debug("标签兜底查询失败（不阻断）: %s", exc)
        return None

    notes_data = _load_notes()
    entry = notes_data.get(tag) or {}
    return {
        "status": "ok",
        "installed_version": __version__,
        "has_update": _ver_key(tag) > _ver_key(__version__),
        "latest": {
            "version": tag,
            "title": f"CoApis v{tag} 发布",
            "release_date": "",
            "url": GITEE_RELEASES_PAGE,
            "notes": list(entry.get("notes") or [])[:8],
        },
    }


@router.get("/updates")
async def check_updates() -> dict:
    """查询是否有最新版（只读、永不阻断、服务器侧 6 小时缓存）。"""
    now = time.monotonic()
    cached = _cache.get("ok")
    if cached is not None and now - _cache["ts"] < _CACHE_TTL_S:
        return {**cached, "cached": True}

    result = _fetch_latest()
    if result.get("status") == "ok":
        _cache.update(ts=now, ok=result)
        return result

    # 失败：保留上一次成功数据继续供给（宁旧勿断）
    if cached is not None:
        return {**cached, "cached": True, "degraded_from": result.get("status")}
    _cache["ts"] = now  # 失败也记入 TTL，避免疯狂外呼
    return result
