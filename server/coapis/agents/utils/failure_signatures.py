# -*- coding: utf-8 -*-
"""失败签名表 —— 把工具失败的原始文本归因成**稳定签名**。

为什么需要它（实施方案 v21 §1③）：现成的空结果闸只认"输出为空"这一种形态，
而真实浪费是"同样一句报错换个姿势再撞一次"——`No such file or directory`、
`Permission denied`、`command not found`……这些文本里本来就带着确定的信号，
不需要模型猜，也不需要判官判。**先归因成签名，才谈得上"同类错误不重犯"**：
连续同类 → 提示换路 → 冷却 → 换个工具成功就归零。

设计边界：

* **纯函数、零依赖、零 LLM**：给一段文本进来，出去是
  ``(签名码, 白话标签, 是否可重试)``。判定顺序=工具专属规则优先，
  再落到 15 类通用签名，最后才是兜底。
* **签名是契约**：新增签名必须先登记 ``SIGNATURES``，闸码/台账/治理页
  都从这里取标签，不散落字符串。
* **兜底也入表**：认不出但确实失败（Traceback / exit code≠0）给
  ``tool_error`` / ``exit_nonzero``，让计数有分母，不静默漏。

对标 QwenPaw 的做法：**不造判定器，只造尺子**——签名稳定后，"改道提示"
与"同类不重犯"都消费同一把尺子，不再各写一套。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# 签名登记表（SSOT）：code -> (白话标签, 是否可重试, 命中模式)
#
# ``retryable`` 语义 = "换个参数/换个路径再试一次有没有意义"。
# False 的签名（权限、依赖缺失、语法错）连续出现时更该立刻换路，
# 而不是继续同样动作。
# ---------------------------------------------------------------------------

SIGNATURES: dict[str, tuple[str, bool, tuple[str, ...]]] = {
    # 1-3：文件系统类
    "file_missing": (
        "文件或路径不存在", True,
        ("no such file or directory", "filenotfounderror", "enoent",
         "does not exist", "path not found", "cannot find the path",
         "没有那个文件或目录", "路径不存在"),
    ),
    "permission": (
        "权限不足", False,
        ("permission denied", "eacces", "operation not permitted",
         "read-only file system", "eperm", "拒绝访问", "权限不足"),
    ),
    "resource": (
        "资源不足（磁盘/内存/句柄）", False,
        ("no space left on device", "enospc", "memoryerror",
         "out of memory", "cannot allocate memory", "too many open files",
         "disk quota exceeded", "killed"),
    ),
    # 4-6：执行环境类
    "missing_dep": (
        "依赖或命令缺失", False,
        ("modulenotfounderror", "importerror", "command not found",
         "not found: ", "no module named", "module not found",
         "pip install", "未找到命令", "不是内部或外部命令"),
    ),
    "timeout": (
        "执行超时", True,
        ("timed out", "timeout", "deadline exceeded", "超时",
         "exceeded the timeout"),
    ),
    "exit_nonzero": (
        "命令退出码非 0", True,
        ("exit code 1", "exit code 2", "exited with code", "command failed",
         "returned non-zero exit status"),
    ),
    # 7-9：网络与远端类
    "network": (
        "网络不可达（DNS/连接/证书）", True,
        ("connection refused", "connection reset", "connection aborted",
         "getaddrinfo failed", "name or service not known", "nameresolutionerror",
         "network is unreachable", "ssl:", "certificate verify failed",
         "net::err_", "fetch failed", "could not fetch", "econnrefused",
         "temporary failure in name resolution"),
    ),
    # 不用裸 "401"/"403"：端口号、字节数里满是这两个串，会误判。
    "auth": (
        "鉴权或凭据失败", False,
        ("unauthorized", "forbidden", "authentication required",
         "authentication failed", "invalid token", "invalid api key",
         "invalid credentials", "access denied", "accessdenied",
         "http 401", "http 403", "status code 401", "status code 403",
         "code 401", "code 403", "认证失败", "凭据无效"),
    ),
    "http_error": (
        "HTTP 状态异常", True,
        ("http error 5", "http 500", "http 502", "http 503", "http 504",
         "bad gateway", "service unavailable", "gateway time-out",
         "status code 5", "5xx"),
    ),
    # 10-12：输入与代码类
    "invalid_arg": (
        "参数不合法", False,
        ("invalid argument", "invalid parameter", "unrecognized argument",
         "unrecognized flag", "unexpected keyword", "typeerror",
         "indexerror", "value error", "is a directory", "is not a directory",
         "usage: ", "参数错误"),
    ),
    "syntax": (
        "语法或解析失败", False,
        ("syntaxerror", "jsondecodeerror", "expecting value", "yaml.",
         "unexpected token", "parse error",
         "parsing error", "编译错误", "语法错误"),
    ),
    "indent": (
        "缩进或格式错", False,
        ("indentationerror", "unexpectedindent", "expected an indented block",
         "could not import", "缩进"),
    ),
    # 13-15：数据与工具类
    "db_error": (
        "数据库操作失败", True,
        ("no such table", "operationalerror", "integrityerror",
         "duplicate key", "deadlock", "database is locked",
         "foreign key constraint", "sqlalchemy.exc"),
    ),
    "empty_result": (
        "无匹配/空结果", True,
        ("no matches found", "no matching", "0 results", "no results",
         "not found in", "no such key", "found nothing", "无匹配",
         "未找到匹配"),
    ),
    "vcs_conflict": (
        "版本库状态冲突", False,
        ("non-fast-forward", "merge conflict", "unmerged paths",
         "would be overwritten", "local changes would", "you have unstaged",
         "nothing to commit", "divergent branches"),
    ),
    # 兜底（必须排最后）
    "tool_error": (
        "工具内部异常", True,
        ("traceback (most recent call last)", "internal server error",
         "exception:", " panicked", "fatal:", "报错", "执行失败"),
    ),
}

#: 检索顺序（兜底放最后，前面的先命中）。auth/permission 有重叠，
#: 权限在前，避免把本地 `Permission denied` 误判成 HTTP 鉴权。
_LOOKUP_ORDER: tuple[str, ...] = (
    "file_missing", "permission", "resource", "missing_dep", "timeout",
    "indent", "syntax", "invalid_arg", "vcs_conflict", "db_error",
    "network", "auth", "http_error", "empty_result", "exit_nonzero",
    "tool_error",
)

# ---------------------------------------------------------------------------
# 工具专属规则（11 个工具键）—— 比通用签名更准，优先匹配
# 值 = ((签名码, (模式, ...)), ...)
# ---------------------------------------------------------------------------

TOOL_RULES: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "execute_shell_command": (
        ("missing_dep", ("command not found", "未找到命令", "没有那个命令")),
        # 脚本本身写坏时，退出码只是表象：SyntaxError 归 syntax 才给得出
        # "改哪一行"的提示，归 exit_nonzero 只能说"命令失败了"。
        # 同理 NameError/TypeError 是脚本内部异常，不是"退出码非 0"。
        ("syntax", ("syntaxerror:", "parseerror:", "unexpected eof")),
        ("indent", ("indentationerror:",)),
        ("tool_error", ("nameerror:", "typeerror:", "attributeerror:",
                        "indexerror:", "keyerror:", "unboundlocalerror:")),
        ("resource", ("no space left on device", "disk quota")),
        ("vcs_conflict", ("non-fast-forward", "would be overwritten",
                          "unstaged changes", "nothing to commit")),
        ("file_missing", ("is a directory", "no such file or directory")),
        # 权限必须排在 exit_nonzero 之前：`exit code 1 / Permission denied` 里
        # 退出码只是表象。判成 exit_nonzero 只能说"命令失败了、换个动作"，
        # 判成 permission 才给得出"重复调用不会有新结果，去解决前置条件"。
        # 实测 dev 最高频的权限形状是 ssh/git 的 `Permission denied (publickey)`，
        # 曾被下面的 exit_nonzero 兜底抢走——分类错了，提示再准也是错的药。
        ("permission", ("permission denied", "operation not permitted",
                        "access denied", "publickey", "eacces", "eperm",
                        "拒绝访问", "权限不足")),
        ("exit_nonzero", ("exit code", "exited with")),
    ),
    "read_file": (
        ("file_missing", ("no such file", "does not exist", "file not found",
                          "no such file or directory")),
        ("invalid_arg", ("is a directory", "binary file", "cannot read")),
    ),
    "write_file": (
        ("permission", ("permission denied", "read-only")),
        ("file_missing", ("no such file", "directory does not exist")),
    ),
    "edit_file": (
        # 我们的 edit_file 未命中时最常见的两种形态
        ("invalid_arg", ("old_text", "not found", "no match",
                         "occurrence", "未找到")),
        ("permission", ("permission denied",)),
    ),
    "grep_search": (
        ("empty_result", ("no matches", "0 matches", "no matching files")),
        ("invalid_arg", ("invalid regular expression", "unterminated")),
    ),
    "glob_search": (
        ("empty_result", ("no files", "no matching", "nothing found")),
    ),
    "browser_use": (
        ("network", ("net::err_", "navigation failed", "target closed",
                     "browsertype.launch", "browser has been closed")),
        ("timeout", ("timeout", "exceeded the timeout", "waiting for")),
        ("invalid_arg", ("strict mode violation", "no element",
                         "element is not attached", "not visible",
                         "selector")),
    ),
    "web_fetch": (
        ("network", ("fetch failed", "could not fetch", "econnrefused",
                     "getaddrinfo")),
        ("auth", ("401", "403", "unauthorized", "forbidden",
                  "requires authentication")),
        ("http_error", ("status code", "http error", "not found")),
    ),
    "web_search": (
        ("resource", ("rate limit", "quota", "too many requests", "429")),
        # 顺序即优先级：搜索后端自己抛异常时，"web_search failed" 里的
        # failed 不是网络故障——判成 network 会让模型去重试网络，
        # 而真正该做的是别再传那个参数。
        ("invalid_arg", ("unexpected keyword argument",)),
        ("tool_error", ("typeerror:", "valueerror:", "keyerror:",
                        "attributeerror:", "traceback (most recent call last)")),
        ("empty_result", ("no results", "未检索到", "没有找到相关")),
        ("network", ("failed to search", "search failed", "无法连接",
                     "连接失败", "dns", "unreachable")),
    ),
    "send_file_to_user": (
        ("file_missing", ("no such file", "not found", "does not exist")),
    ),
    "view_image": (
        ("invalid_arg", ("cannot open", "unsupported", "cannot decode",
                         "not an image", "corrupt")),
        ("file_missing", ("not found", "does not exist", "no such file")),
    ),
}

# 工具键别名（不同注册名共用一套规则）
TOOL_ALIASES: dict[str, str] = {
    "view_video": "view_image",
    "send_file": "send_file_to_user",
    "bash": "execute_shell_command",
    "shell": "execute_shell_command",
    "run_command": "execute_shell_command",
}

# MCP 工具是动态命名（mcp__server__tool / xxx_mcp_yyy），单独一条前缀规则
_MCP_MARKERS = ("mcp__", "_mcp_", "mcp-server")
_MCP_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("network", ("server not connected", "connection closed",
                 "channel closed", "browser has been closed",
                 "not running", "connection reset")),
    ("invalid_arg", ("-32601", "method not found", "invalid params",
                     "-32602", "unknown tool")),
)


@dataclass(frozen=True)
class FailureSignature:
    """一次工具失败的归因结果。"""

    code: str
    label: str
    retryable: bool
    tool: str = ""
    matched: str = ""   # 命中的模式（排查签名表时用，不给用户看）

    def __str__(self) -> str:  # pragma: no cover - 日志友好
        return f"{self.code}({self.label})"


#: 失败前置闸：没有这些"失败口气"的词，一律当成功。
#: 原因：read_file / grep_search 的输出**就是文件内容**，里面出现
#: "not found" 之类的字样太正常了，不做前置判定就会把成功当失败。
_FAILURE_MARKERS: tuple[str, ...] = (
    "error", "failed", "failure", "exception", "traceback", "denied",
    "no such", "not exist", "timeout", "timed out",
    "refused", "reset by peer", "unauthorized", "forbidden", "invalid",
    "cannot", "can't", "unable", "not supported", "unsupported",
    "exit code", "exited with", "killed", "panic", "fatal", "critical",
    "no space left", "disk quota", "out of memory", "cannot allocate",
    "警告", "错误", "失败", "异常", "无法", "不存在", "超时", "拒绝",
    "越界", "不合法",
)

#: "空结果"这类话只有在**短输出**里才算失败：文件正文里写一句
#: "no matching files" 太常见，长文本一律不当失败。
_EMPTY_MARKERS: tuple[str, ...] = (
    "no matches", "no matching", "no files", "no results", "0 results",
    "nothing found", "not found", "not connected", "not running",
    "rejected", "conflict", "未找到", "无匹配", "没有匹配",
)
_EMPTY_MAX_LEN = 160


def looks_like_failure(body: str) -> bool:
    """是否带"失败口气"。纯函数，供 classify 与单测复用。"""
    low = str(body or "").lower()
    if any(m in low for m in _FAILURE_MARKERS):
        return True
    if len(low) > _EMPTY_MAX_LEN:
        return False
    return any(m in low for m in _EMPTY_MARKERS)


# ---------------------------------------------------------------------------
# 两级闸门（近 7 天 53k 条真实工具结果实测出来的教训）
#
# 直接"全文找错误词"会把**读文件/grep 的正文**当成失败：真实语料里 643 条
# timeout、419 条 invalid_arg、188 条 syntax 全是误伤——那些只是被 grep 到的
# 代码里写着 `timeout` / `TypeError` / "报错" 两个字。所以：
#
# * **Tier A 头部确定性短语**：只认输出**开头**出现的、几乎不会作为正文出现的
#   短语（`command not found` / `Traceback (most recent call last)` …）。
# * **Tier B 失败前言**：输出开头带失败口气（正则带词边界，`onerror` 不算），
#   这时才敢拿完整输出做细粒度归因。
# * 两级都不过 → 当成功。宁可漏判，不可把"读文件成功"判成失败。
# ---------------------------------------------------------------------------

_HEAD_CHARS = 200

#: Tier A：出现在输出开头就足以定性的短语
_DEFINITE_HEAD: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("missing_dep", ("command not found", "未找到命令", "no module named",
                     "modulenotfounderror", "importerror")),
    ("resource", ("no space left on device", "disk quota exceeded",
                  "cannot allocate memory")),
    ("permission", ("permission denied", "operation not permitted")),
    ("file_missing", ("no such file or directory", "filenotfounderror")),
    ("network", ("net::err_", "connection refused", "could not resolve host")),
    ("vcs_conflict", ("non-fast-forward", "merge conflict detected")),
    # 构建失败的经典句式："make: *** [Makefile:12: all] Error 2"。它写成
    # "Error 2" 而不是 "Error:"，走不过 `_PREAMBLE_RE` 的词边界，但这行本身
    # 就是确定性失败——归不出因就等于白拦。
    ("exit_nonzero", ("make: ***",)),
    ("syntax", ("syntaxerror:", "jsondecodeerror:", "parseerror:")),
    ("indent", ("indentationerror:",)),
    ("db_error", ("operationalerror:", "integrityerror:",
                  "database is locked", "no such table")),
    ("timeout", ("timed out after", "deadline exceeded", "timed out waiting")),
    ("tool_error", ("traceback (most recent call last)", "panicked")),
)

#: Tier B：输出开头带这些词才算"这是一次失败"（词边界匹配，正文里的
#: `onerror` / `on_failure` 不会命中）
_PREAMBLE_RE = re.compile(
    r"(?:^|[\s\[\{:(>»`\"'])(error|errors|failed|failure|exception|traceback"
    r"|denied|refused|forbidden|unauthorized|invalid|cannot|unable|fatal"
    r"|panic|killed|timed out|timeout|usage:|exit code|exited with"
    r"|no such|no match|no matches|no matching|no results|no files"
    r"|nothing found|not found|not connected|not running|not exist"
    r"|not supported|unsupported|critical"
    r"|警告|错误|失败|异常|无法|不存在|超时|拒绝|越界|未找到|不合法)"
    r"(?:[\s:：,，。!?.»`\"'\]]|$)"
)

_PREAMBLE_EXTRA: tuple[str, ...] = (
    '"ok": false', '"ok":false', '"success": false', '"success":false',
    "⚠", "❌", "✗", "[error]", "[fail]", "approval for",
)


def _head_of(body: str) -> str:
    return body[:_HEAD_CHARS]


def _definite_head_hit(head: str) -> tuple[str, str] | None:
    """Tier A：开头 200 字符内的定性短语。返回 (签名码, 命中短语)。"""
    for code, patterns in _DEFINITE_HEAD:
        for pat in patterns:
            if pat in head:
                return code, pat
    return None


def _has_preamble(head: str) -> bool:
    """Tier B：开头是否就是失败口气。"""
    if any(m in head for m in _PREAMBLE_EXTRA):
        return True
    return bool(_PREAMBLE_RE.search(head))


#: Python 异常行（NameError: / AttributeError: / UnboundLocalError: …）。
#: 这类文案一直漏在闸外：`nameerror:` 里虽然含 "error:"，但前面紧贴字母、
#: 不满足 `_PREAMBLE_RE` 的词边界，而工具常常只把异常名加一行消息打出来
#: （没 traceback、也没 "Error:"）。锚定**首行**开头才认——正文或匹配行里
#: 引用的异常名（"grep 搜到一处 NameError:"）不算工具失败。
_EXCEPTION_HEAD_RE = re.compile(r"[a-z_][a-z0-9_]*error\s*:")
_EXCEPTION_MAX_CHARS = 400


def _has_failure_signal(body: str, head: str) -> bool:
    """失败证据的唯一实现：定性短语 / 失败口气 / 短输出首行的 Python 异常行。

    `is_failure_output`（要不要记账）与 `classify_failure`（归不归得出因）必须
    用同一把尺子——否则会出现"闸认它是失败、归因却返回 None"的空转：账记了，
    签名却是空的，发现闭环拿不到 canary，等于白记账。
    """
    if _definite_head_hit(head) is not None or _has_preamble(head):
        return True
    return (len(body) <= _EXCEPTION_MAX_CHARS
            and _EXCEPTION_HEAD_RE.match(head) is not None)


def is_failure_output(output: str) -> bool:
    """对外：这段输出是不是失败（只过两级闸，不做细归因）。"""
    body = str(output or "").strip().lower()
    if not body:
        return False
    return _has_failure_signal(body, _head_of(body))


def _tool_rules(tool_name: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """取工具专属规则；MCP 动态工具走专用规则。"""
    name = str(tool_name or "").strip().lower()
    if not name:
        return ()
    key = TOOL_ALIASES.get(name, name)
    rules = TOOL_RULES.get(key, ())
    lowered = str(tool_name or "").lower()
    if any(marker in lowered for marker in _MCP_MARKERS):
        return tuple(rules) + _MCP_RULES
    return rules


#: 输出正文=用户数据的工具。这几个只认**专属规则**，不跑通用签名表——
#: 文件正文/匹配行/历史原文里出现 "path not found"、"does not exist" 太正常，
#: 通用表会让"读文件成功"变成"读文件失败"。recall_* 更极端：它的输出
#: 本身就是历史工具原文，等于把昨天的报错又端一遍。
CONTENT_TOOLS: frozenset[str] = frozenset({
    "read_file", "grep_search", "glob_search",
    "recall_history", "recall_tool", "memory_search",
})


def _is_content_tool(tool_name: str) -> bool:
    name = str(tool_name or "").strip().lower()
    return TOOL_ALIASES.get(name, name) in CONTENT_TOOLS


def classify_failure(tool_name: str, output: str) -> FailureSignature | None:
    """把工具输出归因成失败签名；成功（认不出失败）返回 ``None``。

    判定顺序：① 工具专属规则 ② 15 类通用签名 ③ 兜底（Traceback / exit code）。
    纯函数，无副作用、无 IO、无 LLM。
    """
    body = str(output or "").strip().lower()
    if not body:
        return None
    # 两级闸：开头既没有定性短语、也没有失败口气 → 当成功。
    # 这一条挡掉的是"读文件/grep 正文里写着 timeout / TypeError"的误伤。
    head = _head_of(body)
    definite = _definite_head_hit(head)
    if definite is None and not _has_failure_signal(body, head):
        return None

    for code, patterns in _tool_rules(tool_name):
        for pat in patterns:
            if pat in body:
                return _build(code, str(tool_name or ""), pat)

    # 正文型工具到此为止：专属规则没命中就用定性结论，绝不跑通用表兜底
    if _is_content_tool(tool_name):
        return _build(definite[0], str(tool_name or ""), definite[1]) if definite else None

    for code in _LOOKUP_ORDER:
        _label, _retry, patterns = SIGNATURES[code]
        for pat in patterns:
            if pat in body:
                return _build(code, str(tool_name or ""), pat)

    # 兜底：显式失败标记之外，仍认 "Error:" 这一最常见形态
    if "error:" in body or "failed:" in body or "失败:" in body:
        return _build("tool_error", str(tool_name or ""), "error:")
    # 走到这里说明开头是定性失败短语，但通用表没接住——用定性结论
    if definite is not None:
        return _build(definite[0], str(tool_name or ""), definite[1])
    return None


def _build(code: str, tool: str, matched: str) -> FailureSignature:
    label, retryable, _patterns = SIGNATURES[code]
    return FailureSignature(code=code, label=label, retryable=retryable,
                            tool=tool, matched=matched)


def signature_label(code: str) -> str:
    """签名码 → 白话（治理页/提示语用）。未登记返回码本身。"""
    item = SIGNATURES.get(str(code or ""))
    return item[0] if item else str(code or "")


def is_retryable(code: str) -> bool:
    item = SIGNATURES.get(str(code or ""))
    return bool(item[1]) if item else True


def signature_codes() -> tuple[str, ...]:
    return tuple(SIGNATURES.keys())


def hint_text(sig: FailureSignature, streak: int) -> str:
    """连续同类失败时的改道提示（写回工具结果，模型看得见；用户看得见）。

    口径：只说"发生了什么 + 下一步该怎么换"，不堆术语，不指责。
    不可重试的签名（权限/依赖/语法）说得更硬——重复同样动作不会有新结果。
    """
    tool = sig.tool or "这个工具"
    head = f"⚠️ {tool} 已连续 {streak} 次「{sig.label}」。"
    if not sig.retryable:
        tail = (
            "重复同样的调用不会有新结果：先解决前置条件（路径/权限/依赖/参数），"
            "或换一条路；确实做不了就说明卡在哪，别硬试。"
        )
    else:
        tail = (
            "别再原样重试：换一个动作（先确认真实情况再动手，或换个工具/路径）；"
            "两条路都不通就停下来把障碍说清楚。"
        )
    return head + tail


__all__ = [
    "FailureSignature",
    "SIGNATURES",
    "TOOL_RULES",
    "TOOL_ALIASES",
    "classify_failure",
    "hint_text",
    "is_retryable",
    "looks_like_failure",
    "signature_codes",
    "signature_label",
]
