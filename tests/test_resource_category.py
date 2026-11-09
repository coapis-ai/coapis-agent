"""v20 · W1 一致性测试：前后端类别尺子必须逐字同表。

验收第 10 条：「taxonomy 端点返回注册表，前端图标/筛选/预览判定无本地
第二张表」——前端为渲染同步性保留了一份 `EXT_TO_CATEGORY`
(client/src/pages/Chat/components/resourceCategory.ts)，本测试把两份表
逐项对账：任何一边加/删扩展名而另一边没跟上，立刻红。
"""

from __future__ import annotations

import re
from pathlib import Path

from coapis.foundation.resource_category import (
    CHAT_EXPORT_PREFIXES,
    VALID_CATEGORIES,
    _EXT_TO_CATEGORY,
    category_counts,
    ext_of,
    is_chat_record_path,
    resolve_category,
)

TS_FILE = (
    Path(__file__).resolve().parents[1]
    / "client"
    / "src"
    / "pages"
    / "Chat"
    / "components"
    / "resourceCategory.ts"
)


def _parse_ts_table() -> dict[str, str]:
    src = TS_FILE.read_text(encoding="utf-8")
    block = src[src.index("EXT_TO_CATEGORY") :]
    table: dict[str, str] = {}
    # put( "cat", "ext ext" + "ext ext" ) 四种写法都要认：同行、跨行、串接、
    # **引号与 ) 之间换行**（旧正则要求紧邻 ")"，跨行写法成串丢失——66 项被吞）
    for cat, lits in re.findall(
        r'put\(\s*"([a-z_]+)",\s*((?:"[^"]*"(?:\s*\+\s*"[^"]*")?)\s*,?\s*)\s*\)',
        block,
        flags=re.DOTALL,
    ):
        for lit in re.findall(r'"([^"]*)"', lits):
            for e in lit.split():
                table[e] = cat
    # 自检尺子：解析条数 < 后端表 = 解析器塌了，必须红，不许把"丢项"当"漂移"
    assert len(table) >= len(_EXT_TO_CATEGORY), (
        f"前端表解析出 {len(table)} 项 < 后端 {len(_EXT_TO_CATEGORY)} 项，"
        "解析正则没吃下前端的全部写法——先修这个测试，别改业务代码"
    )
    return table


def test_ts_file_exists():
    assert TS_FILE.is_file(), f"前端尺子文件丢失: {TS_FILE}"


def test_category_enum_matches():
    src = TS_FILE.read_text(encoding="utf-8")
    # 枚举成员以 "|" 分隔，**最后一个以 ";" 收尾**——旧正则要求 "|" 把末项漏掉
    ts_cats = set(re.findall(r'"([a-z_]+)"\s*[|;]', src))
    assert ts_cats == set(VALID_CATEGORIES), (
        "类别枚举漂移：前端 vs 后端 差异="
        f"{ts_cats ^ set(VALID_CATEGORIES)}"
    )


def test_ext_table_matches():
    ts = _parse_ts_table()
    assert ts, "前端 EXT 表解析为空（改写法了？同步改这个测试）"
    assert ts == _EXT_TO_CATEGORY, (
        "扩展名表漂移（前端加/删了扩展名，后端没跟上，反之亦然）："
        f"仅前端={set(ts.items()) - set(_EXT_TO_CATEGORY.items())} "
        f"仅后端={set(_EXT_TO_CATEGORY.items()) - set(ts.items())}"
    )


def test_chat_export_prefixes_match():
    src = TS_FILE.read_text(encoding="utf-8")
    m = re.search(r"CHAT_EXPORT_PREFIXES = \[([^\]]+)\]", src)
    assert m, "前端 CHAT_EXPORT_PREFIXES 表丢失"
    ts = {p.strip().strip('"').strip("'") for p in m.group(1).split(",")}
    assert ts == set(CHAT_EXPORT_PREFIXES), (
        f"聊天导出前缀漂移：{ts ^ set(CHAT_EXPORT_PREFIXES)}"
    )


# ── W5 · 判定逻辑单测（写侧读侧共用的唯一换算函数）──────────────

def test_ext_of():
    assert ext_of("a/b/photo.JPG") == "jpg"
    assert ext_of("no_ext_file") == ""
    assert ext_of(".gitignore") == "gitignore"
    assert ext_of("win\\path\\x.Py") == "py"


def test_chat_record_paths():
    # 导出目录 + 记录命名 → 聊天记录
    assert is_chat_record_path("exports/对话记录_2026-11-01.md")
    assert is_chat_record_path("chat_exports/chat-record-abc.md")
    assert is_chat_record_path("./exports/conversation.log")
    # media/ 目录里只有命名命中"记录"才算聊天记录，普通图片按扩展名分类
    assert not is_chat_record_path("media/photo.png")
    assert is_chat_record_path("media/对话记录_2026-11-01.md")
    # 普通工作区路径不算
    assert not is_chat_record_path("docs/report.pdf")


def test_resolve_category_kind_mapping():
    assert resolve_category("web", "https://example.com/x") == "web"
    assert resolve_category("web", "chat-export:会话转写") == "chat_record"
    assert resolve_category("db", "any/path") == "db_record"
    assert resolve_category("kb", "any/path") == "kb_entry"
    assert resolve_category("mcp", "server:tool") == "mcp_tool"
    assert resolve_category("unknown_kind", "x/y") == "other"
    assert resolve_category("", "") == "other"


def test_resolve_category_file():
    # 导出目录的 md 语义是"记录"，优先于按扩展名的"文档"
    assert resolve_category("file", "exports/对话记录.md") == "chat_record"
    assert resolve_category("file", "media/photo.PNG") == "image"
    assert resolve_category("file", "a/b/data.xlsx") == "sheet"
    assert resolve_category("file", "src/main.py") == "code"
    # 无扩展名按整文件名查（Dockerfile 类）
    assert resolve_category("file", "deploy/Dockerfile") == "code"
    # 落空 → other（36% 隐形问题的归宿：有数可看，不再无名）
    assert resolve_category("file", "mystery/xyzqwerty") == "other"
    assert resolve_category("file", "notes/README") == "other"


def test_category_counts_backfill_free():
    rows = [
        {"kind": "file", "path": "media/a.png"},        # 无 category → 现场换算
        {"kind": "file", "path": "exports/对话记录.md"},
        {"kind": "kb", "path": "x"},
        {"kind": "file", "path": "legacy.docx", "category": "doc"},  # 已回填
    ]
    assert category_counts(rows) == {"image": 1, "chat_record": 1, "kb_entry": 1, "doc": 1}
