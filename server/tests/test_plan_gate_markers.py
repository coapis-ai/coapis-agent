"""编号步骤必须被当作多步信号（计划显示的入口条件）。

回归背景（v1.2.37）：用户写多步任务几乎都用 1) 1、、（1） 这种编号，
而 _SEQ_MARKER_RE 只认「首先/然后/第一步」，导致「请分四步…1)…4)」
被判 medium，计划骨架提示不注入，聊天里看不到任务计划。
"""

from coapis.agents.plan_gate import ComplexityClassifier, _SEQ_MARKER_RE


def _classify(text: str) -> str:
    return ComplexityClassifier().classify(text)


def test_numbered_steps_count_as_sequential_markers():
    text = (
        "请分四步实际执行：1) 创建 p.txt；2) 创建 q.txt；"
        "3) 合并 p.txt q.txt 到 r.txt；4) 统计 r.txt 行数并报告。"
    )
    assert len(_SEQ_MARKER_RE.findall(text)) >= 2
    assert _classify(text) == "complex"


def test_chinese_paren_and_english_enum_count_too():
    assert _classify(
        "请处理数据：（1）读取 csv；（2）清洗空值；（3）按日期聚合。"
    ) == "complex"
    assert _classify(
        "Please do this: 1. fetch data 2. clean it 3. write report",
    ) == "complex"


def test_versions_and_dates_do_not_inflate_markers():
    """版本号 / 日期不能被当成编号步骤（只数带数字的标记）。"""
    def _numeric_markers(text: str) -> list[str]:
        return [
            m for m in _SEQ_MARKER_RE.findall(text)
            if any(ch.isdigit() for ch in m)
        ]

    for text in (
        "升级到这个包 1.2.3 版本之后有哪些变更",
        "2026.11.16 到 2026.11.20 的日志帮我导出",
    ):
        assert _numeric_markers(text) == []

    assert _classify("帮我把这段话改通顺") == "simple"
    assert _classify("把 /tmp/a.txt 删掉") == "simple"
    # 「今天天气怎么样」2026-11-23 起不再判 simple：答案得联网现查，
    # 这类问题会先立计划再动手（锁在 test_classifier.py::test_1b）。
