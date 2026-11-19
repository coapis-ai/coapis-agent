"""登记侧噪音闸口径（``file_ledger._is_noise_rel``）。

背景：展示侧一直有 ``resource_category.NOISE_DIR_PARTS`` 这把尺子，但登记侧
照收不误，于是 ``file_records`` 里堆满 ``.temp/<哈希>/script.py`` 这类工具
临时产物（实测某会话 249 行里 247 行是噪音）。修法是登记侧复用同一把尺子，
本测试锁住口径：该拦的拦、不该拦的绝不拦。
"""

from coapis.foundation.file_ledger import _is_noise_rel


def test_noise_paths_rejected():
    """工具临时产物一律拒收。"""
    for p in (
        ".temp/8406641d/script.py",
        "files/.temp/x/出成稿.md",
        ".trash/old.docx",
        "a/__pycache__/b.pyc",
        "proj/node_modules/x.js",
        "env/.venv/lib/site.py",
        "x/.git/objects/aa/bb",
    ):
        assert _is_noise_rel(p) is True, p


def test_real_deliverables_accepted():
    """正常交付物不能误伤——尤其文件名里带噪音词的。"""
    for p in (
        "2026-11/提取文本.md",
        "media/蜜蜂AI智能体宣传册.pptx",
        "reports/venv.md",          # 文件名含 venv，不是目录
        "notes/temp-notes.md",      # 名字像 temp，不是 .temp 目录
        "a/b/.hidden-清单.txt",     # 前缀相似，不命中
        ".gitignore",               # 单段文件名，非目录段
        "",
    ):
        assert _is_noise_rel(p) is False, p
