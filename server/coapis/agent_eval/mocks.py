# -*- coding: utf-8 -*-
"""Mock tools injected into the eval agent's ToolRegistry.

Deterministic fixtures so scores are reproducible. Functions follow the
native ``ToolRegistry`` convention: plain ``dict``/``str`` return values,
schema auto-generated from docstrings and signatures.

``mock_oa_todo_list`` has a flaky mode (first call raises) used by the
failure-recovery task (pl-06).
"""

from __future__ import annotations

from typing import Optional

_TODOS = [
    {"id": 1, "title": "采购合同审批", "dept": "采购部", "urgency": "高"},
    {"id": 2, "title": "出差报销单", "dept": "市场部", "urgency": "中"},
    {"id": 3, "title": "设备采购申请", "dept": "研发部", "urgency": "高"},
    {"id": 4, "title": "加班申请", "dept": "客服部", "urgency": "低"},
    {"id": 5, "title": "供应商付款审批", "dept": "财务部", "urgency": "中"},
]

_CALENDAR = [
    {"day": "周一", "time": "09:30", "title": "晨会"},
    {"day": "周二", "time": "14:00", "title": "项目评审会"},
    {"day": "周四", "time": "10:00", "title": "供应商洽谈"},
    {"day": "周五", "time": "15:00", "title": "周站会"},
]

_DOCS = {
    "季度报告": [
        {"name": "2026Q2季度经营分析报告.pdf", "summary": "营收同比+12%，毛利率稳定"},
        {"name": "Q3季度报告模板.docx", "summary": "标准季度报告结构与填写说明"},
    ],
    "报销制度": [
        {"name": "员工报销管理制度V3.pdf",
         "summary": "单次报销上限5000元，超过需总监审批；差旅住宿上限400元/晚"},
    ],
    "差旅标准": [
        {"name": "差旅费用管理办法.pdf",
         "summary": "高铁二等座/飞机经济舱；一线城市住宿400元/晚，其他城市300元/晚"},
    ],
    "竞品A": [
        {"name": "竞品A市场分析报告.pptx", "summary": "竞品A市占率约18%，主打性价比"},
    ],
    "审批": [
        {"name": "OA审批流程指引.pdf", "summary": "常规审批两级，金额超10万三级审批"},
    ],
}


def _flaky_reset() -> None:
    _FLAKY_STATE.update(armed=False, fired=False)


_FLAKY_STATE = {"armed": False, "fired": False}


def arm_flaky_once() -> None:
    """Arm the next ``mock_oa_todo_list`` call to fail exactly once.

    Called by the runner for the failure-recovery task (pl-06).
    """
    _FLAKY_STATE.update(armed=True, fired=False)


def reset_flaky() -> None:
    _flaky_reset()


def mock_oa_todo_list() -> dict:
    """查询OA系统中的待审批事项列表。返回包含id/title/dept/urgency的数组。"""
    if _FLAKY_STATE["armed"] and not _FLAKY_STATE["fired"]:
        _FLAKY_STATE["fired"] = True
        raise RuntimeError("mock: OA服务临时不可用（模拟故障）")
    return {"count": len(_TODOS), "todos": _TODOS}


def mock_oa_calendar_query(day: Optional[str] = None) -> dict:
    """查询OA日程/会议安排。可按星期过滤。

    Args:
        day: 可选，如"周一"；为空返回本周全部。
    """
    items = [c for c in _CALENDAR if not day or c["day"] == day]
    return {"meetings": items}


def mock_oa_doc_search(keyword: str) -> dict:
    """在企业文档库中按关键词检索文档。

    Args:
        keyword: 检索关键词，如"季度报告"。
    """
    kw = keyword.strip()
    hits = _DOCS.get(kw)
    if hits is None:
        for key, val in _DOCS.items():
            if kw in key:
                hits = val
                break
    return {"keyword": keyword, "results": hits or []}


def mock_email_send(to: str, subject: str, body: str) -> dict:
    """发送邮件（mock，不落真实邮箱）。

    Args:
        to: 收件人邮箱地址。
        subject: 邮件主题。
        body: 邮件正文。
    """
    return {
        "ok": True,
        "to": to,
        "subject": subject,
        "accepted_at": "2026-09-26T12:00:00Z",
    }


MOCK_TOOLS = [
    mock_oa_todo_list,
    mock_oa_calendar_query,
    mock_oa_doc_search,
    mock_email_send,
]
