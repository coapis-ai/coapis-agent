# -*- coding: utf-8 -*-
"""会话目录解析 —— ``files/{YYYY-MM}/{YYYY-MM-DD}_{任务}/``，目录由系统决定。

设计要点（方案：tech_docs/我的空间目录规划_方案与实施计划_20261022.md）
---------------------------------------------------------------------
- **目录不是模型的决定。** 模型只给文件名，落点由本模块按会话身份计算。
  理由：实测 160 个会话里 53% 产出 ≥2 种文件类型，"类型目录"必然导致
  同一会话的产出散进多个目录 —— 正是用户要避开的"到处找文件"。
- **会话是一级组织单位**，与"会话引用/产出直链"同一身份口径
  （``chat_id`` → 会话标题）。
- **月层常驻**（防按天目录平铺爆炸：实测 12 目录/月 → 12 个月 144 个）；
  **日期层按需**：会话目录内已有 ≥15 个文件才加当天层，同会话 ≤15 文件
  直接平铺（实测命中约 10%，多数会话一辈子用不到日期层）。
- **目录名是快照**：建目录当天解析一次会话标题并固化进目录名，此后
  **永不改名** —— 会话可被 PUT 改名，实时解析会让历史直链 404。
- **无会话身份 → 月层平铺**，与历史行为一致，零回归。
- 任何异常一律降级为"不注入目录"，绝不阻断写文件。

同步/异步：标题解析要走 ChatManager（异步），因此 ``resolve_session_dir``
是协程；调用方（写类工具）本身都是 async。
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── 可调参数（集中在此，便于按使用数据调） ──────────────────────────
#: 会话目录内已有文件数达到该值，才启用"日期_任务"层
MIN_NEW_FILES = 15
#: 无日期前缀的目录视为会话目录的宽容天数（跨周末/长假的长会话）
SESSION_DIR_WINDOW_DAYS = 7
#: 会话标题缓存时长（秒）。改名后最长 30s 生效，可接受 —— 目录名是快照，
#: 只有"新建目录"才需要标题。
TITLE_CACHE_TTL = 30.0
#: 模型给出的相对路径超过该段数时不再建深层目录，只取文件名
MAX_PATH_SEGMENTS = 4

MONTH_FMT = "%Y-%m"
DAY_FMT = "%Y-%m-%d"

# `2026-10-22_任务名` —— 前 10 位是日期，后面任务名可缺省（纯日期目录）
_DAY_DIR_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:_(.+))?$")
# 任务名清洗：去路径分隔符/控制字符，保留中文与常见标点
_UNSAFE_RE = re.compile(r"[\\/:*?\"'<>|\x00-\x1f]+")
_WS_RE = re.compile(r"\s+")
# 会话标题经常就是用户第一句话（实测 dev 里"请用write_file搜索…"整句入库），
# 整句当目录名没法看。取第一个子句 + 去掉指令前缀 + 限长。
_CLAUSE_RE = re.compile(r"[，。；！？:;,.!?、]")
_LEADING_NOISE_RE = re.compile(
    r"^(请|麻烦|帮我|帮忙|需要|要|现在|立刻|马上)+(?=\s*)",
)
#: 目录名会出现在提示词、面包屑、直链里 —— 短到能一眼认出来
MAX_SLUG_LEN = 24


def _shorten_title(raw: str) -> str:
    """把"整句话式"的会话标题收成可认的短任务名。"""
    text = raw.strip()
    m = _CLAUSE_RE.search(text)
    # 第一个子句太短（<4 字符）时不切，避免"好，写个报告"切成"好"
    if m and m.start() >= 4:
        text = text[: m.start()]
    text = _LEADING_NOISE_RE.sub("", text).strip()
    if len(text) < 2:
        # 切完没剩下什么 → 用原文，靠长度截断兜底
        text = raw.strip()
    return text[:MAX_SLUG_LEN].strip()


def sanitize_task_name(raw: Optional[str]) -> str:
    """把会话标题清洗成可用作目录名的任务名。

    空/全非法字符 → 返回空串，调用方降级为纯日期目录。
    """
    if not raw:
        return ""
    name = _UNSAFE_RE.sub(" ", str(raw)).strip()
    name = _WS_RE.sub(" ", name)
    if not name:
        return ""
    name = _shorten_title(name)
    # 前导点会造出隐藏目录
    name = name.lstrip(".")
    return name[:MAX_SLUG_LEN].strip().rstrip(".")


def is_session_dir(name: str) -> bool:
    """目录名是否形如 ``{YYYY-MM-DD}_{任务}``（含纯日期目录）。"""
    m = _DAY_DIR_RE.match(name)
    if not m:
        return False
    try:
        datetime.strptime(m.group(1), DAY_FMT)
        return True
    except ValueError:
        return False


def _dir_date(path: Path) -> Optional[date]:
    """会话目录名里的日期；解析失败返回 None。"""
    m = _DAY_DIR_RE.match(path.name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), DAY_FMT).date()
    except ValueError:
        return None


def _session_dirs(month_dir: Path) -> list[Path]:
    """月层下的会话目录，按目录名日期倒序（新→旧）。"""
    if not month_dir.is_dir():
        return []
    out: list[Path] = []
    try:
        for p in month_dir.iterdir():
            if p.is_dir() and is_session_dir(p.name):
                out.append(p)
    except OSError:
        return []
    out.sort(key=lambda p: p.name, reverse=True)
    return out


def _count_files(d: Path) -> int:
    """目录内文件数（不含子目录）—— 日期层的触发判据。"""
    try:
        return sum(1 for p in d.iterdir() if p.is_file())
    except OSError:
        return 0


async def _session_title(chat_id: str, username: Optional[str]) -> Optional[str]:
    """按 ``chat_id`` 解析会话标题（带 TTL 缓存，失败返回 None）。

    走 ChatManager 而非直接读 chats.json：企业版聊天仓库可能被 PG 包装，
    直读文件会读到过期/空数据。
    """
    if not chat_id:
        return None
    key = f"{username or ''}|{chat_id}"
    now = time.time()
    hit = _TITLE_CACHE.get(key)
    if hit and now - hit[0] < TITLE_CACHE_TTL:
        return hit[1]
    title: Optional[str] = None
    try:
        from ...app.multi_agent_manager import get_multi_agent_manager

        manager = get_multi_agent_manager()
        if manager is not None and username:
            cm = manager.get_user_chat_manager(username)
            chat = await cm.get_chat(chat_id) if cm else None
            title = getattr(chat, "name", None) or None
    except Exception:  # noqa: BLE001 - 标题解析失败必须降级，不能阻断写文件
        logger.debug(
            "session_dir: 标题解析失败 chat_id=%s（降级为纯日期目录）",
            chat_id,
            exc_info=True,
        )
        title = None
    _TITLE_CACHE[key] = (now, title)
    if len(_TITLE_CACHE) > 512:  # 防无界增长
        for k in list(_TITLE_CACHE)[:256]:
            _TITLE_CACHE.pop(k, None)
    return title


_TITLE_CACHE: dict[str, tuple[float, Optional[str]]] = {}


def resolve_session_dir(
    files_root: Path,
    chat_id: Optional[str],
    title: Optional[str],
    today: Optional[date] = None,
) -> Path:
    """计算本次写入的落点目录（**不创建目录**，纯计算）。

    Args:
        files_root: 工作区的 ``files`` 目录（绝对路径）
        chat_id: 会话身份；None → 月层平铺
        title: 会话标题（已解析；None → 纯日期目录名）
        today: 判定日用哪天（默认本地当天）

    Returns:
        绝对目录路径。调用方在其下写文件。
    """
    today = today or date.today()
    month_dir = files_root / today.strftime(MONTH_FMT)

    if not chat_id:
        # 无会话身份：与历史行为一致，月层平铺
        return month_dir

    window_start = today - timedelta(days=SESSION_DIR_WINDOW_DAYS)
    for cand in _session_dirs(month_dir):
        d = _dir_date(cand)
        if d is None or d < window_start:
            continue
        # 命中本会话目录（同月内最近的带日期目录）
        if d == today:
            return cand  # 当天层已存在 → 直接复用
        if _count_files(cand) >= MIN_NEW_FILES:
            # 会话在继续，文件多了 → 加当天层
            slug = sanitize_task_name(title)
            name = f"{today.strftime(DAY_FMT)}_{slug}" if slug else today.strftime(DAY_FMT)
            return cand / name
        return cand  # 未达门槛 → 平铺进同一会话目录

    # 本月无该会话目录 → 新建
    slug = sanitize_task_name(title)
    name = f"{today.strftime(DAY_FMT)}_{slug}" if slug else today.strftime(DAY_FMT)
    return month_dir / name


def flatten_rel_path(rel: Path) -> Path:
    """深度保护：模型给了过深的相对路径时只取文件名。

    目录层级由系统决定，模型不该通过 ``a/b/c/d/x.md`` 再造四层目录。
    """
    parts = [p for p in rel.parts if p not in (".", "")]
    if len(parts) > MAX_PATH_SEGMENTS:
        return Path(parts[-1])
    return Path(*parts) if parts else Path("untitled")


async def session_write_dir(
    files_root: Path,
    chat_id: Optional[str],
    username: Optional[str],
    today: Optional[date] = None,
) -> Path:
    """``resolve_session_dir`` 的便捷入口：解析标题 + 计算目录。"""
    title = await _session_title(chat_id, username) if chat_id else None
    return resolve_session_dir(files_root, chat_id, title, today=today)


def sweep_empty_session_dirs(
    files_root: Path,
    min_age_days: int = 1,
    today: Optional[date] = None,
) -> list[Path]:
    """列出**空的**会话目录（B6 清理报告，只报告不删）。

    只认 ``{日期}_{任务}`` 形态的目录，且 mtime 早于今天 —— 避免把本轮
    刚建、马上要写文件的目录报进来。
    """
    today = today or date.today()
    out: list[Path] = []
    if not files_root.is_dir():
        return out
    try:
        months = [p for p in files_root.iterdir() if p.is_dir()]
    except OSError:
        return out
    for month in months:
        for cand in _session_dirs(month):
            try:
                if cand.stat().st_mtime >= _start_of_today(today):
                    continue
                if not any(cand.iterdir()):
                    out.append(cand)
            except OSError:
                continue
    return out


def _start_of_today(today: date) -> float:
    return datetime(today.year, today.month, today.day).timestamp()


def sweep_report(max_report: int = 20) -> dict[str, Any]:
    """扫描所有用户工作区，报告空的会话目录（**只报告，不删除**）。

    为什么只报告：删目录要判"目录里是否曾有文件"，而台账有已知缺陷
    （dev 实测 89% 为巡检噪声）—— 依据不可靠的数据做删除，风险大于收益。
    先观察数量，再决定是否做真正的清理。
    """
    from ...constant import WORKSPACES_DIR

    empty: list[str] = []
    users = 0
    try:
        roots = [p for p in Path(WORKSPACES_DIR).iterdir() if p.is_dir()]
    except OSError:
        return {"users": 0, "empty_dirs": [], "total": 0}
    for ws in roots:
        users += 1
        for cand in sweep_empty_session_dirs(ws / "files"):
            try:
                empty.append(str(cand.relative_to(WORKSPACES_DIR)))
            except ValueError:
                empty.append(str(cand))
    return {
        "users": users,
        "total": len(empty),
        "empty_dirs": empty[:max_report],
    }


__all__ = [
    "MIN_NEW_FILES",
    "SESSION_DIR_WINDOW_DAYS",
    "MAX_PATH_SEGMENTS",
    "sanitize_task_name",
    "is_session_dir",
    "resolve_session_dir",
    "flatten_rel_path",
    "session_write_dir",
    "sweep_empty_session_dirs",
]
