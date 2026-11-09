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
"""

from __future__ import annotations

from pathlib import Path
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
