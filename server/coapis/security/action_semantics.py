# -*- coding: utf-8 -*-
"""动作语义分级表（片0 · 限制治理地基）。

把"这次调用到底做了什么级别的事"从**工具名**升维到**动作语义**，
供计划门禁、方案授权域、子智能体继承三处共用同一张表。

六档语义（由轻到重）::

    read            纯读取，零副作用
    external_read   对外发起读取（网络/其他系统），不改变外部状态
    local_write     工作区内新增/修改，可回滚
    local_delete    本地删除/覆盖，恢复成本高
    external_write  对外产生"出入"（发消息/发帖/写外部系统/推送）
    destructive     破坏性且不可逆（rm -rf、drop、生产发布）

判定口径（用户拍板 2026-10-14）：
    计划除非涉及"出入"，可直接执行；涉及出入必须先经方案确认。
    破坏性动作**永不**被计划授权域覆盖，一律单独审批。

配置真相源：``system/action_semantics.yaml``（缺失时用内置默认）。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "system" / "action_semantics.yaml"


# ---------------------------------------------------------------------------
# 语义枚举
# ---------------------------------------------------------------------------


class ActionSemantics(str, Enum):
    """动作语义档位（值即配置里写的字符串）。"""

    READ = "read"
    EXTERNAL_READ = "external_read"
    LOCAL_WRITE = "local_write"
    LOCAL_DELETE = "local_delete"
    EXTERNAL_WRITE = "external_write"
    DESTRUCTIVE = "destructive"


# 由轻到重的顺序；索引越大越重
ORDER: tuple[ActionSemantics, ...] = (
    ActionSemantics.READ,
    ActionSemantics.EXTERNAL_READ,
    ActionSemantics.LOCAL_WRITE,
    ActionSemantics.LOCAL_DELETE,
    ActionSemantics.EXTERNAL_WRITE,
    ActionSemantics.DESTRUCTIVE,
)

_RANK: dict[ActionSemantics, int] = {s: i for i, s in enumerate(ORDER)}


def rank(sem: ActionSemantics) -> int:
    """语义档位序号（越大越重）。"""
    return _RANK[sem]


def at_least(sem: ActionSemantics, threshold: ActionSemantics) -> bool:
    """``sem`` 是否达到 ``threshold`` 档及以上。"""
    return _RANK[sem] >= _RANK[threshold]


def parse_semantics(raw: str) -> ActionSemantics:
    """解析配置字符串，无法识别时按最重的破坏性处理（fail-closed）。"""
    try:
        return ActionSemantics(str(raw).strip().lower())
    except ValueError:
        return ActionSemantics.DESTRUCTIVE


# ---------------------------------------------------------------------------
# 内置默认表（配置文件缺失时的兜底）
# ---------------------------------------------------------------------------

#: 纯读取类工具
_DEFAULT_READ_TOOLS: dict[str, ActionSemantics] = {
    "read_file": ActionSemantics.READ,
    "view_image": ActionSemantics.READ,
    "view_video": ActionSemantics.READ,
    "grep_search": ActionSemantics.READ,
    "glob_search": ActionSemantics.READ,
    "list_agents": ActionSemantics.READ,
    "get_current_time": ActionSemantics.READ,
    "get_token_usage": ActionSemantics.READ,
    "memory_search": ActionSemantics.READ,
    "recall_history": ActionSemantics.READ,
    "desktop_screenshot": ActionSemantics.READ,
    "file_diff": ActionSemantics.READ,
    "file_search": ActionSemantics.READ,
    "session_search": ActionSemantics.READ,
    "tool_stats": ActionSemantics.READ,
    "sys_monitor": ActionSemantics.READ,
    "dependency_audit": ActionSemantics.READ,
    "code_quality": ActionSemantics.READ,
    "secret_scan": ActionSemantics.READ,
    "check_agent_task": ActionSemantics.READ,
}

#: 对外读取（发起网络请求但不改外部状态）
_DEFAULT_EXTERNAL_READ_TOOLS: dict[str, ActionSemantics] = {
    "web_search": ActionSemantics.EXTERNAL_READ,
    "web_fetch": ActionSemantics.EXTERNAL_READ,
    "resource_search": ActionSemantics.EXTERNAL_READ,
    "http_client": ActionSemantics.EXTERNAL_READ,
    "browser_use": ActionSemantics.EXTERNAL_READ,
}

#: 工作区内写入
_DEFAULT_LOCAL_WRITE_TOOLS: dict[str, ActionSemantics] = {
    "write_file": ActionSemantics.LOCAL_WRITE,
    "edit_file": ActionSemantics.LOCAL_WRITE,
    "create_dir": ActionSemantics.LOCAL_WRITE,
    "move_file": ActionSemantics.LOCAL_WRITE,
    "copy_file": ActionSemantics.LOCAL_WRITE,
    "write_text_file": ActionSemantics.LOCAL_WRITE,
    "create_file": ActionSemantics.LOCAL_WRITE,
    "send_file_to_user": ActionSemantics.LOCAL_WRITE,
    "send_file": ActionSemantics.LOCAL_WRITE,
    "notes": ActionSemantics.LOCAL_WRITE,
    "daily_memory": ActionSemantics.LOCAL_WRITE,
    "memory_manager": ActionSemantics.LOCAL_WRITE,
    "generate_image": ActionSemantics.LOCAL_WRITE,
    "data_store": ActionSemantics.LOCAL_WRITE,
    "data_processor": ActionSemantics.LOCAL_WRITE,
    "text_processor": ActionSemantics.LOCAL_WRITE,
    "file_io": ActionSemantics.LOCAL_WRITE,
    "todo_tool": ActionSemantics.LOCAL_WRITE,
    "skill_manager": ActionSemantics.LOCAL_WRITE,
    "materialize_skill": ActionSemantics.LOCAL_WRITE,
    "test_runner": ActionSemantics.LOCAL_WRITE,
    "code_runner": ActionSemantics.LOCAL_WRITE,
    "changelog_gen": ActionSemantics.LOCAL_WRITE,
    "project_analyzer": ActionSemantics.LOCAL_WRITE,
    "prompt_builder": ActionSemantics.LOCAL_WRITE,
}

#: 本地删除/覆盖
_DEFAULT_LOCAL_DELETE_TOOLS: dict[str, ActionSemantics] = {
    "delete_file": ActionSemantics.LOCAL_DELETE,
    "remove_file": ActionSemantics.LOCAL_DELETE,
    "cleanup": ActionSemantics.LOCAL_DELETE,
    "archive_ops": ActionSemantics.LOCAL_DELETE,
    "clipboard_ops": ActionSemantics.LOCAL_DELETE,
    "env_manager": ActionSemantics.LOCAL_DELETE,
}

#: 对外产生出入
_DEFAULT_EXTERNAL_WRITE_TOOLS: dict[str, ActionSemantics] = {
    "chat_with_agent": ActionSemantics.EXTERNAL_WRITE,
    "submit_to_agent": ActionSemantics.EXTERNAL_WRITE,
    "spawn_subagent": ActionSemantics.EXTERNAL_WRITE,
    "send_message": ActionSemantics.EXTERNAL_WRITE,
    "channels_send": ActionSemantics.EXTERNAL_WRITE,
    "cron_scheduler": ActionSemantics.EXTERNAL_WRITE,
    "install_dependency": ActionSemantics.EXTERNAL_WRITE,
    "deploy_helper": ActionSemantics.EXTERNAL_WRITE,
    "git_ops": ActionSemantics.EXTERNAL_WRITE,
    "auto_heal": ActionSemantics.EXTERNAL_WRITE,
    "security_ops": ActionSemantics.EXTERNAL_WRITE,
    "policy_engine": ActionSemantics.EXTERNAL_WRITE,
    "browser_control": ActionSemantics.EXTERNAL_WRITE,
}

#: 破坏性工具（不可逆）
_DEFAULT_DESTRUCTIVE_TOOLS: dict[str, ActionSemantics] = {
    "drop_database": ActionSemantics.DESTRUCTIVE,
    "delete_session": ActionSemantics.DESTRUCTIVE,
    "delete_all": ActionSemantics.DESTRUCTIVE,
}

DEFAULT_TOOL_SEMANTICS: dict[str, ActionSemantics] = {
    **_DEFAULT_READ_TOOLS,
    **_DEFAULT_EXTERNAL_READ_TOOLS,
    **_DEFAULT_LOCAL_WRITE_TOOLS,
    **_DEFAULT_LOCAL_DELETE_TOOLS,
    **_DEFAULT_EXTERNAL_WRITE_TOOLS,
    **_DEFAULT_DESTRUCTIVE_TOOLS,
}

#: 命令风险等级（tool_guard.yaml 的 L0~L4）→ 语义
COMMAND_LEVEL_TO_SEMANTICS: dict[str, ActionSemantics] = {
    "L0": ActionSemantics.READ,
    "L1": ActionSemantics.LOCAL_WRITE,
    "L2": ActionSemantics.LOCAL_WRITE,
    "L3": ActionSemantics.EXTERNAL_WRITE,
    "L4": ActionSemantics.DESTRUCTIVE,
}

#: 破坏性命令模式（命中即 DESTRUCTIVE，不看命令名）
DEFAULT_DESTRUCTIVE_PATTERNS: tuple[str, ...] = (
    r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r)\b",
    r"\brm\s+-[a-zA-Z]+\s+/(?:\s|$)",
    r"\bmkfs(\.|\s)",
    r"\bdd\s+if=",
    r"\bdrop\s+(table|database|schema)\b",
    r"\btruncate\s+table\b",
    r"\bdelete\s+from\s+\w+\s*(;|$)",
    r"\btruncate\s+(-c)?\s*(-a)?\s*(-v)?\s*(-f)?\s*(-r)?\s*(-x)?\s*(-n)?\s*(-s)?\s*(-t)?\s*(-w)?\s*(-y)?\s*(-z)?\b",
    r":\(\)\s*\{\s*:\|:&\s*\}\s*;",
    r">\s*/dev/(sd|nvme|hd)",
    r"\bgit\s+push\b.*(--force\b|-f\b)",
    r"\bgit\s+(reset\s+--hard|clean\s+-[a-zA-Z]*f)\b",
    r"\bdocker\s+(system\s+prune|volume\s+rm|container\s+rm)\b",
    r"\bkubectl\s+delete\b",
    r"\bchmod\s+-R\s+777\s+/(?:\s|$)",
    r"\bchown\s+-R\b.*\s/(?:\s|$)",
    r"\bkill\s+(-9|-KILL)\b.*\b1\b",
    r"\bshutdown\b|\breboot\b|\binit\s+0\b",
    r"\b(curl|wget)\b.*\|\s*(ba)?sh\b",
    r"\b(publish|deploy)\b.*\b(prod|production)\b",
    r"\bALTER\s+TABLE\b.*\bDROP\b",
)

#: 计划文本里的"出入/破坏"线索词（用于计划级预判，宁滥勿缺）
DEFAULT_PLAN_SIDE_EFFECT_KEYWORDS: tuple[str, ...] = (
    # 对外
    "发送", "发消息", "推送", "通知", "发帖", "回复邮件", "发邮件", "发布",
    "上传到", "提交到", "写入外部", "调用外部", "第三方", "线上", "生产",
    "send ", "notify", "publish", "post ", "email", "webhook", "http post",
    "push", "deploy",
    # 破坏性
    "删除", "清空", "清除", "销毁", "卸载", "重置", "回滚", "覆盖",
    "drop", "delete", "remove", "destroy", "purge", "format", "truncate",
    # 权限/凭证
    "授权", "凭证", "令牌", "密码", "token", "secret", "credential",
)

#: 计划文本里的"纯读取"线索词（命中且无出入词 → 判定为可直接执行）
DEFAULT_PLAN_READ_ONLY_KEYWORDS: tuple[str, ...] = (
    "读取", "查看", "列出", "检索", "搜索", "统计", "分析", "汇总", "对比",
    "核对", "检查", "梳理", "解读", "摘录", "翻译", "解释",
    "read", "list", "search", "grep", "show", "count", "analyze", "compare",
)


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------


@dataclass
class ActionSemanticsConfig:
    """分级表配置（含阈值）。"""

    tool_semantics: dict[str, ActionSemantics] = field(
        default_factory=lambda: dict(DEFAULT_TOOL_SEMANTICS),
    )
    destructive_patterns: tuple[str, ...] = DEFAULT_DESTRUCTIVE_PATTERNS
    side_effect_keywords: tuple[str, ...] = DEFAULT_PLAN_SIDE_EFFECT_KEYWORDS
    read_only_keywords: tuple[str, ...] = DEFAULT_PLAN_READ_ONLY_KEYWORDS
    #: 计划内可免确认执行的最高语义档（用户口径：涉及出入须确认）
    plan_auto_max: ActionSemantics = ActionSemantics.LOCAL_WRITE
    #: 方案授权域内可免单独审批的最高语义档
    scope_auto_max: ActionSemantics = ActionSemantics.LOCAL_WRITE
    #: 子智能体可继承的最高语义档（用户口径：继承除破坏性之外全部）
    subagent_max: ActionSemantics = ActionSemantics.EXTERNAL_WRITE
    #: 未收录工具按工具名启发式判定的兜底档
    unknown_semantics: ActionSemantics = ActionSemantics.EXTERNAL_WRITE

    def threshold_ok(self, sem: ActionSemantics, ceiling: ActionSemantics) -> bool:
        """``sem`` 是否落在 ``ceiling`` 档及以下（破坏性永不放行）。"""
        if sem is ActionSemantics.DESTRUCTIVE:
            return False
        return rank(sem) <= rank(ceiling)


def _compile_patterns(patterns: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    out = []
    for pat in patterns:
        try:
            out.append(re.compile(pat, re.IGNORECASE))
        except re.error as exc:  # 配置写坏时跳过该条，不影响其余
            logger.warning("action_semantics: bad pattern %r: %s", pat, exc)
    return tuple(out)


# ---------------------------------------------------------------------------
# 加载
# ---------------------------------------------------------------------------


def _load_config() -> ActionSemanticsConfig:
    cfg = ActionSemanticsConfig()
    if not _CONFIG_PATH.exists():
        logger.debug("action_semantics: %s not found, using defaults", _CONFIG_PATH)
        return cfg
    try:
        import yaml

        raw = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # pragma: no cover
        logger.error("action_semantics: load failed (%s), using defaults", exc)
        return cfg

    tools = raw.get("tools") or {}
    if isinstance(tools, dict):
        for name, sem in tools.items():
            cfg.tool_semantics[str(name)] = parse_semantics(str(sem))

    destr = raw.get("destructive_tools") or []
    if isinstance(destr, list):
        for name in destr:
            cfg.tool_semantics[str(name)] = ActionSemantics.DESTRUCTIVE

    pats = raw.get("destructive_patterns") or []
    if isinstance(pats, list) and pats:
        cfg.destructive_patterns = tuple(str(p) for p in pats)

    kws = raw.get("side_effect_keywords") or []
    if isinstance(kws, list) and kws:
        cfg.side_effect_keywords = tuple(str(k) for k in kws)

    kws = raw.get("read_only_keywords") or []
    if isinstance(kws, list) and kws:
        cfg.read_only_keywords = tuple(str(k) for k in kws)

    thresholds = raw.get("thresholds") or {}
    if isinstance(thresholds, dict):
        cfg.plan_auto_max = parse_semantics(
            str(thresholds.get("plan_auto_execute_max", cfg.plan_auto_max.value)),
        )
        cfg.scope_auto_max = parse_semantics(
            str(thresholds.get("scope_auto_approve_max", cfg.scope_auto_max.value)),
        )
        cfg.subagent_max = parse_semantics(
            str(thresholds.get("subagent_max", cfg.subagent_max.value)),
        )
        cfg.unknown_semantics = parse_semantics(
            str(thresholds.get("unknown", cfg.unknown_semantics.value)),
        )

    return cfg


@lru_cache(maxsize=1)
def get_config() -> ActionSemanticsConfig:
    """分级表配置单例（热重载时调用 ``reload_config``）。"""
    return _load_config()


def reload_config() -> ActionSemanticsConfig:
    """清空缓存并重读配置，返回新配置。"""
    get_config.cache_clear()
    return get_config()


# ---------------------------------------------------------------------------
# 判定
# ---------------------------------------------------------------------------

#: 需要单独审批的动作语义（>= 阈值）由调用方按场景阈值决定；
#: 这里提供"工具名 → 语义"的纯查表 + 参数感知修正。

_SHELL_TOOLS = frozenset(
    {"execute_shell_command", "shell", "bash", "run_shell", "exec_shell"},
)

_WRITEISH_HINTS = ("write", "create", "edit", "save", "append", "update", "insert")
_DELETE_HINTS = ("delete", "remove", "drop", "purge", "destroy", "clean", "trash")
_SEND_HINTS = ("send", "publish", "post", "notify", "push", "deploy", "submit")
_READ_HINTS = ("read", "list", "get", "view", "search", "grep", "glob", "show", "stat")


def _heuristic(name: str) -> ActionSemantics:
    """未收录工具按名字启发式判档（判不准时按对外写入，宁严勿松）。

    按 ``_``/``-``/驼峰切词后整词匹配，避免 "widget" 命中 "get" 这类误判。
    """
    tokens = _name_tokens(name)
    if tokens & set(_DELETE_HINTS):
        return ActionSemantics.LOCAL_DELETE
    if tokens & set(_SEND_HINTS):
        return ActionSemantics.EXTERNAL_WRITE
    if tokens & set(_WRITEISH_HINTS):
        return ActionSemantics.LOCAL_WRITE
    if tokens & set(_READ_HINTS):
        return ActionSemantics.READ
    return get_config().unknown_semantics


def _name_tokens(name: str) -> frozenset[str]:
    """把工具名切成小写词元：分隔符切分 + 驼峰切分。"""
    raw = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name or "")
    parts = re.split(r"[^a-zA-Z0-9]+", raw)
    return frozenset(p.lower() for p in parts if p)


def command_semantics(command: str) -> ActionSemantics:
    """把 shell 命令映射到动作语义。

    优先用 tool_guard 统一引擎的命令等级（L0~L4），
    命中破坏性模式则直接判破坏性（模式优先于等级，宁严勿松）。
    """
    cfg = get_config()
    text = command or ""
    for pat in _compiled_patterns():
        if pat.search(text):
            return ActionSemantics.DESTRUCTIVE

    level = _command_level(text)
    if level:
        return COMMAND_LEVEL_TO_SEMANTICS.get(level, cfg.unknown_semantics)
    return cfg.unknown_semantics


def _command_level(command: str) -> str | None:
    """向统一引擎要命令风险等级；引擎不可用时返回 None。"""
    try:
        from .tool_guard.unified_engine import get_unified_engine

        engine = get_unified_engine()
        cfg = engine.config
        first = (command or "").strip().split()
        if not first:
            return None
        return cfg.get_command_level(first[0])
    except Exception:  # pragma: no cover - 引擎缺失时降级
        return None


@lru_cache(maxsize=1)
def _compiled_patterns() -> tuple[re.Pattern[str], ...]:
    return _compile_patterns(get_config().destructive_patterns)


def classify_action(
    tool_name: str,
    params: dict[str, Any] | None = None,
) -> ActionSemantics:
    """判定一次工具调用的动作语义。

    优先级：破坏性参数模式 > shell 命令语义 > 工具名查表 > 名字启发式。
    """
    cfg = get_config()
    params = params or {}
    name = tool_name or ""

    # 1) shell 类：看命令本身
    if name in _SHELL_TOOLS:
        command = str(params.get("command", "") or "")
        return command_semantics(command)

    # 2) 参数里带 command 的（如 code_exec / test_runner）
    command = params.get("command")
    if isinstance(command, str) and command.strip():
        sem = command_semantics(command)
        if sem is ActionSemantics.DESTRUCTIVE:
            return ActionSemantics.DESTRUCTIVE

    # 3) 浏览器类：只读动作 vs 交互动作
    if name == "browser_use":
        action = str(params.get("action", "") or "").lower()
        if action in {
            "click", "type", "fill_form", "submit", "press_key", "drag",
            "select_option", "file_upload", "cookies_set", "cookies_clear",
            "handle_dialog", "run_code", "evaluate", "eval", "batch",
        }:
            return ActionSemantics.EXTERNAL_WRITE
        if action in {"start", "stop", "open", "navigate", "navigate_back"}:
            return ActionSemantics.EXTERNAL_READ
        return ActionSemantics.READ

    # 4) HTTP 类：GET 读 / 其他写
    if name in {"http_client", "api_tools"}:
        method = str(params.get("method", "GET") or "GET").upper()
        if method in {"GET", "HEAD", "OPTIONS"}:
            return ActionSemantics.EXTERNAL_READ
        return ActionSemantics.EXTERNAL_WRITE

    # 5) 查表
    sem = cfg.tool_semantics.get(name)
    if sem is not None:
        return sem

    # 6) 启发式
    return _heuristic(name)


def requires_confirmation(
    sem: ActionSemantics,
    ceiling: ActionSemantics | None = None,
) -> bool:
    """``True`` 表示该语义档需要用户确认/单独审批。

    破坏性恒为 True；其余按场景阈值（默认取计划阈值）。
    """
    if sem is ActionSemantics.DESTRUCTIVE:
        return True
    limit = ceiling if ceiling is not None else get_config().plan_auto_max
    return rank(sem) > rank(limit)


def is_destructive(sem: ActionSemantics) -> bool:
    """是否破坏性档。"""
    return sem is ActionSemantics.DESTRUCTIVE


def plan_text_semantics(text: str) -> ActionSemantics:
    """计划文本级预判（粗判，用于"方案必须经过确认"的门禁）。

    命中出入/破坏线索 → 至少对外写入；命中破坏线索 → 破坏性。
    纯读取线索且无出入线索 → 读取；判不准时按对外写入（宁严勿松）。
    """
    cfg = get_config()
    low = (text or "").lower()
    if not low.strip():
        return cfg.unknown_semantics

    for pat in _compiled_patterns():
        if pat.search(low):
            return ActionSemantics.DESTRUCTIVE

    destr_kw = cfg.destructive_patterns and _keywords_hit(low, _DESTRUCTIVE_KEYWORDS)
    if destr_kw:
        return ActionSemantics.DESTRUCTIVE

    if _keywords_hit(low, cfg.side_effect_keywords):
        return ActionSemantics.EXTERNAL_WRITE

    if _keywords_hit(low, cfg.read_only_keywords):
        return ActionSemantics.READ

    return cfg.unknown_semantics


_DESTRUCTIVE_KEYWORDS: tuple[str, ...] = (
    "销毁", "清空", "rm -rf", "drop table", "drop database", "truncate",
    "格式化", "不可恢复", "永久删除", "生产发布", "全量删除",
)


def _keywords_hit(text: str, keywords: tuple[str, ...]) -> bool:
    for kw in keywords:
        if kw.lower() in text:
            return True
    return False


__all__ = [
    "ActionSemantics",
    "ActionSemanticsConfig",
    "COMMAND_LEVEL_TO_SEMANTICS",
    "DEFAULT_TOOL_SEMANTICS",
    "ORDER",
    "at_least",
    "classify_action",
    "command_semantics",
    "get_config",
    "is_destructive",
    "parse_semantics",
    "plan_text_semantics",
    "rank",
    "reload_config",
    "requires_confirmation",
]
