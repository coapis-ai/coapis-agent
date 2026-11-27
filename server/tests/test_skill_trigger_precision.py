"""技能触发精度尺子的契约测试。

全部来自实测误触发，防回流：
  - 单字关键词「函」曾命中「函数」，把无关对话拉去 pptx/公文技能
  - 裸子串 search 曾命中路径里的 web_search.py
  - 正则 做.*汇报 曾跨句命中「做完后…汇报」
"""

import re

from coapis.agents.utils.skill_selector import keyword_matches, safe_pattern


def test_single_char_keyword_never_matches():
    """「函」必须放过「函数」——单字关键词不可信。"""
    assert keyword_matches("函", "帮我改一下这个函数，让它支持批量") is False
    assert keyword_matches("表", "这个表很复杂") is False


def test_ascii_keyword_requires_word_boundary():
    """ASCII 关键词不能扎进标识符/路径内部。"""
    assert keyword_matches("search", "web_search 这个工具怎么用") is False
    assert keyword_matches("search", "读取 /app/tools/web_search.py") is False
    # 但正常独立使用必须命中
    assert keyword_matches("search", "please search this topic") is True
    assert keyword_matches("pdf", "把这份报告转成 pdf 发给老板") is True


def test_chinese_keyword_still_substring():
    """中文没有词边界，多字词仍按子串命中。"""
    assert keyword_matches("读取文件", "读取文件 server/main.py") is True
    assert keyword_matches("重构", "把这段代码重构一下") is True


def test_unbounded_quantifier_is_bounded():
    """.* / .+ 必须被收紧成有界量词，禁止跨句命中。"""
    out = safe_pattern("做.*汇报")
    assert ".*" not in out
    assert re.search(out, "做汇报") is not None

    out2 = safe_pattern("帮我.+生成.+文档")
    assert ".+" not in out2
    # .+ 语义保持：中间必须有字，但不得跨句
    assert re.search(out2, "帮我快速生成一份文档") is not None
    assert re.search(out2, "帮我生成文档") is None
    # 单段间隙超过 16 字（跨句）必须不再命中
    far = "帮我把这个需求的结构先梳理清楚并且补充背景说明然后再生成一份说明文档"
    assert re.search(out2, far) is None


def test_safe_pattern_keeps_normal_pattern_intact():
    """不含贪婪量词的正则应原样保留，别把合法触发改坏。"""
    pat = "转成\\s*(pdf|docx)"
    assert safe_pattern(pat) == pat
    assert re.search(safe_pattern(pat), "把这个文件转成 PDF", re.IGNORECASE)


def test_legit_document_triggers_survive():
    """收紧尺子后，真正的文档类请求仍要能命中。"""
    for msg, kw in (
        ("把这个文件转成 docx", "docx"),
        ("帮我把这个 excel 里的重复行删掉", "excel"),
        ("提取这个 pdf 里的表格", "pdf"),
    ):
        assert keyword_matches(kw, msg.lower()) is True, msg
