# -*- coding: utf-8 -*-
"""资源类别注册表（v20 · W1 · 拍板 D1）——聊天引用/生成资源的**统一分类尺子**。

背景（小蜜蜂 2026-11-09「资源管理检查」）：平台对"资源"原本只有 **kind 五档**
（file/db/kb/mcp/web），它回答的是"资源从哪个子系统来"，不是"用户手里这是
个什么东西"。一百多个台账行里 file 占九成，列表只能显示一排相同的图标；
前端预览侧另有一套 `PreviewKind`（image/pdf/markdown/text/office），两套
词表互不相认，也没有任何一处按"办公/图片/网页/聊天记录"这种用户语义分类。

本模块是**后端的唯一尺子**：

- ``VALID_CATEGORIES``：类别枚举（台账列、API 过滤、统计分组共用）；
- ``resolve_category(kind, path)``：kind+路径 → 类别的唯一函数；
- 前端配套尺子在 ``client/src/pages/Chat/components/resourceCategory.ts``，
  两侧扩展名表由 ``tests/test_resource_category.py`` 做**双向对账**
  （惯例沿用 file_kind_registry：TS 为源，Python 对账，测试防漂移）。

类别语义（给用户的口径）：
    doc         文档（md/txt/doc…——可读的正文）
    sheet       表格（xlsx/csv…——数据表）
    slide       演示与图（ppt/mermaid/drawio——给人看的图页）
    pdf         PDF（单独一档：预览链独立，量也大）
    image       图片
    media       音视频
    archive     压缩包
    code        代码/脚本
    web         网页与外部链接
    chat_record 聊天记录（导出/会话转写——平台自身产出的"会话记录"）
    db_record   数据库条目
    kb_entry    知识条目
    mcp_tool    MCP 工具
    other       兜底（未知扩展名一律进这里，不丢）

第二把尺子（v26 · F1，文件末尾）：``is_system_path`` —— 回答"这条路径**根本
不该是资源**吗"。类别回答"这是什么东西"，系统路径尺子回答"用户手里有没有
这个东西"。采集闸门、会话收尾补扫、巡检、读面过滤共用它。
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Optional

#: 类别枚举。台账 ``category`` 列、`GET /resources?category=`、stats 分组
#: 共用这一份；新类别必须先进这里，禁止端点/前端私造词。
VALID_CATEGORIES = frozenset(
    {
        "doc",
        "sheet",
        "slide",
        "pdf",
        "image",
        "media",
        "archive",
        "code",
        "web",
        "chat_record",
        "db_record",
        "kb_entry",
        "mcp_tool",
        "other",
    }
)

#: 展示排序（管理页/统计面板按此顺序，稳定不随数据变）。
CATEGORY_ORDER = (
    "doc",
    "sheet",
    "slide",
    "pdf",
    "image",
    "media",
    "archive",
    "code",
    "web",
    "chat_record",
    "db_record",
    "kb_entry",
    "mcp_tool",
    "other",
)

# ── 文件扩展名 → 类别 ──────────────────────────────────────────────
# 与前端 resourceCategory.ts 的 EXT 表**逐项一致**（一致性测试对账）。
# 注意：这里的键必须是**小写无点**扩展名；空扩展名走 other。

IMAGE_EXTS = frozenset(
    {
        "png", "jpg", "jpeg", "gif", "webp", "svg", "bmp",
        "ico", "tiff", "tif", "avif", "heic", "jfif",
    }
)
PDF_EXTS = frozenset({"pdf"})
DOC_EXTS = frozenset(
    {
        "md", "markdown", "mdx", "txt", "log", "rtf", "odt",
        "doc", "docx", "epub", "typ", "quarto", "adoc", "asciidoc",
    }
)
SHEET_EXTS = frozenset(
    {"xls", "xlsx", "xlsm", "csv", "tsv", "ods", "numbers", "parquet"}
)
SLIDE_EXTS = frozenset(
    {
        "ppt", "pptx", "odp", "key",
        # 图/示意类：mermaid 是图，drawio 是图——它们不是"文档正文"。
        "mmd", "mermaid", "drawio",
    }
)
MEDIA_AUDIO_EXTS = frozenset({"mp3", "wav", "m4a", "flac", "ogg", "aac", "opus"})
MEDIA_VIDEO_EXTS = frozenset({"mp4", "mov", "avi", "mkv", "webm", "m4v", "wmv"})
ARCHIVE_EXTS = frozenset(
    {"zip", "tar", "gz", "tgz", "bz2", "xz", "7z", "rar", "gz2", "zst"}
)
CODE_EXTS = frozenset(
    {
        "py", "pyi", "ipynb", "js", "mjs", "cjs", "ts", "tsx", "jsx", "vue",
        "java", "go", "rs", "c", "cc", "cpp", "h", "hpp", "cs", "php", "rb",
        "sh", "bash", "zsh", "ps1", "bat", "sql", "yaml", "yml", "json",
        "toml", "ini", "env", "dockerfile", "tf", "pl", "lua", "r", "jl",
    }
)
WEB_FILE_EXTS = frozenset({"html", "htm", "xhtml"})

#: 聊天记录导出的目录口径：聊天"导出对话"落在工作区 ``exports/`` 下
#: （app/routers/chats.py），会话转写/记录类文件名特征也认。
CHAT_EXPORT_PREFIXES = ("exports/", "chat_exports/", "media/")
CHAT_NAME_HINTS = ("对话记录", "聊天记录", "chat-record", "chat_record",
                   "conversation")

_EXT_TO_CATEGORY: dict[str, str] = {}
for _exts, _cat in (
    (IMAGE_EXTS, "image"),
    (PDF_EXTS, "pdf"),
    (SHEET_EXTS, "sheet"),
    (SLIDE_EXTS, "slide"),
    (DOC_EXTS, "doc"),
    (MEDIA_AUDIO_EXTS, "media"),
    (MEDIA_VIDEO_EXTS, "media"),
    (ARCHIVE_EXTS, "archive"),
    (CODE_EXTS, "code"),
    (WEB_FILE_EXTS, "web"),
):
    for _e in _exts:
        # 先到先得：同一扩展名只属于一个类别（注册表自身保证无歧义）。
        _EXT_TO_CATEGORY.setdefault(_e, _cat)


def ext_of(path: str) -> str:
    """小写无点扩展名；无扩展名返回 ""。

    ``Dockerfile`` 这类"整名即扩展名"的文件在 CODE_EXTS 里直接登记了
    ``dockerfile`` 全名，这里取 suffix 会得 ``""`` —— 由调用方按文件名
    兜底（见 resolve_category）。
    """
    name = str(path).replace("\\", "/").rsplit("/", 1)[-1]
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[-1].lower()


def is_chat_record_path(path: str) -> bool:
    """路径是否属于"聊天记录"语义（导出目录 / 记录命名）。"""
    norm = str(path).replace("\\", "/").strip().lower().lstrip("./")
    if norm.startswith(CHAT_EXPORT_PREFIXES):
        # media/ 是聊天上传/生成媒体目录：里面的文件按扩展名分类更准，
        # 只有命名命中"记录"特征的才算聊天记录。
        return any(h in norm for h in CHAT_NAME_HINTS)
    return any(h in norm for h in CHAT_NAME_HINTS)


def resolve_category(kind: str, path: str) -> str:
    """kind + 路径 → 类别。**唯一换算函数**，写侧读侧都走这里。

    规则优先级（自上而下，先命中先返回）：
      1. 非 file 类：kind 直接映射（web→web、db→db_record、kb→kb_entry、
         mcp→mcp_tool）；聊天导出型 web 路径（``chat-export:`` 前缀）→
         chat_record。
      2. file 类：导出目录/记录命名 → chat_record（办公导出、会话转写
         优先于按扩展名的粗分类——导出的 md 语义是"记录"不是"文档"）。
      3. 扩展名查表；无扩展名时按全名查表（Dockerfile）；都落空 → other。
    """
    kind = str(kind or "").strip().lower()
    raw = str(path or "").strip()

    if kind == "web":
        # 聊天导出卡片以 web 资源入库时带 ``chat-export:`` 前缀（W3 约定），
        # 正规 URL 进 web。
        if raw.startswith("chat-export:") or is_chat_record_path(raw):
            return "chat_record"
        return "web"
    if kind == "db":
        return "db_record"
    if kind == "kb":
        return "kb_entry"
    if kind == "mcp":
        return "mcp_tool"
    if kind != "file":
        return "other"

    if is_chat_record_path(raw):
        return "chat_record"
    ext = ext_of(raw)
    if ext:
        cat = _EXT_TO_CATEGORY.get(ext)
        if cat:
            return cat
    # 无扩展名/未知扩展名：按整文件名查（Dockerfile / Makefile 这类）
    stem = raw.replace("\\", "/").rsplit("/", 1)[-1].lower()
    cat = _EXT_TO_CATEGORY.get(stem)
    if cat:
        return cat
    return "other"


def category_counts(rows: list[dict]) -> dict[str, int]:
    """把台账行按类别聚合成 ``{类别: 数量}``（只含 >0 的项）。

    行内缺 ``category``（迁移前的存量行）时现场用 ``resolve_category`` 换算，
    保证统计面在新列回填完成前也给出正确数字。
    """
    out: dict[str, int] = {}
    for r in rows:
        cat = str(r.get("category") or "").strip()
        if not cat:
            cat = resolve_category(str(r.get("kind") or ""), str(r.get("path") or ""))
        out[cat] = out.get(cat, 0) + 1
    return out


def registry_snapshot() -> dict[str, dict[str, object]]:
    """给一致性测试/排障用的注册表快照（类别 → 扩展名集合）。"""
    return {
        cat: {
            "exts": sorted(
                e for e, c in _EXT_TO_CATEGORY.items() if c == cat
            )
        }
        for cat in CATEGORY_ORDER
    }


# ── 系统路径尺子（v26 · F1，2026-11-10）───────────────────────────────
#
# 起因（小蜜蜂 2026-11-10）：聊天资源条里出现了**根本不存在于用户工作区**
# 的文件，甚至还有 ``MEMORY.md``/``HEARTBEAT.md``/``SKILL.md`` 这类平台
# 自己的运行时文件。实测 dev 台账 113 条可见行里只有 46% 合格：
#   - 52  = /var/log/….log（区外绝对路径）
#   - 11  = /tmp/probe_*.py
#   - 8   = HEARTBEAT.md（平台心跳文件）
#   - 16  = .skills/*/SKILL.md（技能定义）
#   - 81  = .temp/probe_*.py（会话收尾补扫把 1 小时内改动的文件**全**标成
#     producer，探针脚本因此成批入账）
# 根因不是"路径写错"，是**全仓没有"什么算用户的资源"这把尺子**：采集器
# 只判"落在工作区内 + is_file()"，sweep 只判"FS 存在"。
#
# 尺子只写这一处（v20 §1.5 的教训：抄一份规则就是第二把尺子）。采集闸门、
# 会话收尾补扫、巡检补扫、读面过滤**全部调用本函数**。


#: 噪音目录：里面的东西不是用户的"资源"。``.trash`` 是软删归档、``.temp`` 是
#: 脚本暂存。补扫/巡检与消费面补扫共用这一份定义，避免两边口径漂移。
#: （实测 dev：1242 条 unledgered 里 298 条来自 ``.trash``/``.temp``。）
#: v26 · F1：本定义从 ``resource_ledger`` 上移到这里——噪音目录既是巡检
#: 排除项，也是"系统路径"判据的一条，两处必须同一把尺子。
NOISE_DIR_PARTS = frozenset({
    ".trash", ".temp", ".git", "__pycache__", "node_modules", "venv",
    ".venv", "site-packages", ".ipynb_checkpoints",
})

#: 工作区根下"用户拿得到"的目录（交付区）。与前端分桶口径
#: （``resource_ledger.WS_TOP_DIRS``）逐项一致：前端认哪几段能预览/下载，
#: 尺子就认哪几段能当资源，两边不能各有名单。
DELIVERABLE_ROOTS = frozenset(
    {"files", "media", "output", "downloads", "uploads"}
)

#: 平台自身的约定文件（SOUL.md/AGENTS.md 写死的运行时文件）。
#: 判定本身由"首段不在交付目录"这条结构规则完成，这张名单的作用是让规则
#: **说得清、测得住**（回归测试逐条点名），不是判定必需的条件。
PLATFORM_FILE_NAMES = frozenset({
    "MEMORY.md", "PROFILE.md", "SOUL.md", "AGENTS.md", "HEARTBEAT.md",
    "HEARTBEAT.local.md", "BOOTSTRAP.md", "SKILL.md",
})

#: 绝对路径 / 家目录 / URI 形态（台账统一口径是**工作区相对**，出现这些即越界）。
_ABSOLUTEISH_RE = re.compile(r"^(?:[A-Za-z]+://|[A-Za-z]:[\\/]|~|/)")

#: 隐藏段前缀（v26 · F1 补，2026-11-11 实测逼出来的）：交付目录**里面**的
#: 点开头条目是平台/工具的状态文件，不是用户手里的东西——实测 dev 台账里
#: 挂着 ``files/.session_dirs.json``、``files/.session_dirs.lock``（会话目录
#: 锁）、``media/docs/.nojekyll``（站点构建产物），``.session_dirs.lock`` 还是
#: 0 字节。``NOISE_DIR_PARTS`` 是逐条点名的名单，这条是它的一般式：**任何**
#: 点开头的段（目录或文件）都不算用户资源。
HIDDEN_SEGMENT_PREFIX = "."


def is_system_path(
    path: str, *, kind: str = "file", bare_top_file_ok: bool = False
) -> bool:
    """这条路径是不是"平台自己的文件"——**不是**用户手里的资源。

    输入是台账/采集器的**工作区相对**口径（``files/...``、``media/...``）；
    存量裸路径（files 根相对的 ``x.md``）请先过
    ``resource_ledger.workspace_relative_path`` 换算，两侧同一把尺子。

    判 True 的一律不是用户资源：不进采集、不进补扫、不进会话资源清单，
    巡检会把已有的台账行软删（``deleted_at`` 置位，**永不删 FS 文件**）。

    规则（自上而下，先命中先返回）：
      1. 非 file 类（web/db/kb/mcp）不判——它们不是文件，交给各自口径；
      2. 空路径、绝对路径、``~`` 开头、URI 形态：台账口径是工作区相对，
         出现这些就是越界（实测有 /tmp、/var/log、仓库内 SKILL.md）；
      3. 任一段命中噪音目录（``.trash``/``.temp``/``.git``/``__pycache__``…），
         或任一段以 ``.`` 开头（交付区里的平台状态文件
         ``files/.session_dirs.json``、``media/docs/.nojekyll`` 这类）；
      4. 首段不在交付目录（files/media/output/downloads/uploads）——这一条
         同时覆盖工作区根的 MEMORY.md/HEARTBEAT.md、技能目录
         （``.skills/…``/``skills/…/SKILL.md``）、memory/ 日记、scripts/、logs/；
      5. 命中 ``PLATFORM_FILE_NAMES`` 的**根层**文件（防御：交付区里的同名
         文件是用户自己的产物，不在此列）。
    """
    if str(kind or "").strip().lower() != "file":
        return False
    p = str(path or "").replace("\\", "/").strip()
    if not p:
        return True
    if _ABSOLUTEISH_RE.match(p):
        return True
    # URI 混在路径里（v26 · F1 补，2026-11-11 dev 实测）：台账里躺着一条
    # ``http://www.baidu.com/link?url=…`` 当 **file** 行——采集器把网页链接
    # 当成文件登记了。整段前缀尺子看不见它（前缀是 ``files/``），所以按
    # "路径里出现 scheme" 直接判系统：链接是链接，不是用户手里的文件。
    if "://" in p:
        return True
    p = p.lstrip("./")
    parts = PurePosixPath(p).parts
    if not parts:
        return True
    if any(seg in NOISE_DIR_PARTS for seg in parts):
        return True
    # 任何点开头的段（``files/.session_dirs.json``、``media/docs/.nojekyll``…）
    # 都是平台/工具状态，不是用户交付物——``NOISE_DIR_PARTS`` 的一般式。
    if any(str(seg).startswith(HIDDEN_SEGMENT_PREFIX) for seg in parts):
        return True
    # 工作区根上的**散文件**（``loose.md`` 这种没有目录前缀的一段名）：读面
    # 不算交付物（聊天里不该露），但**登记闸门必须放行**——台账要认识它，
    # 资源治理的"归位收件箱"才能把它请进 ``files/_inbox/``。闸门一刀切会把
    # 归位功能打死（2026-11-11 全量回归 ``test_resource_govern_api`` 2 红）。
    if bare_top_file_ok and len(parts) == 1:
        return False
    if parts[0] not in DELIVERABLE_ROOTS:
        return True
    # 交付区内部出现平台约定文件（files/MEMORY.md 这类）：只在"直接位于
    # 交付区根"时判系统，深层目录里的同名文件按用户产物处理。
    if len(parts) == 2 and parts[1] in PLATFORM_FILE_NAMES:
        return True
    return False
