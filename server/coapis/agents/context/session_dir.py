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
- **目录与会话一一绑定**（``files/.session_dirs.json``）：一个会话一个目录，
  绝不共用。早期实现靠"扫月层里当天最新的会话目录"复用，实测**同一天开两个
  会话会落进同一个目录**（chat-B 的产出写进 chat-A 的目录）—— 目录归属由
  绑定表决定，扫描只用于采纳历史遗留目录。
- **系统目录不进 files/**：智能体点名写 ``tool_results/``、``sessions/``、
  ``skills/`` 这类目录时落在工作区根（治理模块本来就写在那里），混进会话
  目录会把系统缓存当成用户产出。
- **临时区固定 ``files/.temp``**：提示词承诺"默认写 .temp/、自动清理"，而
  清理规则的路径就是 ``files/.temp``；落在会话目录内的 .temp 清理扫不到
  （dev 实测 2 例），故固定到工作区层。
- **无会话身份 → 月层平铺**，与历史行为一致，零回归。
- 任何异常一律降级为"不注入目录"，绝不阻断写文件。

同步/异步：标题解析要走 ChatManager（异步），因此 ``resolve_session_dir``
是协程；调用方（写类工具）本身都是 async。
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

def _env_int(name: str, default: int) -> int:
    """环境变量取整参数；值非法就用默认值（启动绝不能被一个坏配置搞崩）。"""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        val = int(str(raw).strip())
    except (TypeError, ValueError):
        logger.warning("session_dir: %s=%r 不是整数，用默认 %d", name, raw, default)
        return default
    return val if val > 0 else default


# ── 可调参数（集中在此 + env 可配，便于按使用数据调）────────────────
#: 会话目录内已有文件数达到该值，才启用"日期_任务"层
MIN_NEW_FILES = _env_int("COAPIS_SESSION_DIR_DAILY_LAYER", 15)
#: 无日期前缀的目录视为会话目录的宽容天数（跨周末/长假的长会话）
SESSION_DIR_WINDOW_DAYS = _env_int("COAPIS_SESSION_DIR_WINDOW_DAYS", 7)
#: 会话标题缓存时长（秒）。改名后最长 30s 生效，可接受 —— 目录名是快照，
#: 只有"新建目录"才需要标题。
TITLE_CACHE_TTL = 30.0
#: 模型给出的相对路径超过该段数时不再建深层目录，只取文件名
MAX_PATH_SEGMENTS = _env_int("COAPIS_SESSION_DIR_MAX_SEGMENTS", 4)

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
#: 新会话的默认标题（多语言）。这些词当目录名没有任何信息量。
_JUNK_TITLES: frozenset[str] = frozenset(
    {
        "new chat",
        "new conversation",
        "new session",
        "new task",
        "chat",
        "未命名会话",
        "新聊天",
        "新建对话",
        "新对话",
        "新会话",
        "新任务",
        "默认会话",
        "新建会话",
        "会话",
        "новый чат",
        "новая беседа",
        "новый диалог",
    },
)
#: 纯 ID 形态标题：``chat-2f9c1a3b``、``2f9c1a3b``、UUID（含带前缀的 chat/会话ID）
_ID_LIKE_RE = re.compile(r"^(?:[a-z]+[-_])?[0-9a-f]{6,}$", re.IGNORECASE)
#: 纯日期/时间形态标题
_DATE_LIKE_RE = re.compile(
    r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}(?:[ _]+\d{1,2}:\d{2}(?::\d{2})?)?$",
)
#: 目录名会出现在提示词、面包屑、直链里 —— 短到能一眼认出来
MAX_SLUG_LEN = _env_int("COAPIS_SESSION_DIR_SLUG_LEN", 24)

# ── 系统目录 / 临时区（都不进会话目录）──────────────────────────────
#: 工作区根的系统与治理目录。智能体在相对路径里点名这些目录时，落点在
#: **工作区根** —— 治理模块（light_context_manager）本来就写
#: ``{workspace}/tool_results``，技能、记忆、会话状态同理；把它们塞进
#: ``files/{月}/{会话}/`` 会让系统缓存出现在"我的空间"里当产出。
SYSTEM_DIR_NAMES: frozenset[str] = frozenset(
    {
        "_tool_results_cache",
        "tool_results_cache",
        "tool_results",
        "sessions",
        "chat",
        "chats",
        "crons",
        "memory",
        "uploads",
        "downloads",
        "backup",
        "backups",
        "browser",
        "skills",
        "agents",
        "dialog",
        "evolution",
        "knowledge_flow",
        "workflows",
        "tmp",
        "unpacked_doc",
        ".trash",
        ".doccache",
        ".memory_versions",
    },
)

#: 临时区目录名。``cleanup_manager`` 的清理规则写死 ``files/.temp``
#: （保留 1 天，每小时扫），所以临时区必须落在这个路径上才兑现提示词
#: 里"自动清理"的承诺。
SCRATCH_DIR_NAME = ".temp"


def system_dir_target(rel: Path, workspace_dir: Path) -> Optional[Path]:
    """相对路径点名系统/治理目录时，返回工作区根下的落点（否则 None）。"""
    parts = [p for p in rel.parts if p not in (".", "")]
    if not parts:
        return None
    if parts[0] in SYSTEM_DIR_NAMES:
        return workspace_dir / Path(*parts)
    return None


def scratch_dir_target(rel: Path, files_root: Path) -> Optional[Path]:
    """相对路径点名临时区时，返回 ``files/.temp/...``（否则 None）。"""
    parts = [p for p in rel.parts if p not in (".", "")]
    if not parts:
        return None
    if parts[0] == SCRATCH_DIR_NAME:
        return files_root / Path(*parts)
    return None


def _truncate_at_word(text: str, limit: int) -> str:
    """按长度截断，尽量在词边界收尾。

    实测 dev 目录名 ``…e2e目录验证.md，内容写一句话即可。不要问我，直接调用 w``
    —— 截断落在词中间，目录名读起来像乱码。中文无空格，直接按长度切；
    拉丁文回退到最后一个空格，找不到就整体截。
    """
    if len(text) <= limit:
        return text
    cut = text[:limit]
    sp = cut.rfind(" ")
    if sp >= max(4, limit // 2):
        cut = cut[:sp]
    return cut.strip()


def _is_junk_title(name: str) -> bool:
    """标题是否毫无信息量（新会话默认名 / 纯 ID / 纯日期形态）。

    这类标题当目录名等于没有名字，还占着"任务名"的位置。命中就返回空串，
    目录降级为纯日期目录 ``2026-10-22``。
    """
    if not name:
        return True
    low = name.strip().lower()
    if not low:
        return True
    if low in _JUNK_TITLES:
        return True
    # ``chat-2f9c1a3b`` / ``2f9c1a3b-5d6e-…`` / 会话ID后6位形态
    if _ID_LIKE_RE.match(low):
        return True
    # 纯日期/时间串
    if _DATE_LIKE_RE.match(low):
        return True
    return False


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
    return _truncate_at_word(text, MAX_SLUG_LEN)


def sanitize_task_name(raw: Optional[str]) -> str:
    """把会话标题清洗成可用作目录名的任务名。

    空/全非法字符/垃圾标题 → 返回空串，调用方降级为纯日期目录。
    """
    if not raw:
        return ""
    # 垃圾判定跑在**原文**上：清洗会把 ":" 换成空格，"2026-10-22 09:30"
    # 这种纯日期标题清洗后就躲过日期形态判定了。
    if _is_junk_title(str(raw)):
        return ""
    name = _UNSAFE_RE.sub(" ", str(raw)).strip()
    name = _WS_RE.sub(" ", name)
    if not name:
        return ""
    if _is_junk_title(name):
        return ""
    name = _shorten_title(name)
    # 目录名里的空格要变成 `_`：带空格的名字会进 URL（%20）、进 shell、
    # 进面包屑，每一处都要转义 —— 实测直链可用但脆。
    name = _WS_RE.sub("_", name).strip("._")
    # 前导点会造出隐藏目录
    name = name.lstrip(".")
    return _truncate_at_word(name, MAX_SLUG_LEN).strip("._").rstrip(".")


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


# ── 会话目录绑定表 ──────────────────────────────────────────────────
# ``files/.session_dirs.json``：chat_id → 目录（相对 files 根）+ 建目录时的
# 标题快照。为什么单独存文件而不用台账：台账有已知缺陷（dev 实测 89% 为巡检
# 噪声），目录归属是硬约束，不能建立在不可靠数据上；这个文件只由本模块写，
# 体积小、可删可重建（丢了最坏结果是新建目录，不会串会话）。
BINDING_FILE = ".session_dirs.json"
BINDING_LOCK_FILE = ".session_dirs.lock"
_BINDING_VERSION = 1
_binding_lock = threading.Lock()


def _binding_path(files_root: Path) -> Path:
    return files_root / BINDING_FILE


def load_bindings(files_root: Path) -> dict[str, dict]:
    """读绑定表。文件缺失/损坏一律当空表 —— 解析目录绝不能因它抛异常。"""
    path = _binding_path(files_root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("session_dir: 绑定表不可读，按空表处理 %s", path)
        return {}
    if not isinstance(data, dict):
        return {}
    dirs = data.get("dirs")
    if not isinstance(dirs, dict):
        return {}
    return {
        str(k): v for k, v in dirs.items() if isinstance(v, dict) and v.get("dir")
    }


def _save_bindings(files_root: Path, dirs: dict[str, dict]) -> None:
    """原子写：临时文件 + ``os.replace``，避免半截文件。"""
    path = _binding_path(files_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": _BINDING_VERSION, "dirs": dirs}
    tmp = path.parent / f"{path.name}.{os.getpid()}.tmp"
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, path)


@contextmanager
def _binding_txn(files_root: Path):
    """绑定表的读-改-写事务。

    进程内用锁串行；跨进程用 ``flock`` 串行（多 worker 同时写文件时，
    没有锁会互相覆盖绑定记录 → 两个会话共用目录）。无 flock 的平台
    （Windows）退化为进程内锁，最坏结果与旧实现相同。
    """
    lock_path = _binding_path(files_root).with_name(BINDING_LOCK_FILE)
    fh = None
    try:
        import fcntl

        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(lock_path, "a+")
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    except Exception:  # noqa: BLE001 - 无 flock/只读目录：降级为进程内锁
        fh = None
    with _binding_lock:
        try:
            yield
        finally:
            if fh is not None:
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                    fh.close()
                except Exception:  # noqa: BLE001
                    pass


def lookup_bound_dir(files_root: Path, chat_id: Optional[str]) -> Optional[Path]:
    """会话已绑定的目录；目录被删掉时丢弃绑定（下次写入重建）。"""
    if not chat_id:
        return None
    try:
        with _binding_txn(files_root):
            dirs = load_bindings(files_root)
            rec = dirs.get(chat_id)
            if not rec:
                return None
            target = files_root / str(rec["dir"])
            if target.is_dir():
                return target
            dirs.pop(chat_id, None)
            _save_bindings(files_root, dirs)
            return None
    except Exception:  # noqa: BLE001 - 绑定表故障不能阻断写文件
        logger.debug("session_dir: 绑定表读取失败", exc_info=True)
        return None


def bind_session_dir(
    files_root: Path,
    chat_id: Optional[str],
    dir_path: Path,
    title: Optional[str],
    today: Optional[date] = None,
) -> None:
    """把目录绑定到会话（标题按建目录当天固化 = 名称快照）。"""
    if not chat_id:
        return
    try:
        rel = str(Path(dir_path).relative_to(files_root))
    except ValueError:
        return  # 不在 files 根下（用户自建目录引用等），不绑
    try:
        with _binding_txn(files_root):
            dirs = load_bindings(files_root)
            dirs[chat_id] = {
                "dir": rel,
                "title": title or "",
                "created": (today or date.today()).isoformat(),
            }
            _save_bindings(files_root, dirs)
    except Exception:  # noqa: BLE001 - 绑定失败最坏是下次重建目录
        logger.debug("session_dir: 绑定写入失败", exc_info=True)


def bound_dir_names(files_root: Path) -> set[str]:
    """已被任何会话绑定的目录（相对 files 根），用于避免共用。"""
    try:
        return {str(v.get("dir")) for v in load_bindings(files_root).values()}
    except Exception:  # noqa: BLE001
        return set()


def session_dir_rel(
    files_root: Path,
    chat_id: Optional[str],
) -> Optional[str]:
    """会话已绑定的目录（相对 files 根）；没绑定返回 None。

    给"本会话目录"入口用：只读绑定表，不解析标题、不建目录 —— 会话还没
    产出过文件时没有目录，前端据此置灰，而不是跳进一个空目录。
    """
    if not chat_id:
        return None
    bound = lookup_bound_dir(files_root, chat_id)
    if bound is None:
        return None
    try:
        return str(Path(bound).relative_to(files_root))
    except ValueError:
        return None


def find_loose_file(
    files_root: Path,
    name: str,
    chat_id: Optional[str] = None,
    today: Optional[date] = None,
) -> Optional[Path]:
    """裸文件名在 ``files`` 根找不到时，按"本会话目录 → 当月 → 根"顺序找。

    写侧会把 ``报告.md`` 重排进 ``files/{月}/{日期}_{任务}/`` 并回报完整相对
    路径；模型抄回裸文件名时，读侧若只按 ``files/报告.md`` 解析就会"写了却
    读不到"。这里只在**精确路径不存在**时兜底，不改变命中时的行为。
    """
    if not name or "/" in name or name in (".", ".."):
        return None
    today = today or date.today()
    tried: list[Path] = []
    bound = lookup_bound_dir(files_root, chat_id) if chat_id else None
    if bound is not None:
        # 会话目录根 + 一层日期层（日期层最多一层，不做全递归）
        tried.append(bound / name)
        try:
            tried.extend(sub / name for sub in bound.iterdir() if sub.is_dir())
        except OSError:
            pass
    tried.append(files_root / today.strftime(MONTH_FMT) / name)
    tried.append(files_root / name)
    for cand in tried:
        try:
            if cand.is_file():
                return cand
        except OSError:
            continue
    return None


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


def _slug_of_dir(name: str) -> str:
    """``2026-10-22_季度报告`` → ``季度报告``；纯日期目录 → 空串。"""
    return name.split("_", 1)[1] if "_" in name else ""


def _extend_day_layer(bound: Path, title: Optional[str], today: date) -> Path:
    """已绑定目录内的落点：今天的日期层优先，未达门槛就平铺。"""
    if not is_session_dir(bound.name):
        return bound
    day = today.strftime(DAY_FMT)
    # 今天的日期层已存在 → 继续用它。不能因为"根目录文件数没到门槛"又把
    # 文件写回会话目录根，那样日期层永远只装着第一批文件。
    try:
        for child in bound.iterdir():
            if child.is_dir() and child.name.startswith(day):
                return child
    except OSError:
        return bound
    if _count_files(bound) >= MIN_NEW_FILES:
        slug = sanitize_task_name(title)
        return bound / (f"{day}_{slug}" if slug else day)
    return bound


def _adopt_legacy_dir(
    month_dir: Path,
    title: Optional[str],
    today: date,
    bound: set[str],
) -> Optional[Path]:
    """采纳绑定表启用前遗留的会话目录（历史写入/cron 建的），避免重复建目录。

    只采纳：会话目录形态、标题清洗后同名、日期在活跃窗口内、**未被任何会话
    绑定**。已绑定的目录绝不采纳 —— 那是别人的会话。
    """
    slug = sanitize_task_name(title)
    if not slug:
        return None
    for cand in _session_dirs(month_dir):
        d = _dir_date(cand)
        if d is None or d > today:
            continue
        if (today - d).days > SESSION_DIR_WINDOW_DAYS:
            continue
        if f"{month_dir.name}/{cand.name}" in bound:
            continue
        if sanitize_task_name(_slug_of_dir(cand.name)) == slug:
            return cand
    return None


def _adopt_or_new_dir(
    month_dir: Path,
    title: Optional[str],
    today: date,
    bound: set[str],
) -> Path:
    """新会话目录名 ``{日期}_{任务}``；名字被占就加序号，**绝不共用**。"""
    slug = sanitize_task_name(title)
    base = f"{today.strftime(DAY_FMT)}_{slug}" if slug else today.strftime(DAY_FMT)
    rel = f"{month_dir.name}/{base}"
    cand = month_dir / base
    if cand.is_dir() and rel not in bound:
        # 目录在、没人绑定 → 本会话遗留（重开、绑定表被清）→ 采纳
        return cand
    if not cand.is_dir() and rel not in bound:
        return cand
    n = 2
    while n <= 50:
        name = f"{base}-{n}"
        c = month_dir / name
        if not c.is_dir() and f"{month_dir.name}/{name}" not in bound:
            return c
        n += 1
    return month_dir / f"{base}-{int(time.time())}"


def resolve_session_dir(
    files_root: Path,
    chat_id: Optional[str],
    title: Optional[str],
    today: Optional[date] = None,
    bound: Optional[Path] = None,
) -> Path:
    """计算本次写入的落点目录（**不创建目录**，纯计算）。

    Args:
        files_root: 工作区的 ``files`` 目录（绝对路径）
        chat_id: 会话身份；None → 月层平铺
        title: 会话标题（已解析；None → 纯日期目录名）
        today: 判定日用哪天（默认本地当天）
        bound: 该会话已绑定的目录（调用方从绑定表取）；给了就直接用

    Returns:
        绝对目录路径。调用方在其下写文件。
    """
    today = today or date.today()
    month_dir = files_root / today.strftime(MONTH_FMT)

    if not chat_id:
        # 无会话身份：与历史行为一致，月层平铺
        return month_dir

    if bound is not None:
        return _extend_day_layer(bound, title, today)

    bound_names = bound_dir_names(files_root)
    legacy = _adopt_legacy_dir(month_dir, title, today, bound_names)
    if legacy is not None:
        return _extend_day_layer(legacy, title, today)
    return _adopt_or_new_dir(month_dir, title, today, bound_names)


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
    """``resolve_session_dir`` 的便捷入口：解析标题 + 查绑定 + 首次绑定。

    绑定只在**首次**写入时建立，目录名按当天标题固化；此后会话改名也
    不会动目录，历史直链不会 404。
    """
    today = today or date.today()
    if not chat_id:
        return files_root / today.strftime(MONTH_FMT)
    title = await _session_title(chat_id, username)
    bound = lookup_bound_dir(files_root, chat_id)
    target = resolve_session_dir(
        files_root,
        chat_id,
        title,
        today=today,
        bound=bound,
    )
    if bound is None:
        bind_session_dir(files_root, chat_id, target, title, today)
    return target


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


def sweep_scratch_dirs(
    files_root: Path,
    retention_days: int = 1,
    now: Optional[float] = None,
) -> int:
    """清掉**任意层级**的 ``.temp`` 过期内容，返回删除的文件数。

    提示词承诺"默认写 .temp、自动清理"，而 ``cleanup_manager`` 的规则路径
    写死 ``files/.temp``；历史上 .temp 被重排进会话目录
    （``files/{月}/{会话}/.temp/``），清理规则扫不到 —— 承诺落空。
    这里按目录名匹配，任意层级都兑现，与 ``files/.temp`` 的保留期一致。
    """
    if not files_root.is_dir():
        return 0
    cutoff = (now if now is not None else time.time()) - retention_days * 86400
    removed = 0
    try:
        scratch_dirs = [p for p in files_root.rglob(SCRATCH_DIR_NAME) if p.is_dir()]
    except OSError:
        return 0
    for d in scratch_dirs:
        for f in sorted(d.rglob("*")):
            try:
                if not f.is_file():
                    continue
                if f.stat().st_mtime > cutoff:
                    continue
                f.unlink()
                removed += 1
            except OSError:
                continue
        # 内容清完就收掉空壳（含会话目录里的 .temp 子目录）
        for sub in sorted((p for p in d.rglob("*") if p.is_dir()), reverse=True):
            try:
                if not any(sub.iterdir()):
                    sub.rmdir()
            except OSError:
                pass
        try:
            if not any(d.iterdir()):
                d.rmdir()
        except OSError:
            pass
    return removed


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
    "BINDING_FILE",
    "MIN_NEW_FILES",
    "SESSION_DIR_WINDOW_DAYS",
    "MAX_PATH_SEGMENTS",
    "MAX_SLUG_LEN",
    "SCRATCH_DIR_NAME",
    "SYSTEM_DIR_NAMES",
    "sanitize_task_name",
    "is_session_dir",
    "resolve_session_dir",
    "flatten_rel_path",
    "session_write_dir",
    "sweep_empty_session_dirs",
    "bound_dir_names",
    "bind_session_dir",
    "lookup_bound_dir",
    "load_bindings",
    "session_dir_rel",
    "find_loose_file",
    "sweep_scratch_dirs",
    "sweep_report",
    "scratch_dir_target",
    "system_dir_target",
]
