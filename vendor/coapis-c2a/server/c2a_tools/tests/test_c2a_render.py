# -*- coding: utf-8 -*-
"""Regression tests for c2a_render_card content normalisation (Mode 1) and
the implicit tool-output converter (Mode 2).

Run from the c2a_tools dir:
    python -m pytest server/c2a_tools/tests/test_c2a_render.py -q
(or directly: python server/c2a_tools/tests/test_c2a_render.py)
"""
import os
import sys

# Make c2a_tools + c2a_protocol importable when running standalone.
_HERE = os.path.dirname(__file__)
_SERVER = os.path.abspath(os.path.join(_HERE, "..", ".."))
sys.path.insert(0, os.path.join(_SERVER, "c2a_tools", "src"))
sys.path.insert(0, os.path.join(_SERVER, "c2a_protocol", "src"))

from c2a_tools.integrations.coapis import render_card_payload
from c2a_tools.converter import convert_tool_output_to_c2a


def _data_table_block(message):
    return next(b for b in message["blocks"] if b["type"] == "data_table")


# ── Mode 1 ────────────────────────────────────────────────────────────────

def test_mode1_columns_rows_at_payload_root():
    """The real-world LLM bug: columns/rows at payload root, content empty."""
    payload = {
        "protocol_version": "1.0",
        "message_id": "msg_2",
        "blocks": [
            {"type": "text_markdown", "content": "## 📋 审批明细（3 条）"},
            {"type": "data_table", "content": {}},
        ],
        "actions": [{"action_id": "btn_export", "label": "导出",
                     "intent": "api_call", "payload": {}}],
        "columns": [
            {"key": "title", "label": "标题"},
            {"key": "applicant", "label": "申请人"},
        ],
        "rows": [
            {"title": "付款申请", "applicant": "张伟"},
            {"title": "差旅报销", "applicant": "李娜"},
            {"title": "采购审批", "applicant": "王强"},
        ],
    }
    r = render_card_payload(c2a_payload=payload)
    assert r["status"] == "success", r.get("errors")
    dt = _data_table_block(r["c2a_message"])
    assert dt["content"]["data"]["headers"] == ["标题", "申请人"]
    assert len(dt["content"]["data"]["rows"]) == 3
    assert dt["content"]["data"]["rows"][0] == ["付款申请", "张伟"]
    # text_markdown normalised from bare string → {"markdown": ...}
    tm = next(b for b in r["c2a_message"]["blocks"] if b["type"] == "text_markdown")
    assert isinstance(tm["content"], dict) and tm["content"]["markdown"].startswith("## 📋")


def test_mode1_empty_table_fails_not_blank_success():
    """A data_table with no recoverable rows must return failed, not success."""
    payload = {
        "protocol_version": "1.0",
        "message_id": "msg_e",
        "blocks": [
            {"type": "text_markdown", "content": "审批明细"},
            {"type": "data_table", "content": {}},
        ],
        "actions": [],
    }
    r = render_card_payload(c2a_payload=payload)
    assert r["status"] == "failed", r
    assert r["errors"] and "table data" in r["errors"][0]


def test_mode1_canonical_content_data_unchanged():
    payload = {
        "protocol_version": "1.0",
        "message_id": "msg_ok",
        "blocks": [
            {"type": "data_table",
             "content": {"data": {"headers": ["名称", "值"],
                                  "rows": [["a", "1"], ["b", "2"]]}}},
        ],
        "actions": [],
    }
    r = render_card_payload(c2a_payload=payload)
    assert r["status"] == "success", r.get("errors")
    assert _data_table_block(r["c2a_message"])["content"]["data"]["rows"] == [["a", "1"], ["b", "2"]]


# ── Mode 2 (implicit tool-output converter) ───────────────────────────────

def test_mode2_nested_data_found():
    nested = {"total": 3, "result": {"items": [
        {"id": 1, "name": "甲", "amount": 100},
        {"id": 2, "name": "乙", "amount": 200},
        {"id": 3, "name": "丙", "amount": 300},
    ]}}
    r = render_card_payload(tool_output=nested, tool_name="approval")
    assert r["status"] == "success", r.get("errors")
    assert len(_data_table_block(r["c2a_message"])["content"]["data"]["rows"]) == 3


def test_mode2_no_data_is_skipped_not_crash():
    r = render_card_payload(tool_output={"message": "ok", "count": 0}, tool_name="t")
    assert r["status"] == "skipped", r


def test_mode2_mixed_list_is_skipped_not_crash():
    r = render_card_payload(tool_output={"items": [{"id": 1}, "str", None]}, tool_name="t")
    assert r["status"] == "skipped", r


def test_converter_mixed_and_non_dict_top_level():
    assert convert_tool_output_to_c2a("t", {"items": [{"id": 1}, "x"]}) is None
    assert convert_tool_output_to_c2a("t", "just a string") is None


def test_converter_depth_limit():
    # 3 nesting levels (a→b→c→items) is found; 4 (a→b→c→d→items) is not.
    assert convert_tool_output_to_c2a("t", {"a": {"b": {"c": {"items": [{"id": 1, "n": "x"}]}}}}) is not None
    assert convert_tool_output_to_c2a("t", {"a": {"b": {"c": {"d": {"items": [{"id": 1}]}}}}}) is None


# ── P0: resilience tests ──────────────────────────────────────────────────

def test_p0_payload_as_valid_json_string():
    """LLM passes c2a_payload as a JSON string → should work (json.loads)."""
    import json as _json
    payload_dict = {
        "protocol_version": "1.0",
        "message_id": "msg_str",
        "blocks": [
            {"type": "data_table",
             "content": {"data": {"headers": ["名称", "值"],
                                  "rows": [["a", "1"]]}}},
        ],
        "actions": [],
    }
    r = render_card_payload(c2a_payload=_json.dumps(payload_dict))
    assert r["status"] == "success", r.get("errors")
    assert len(_data_table_block(r["c2a_message"])["content"]["data"]["rows"]) == 1


def test_p0_payload_as_invalid_json_string():
    """LLM passes c2a_payload as a broken string → graceful failed, no crash."""
    r = render_card_payload(c2a_payload="not valid json {")
    assert r["status"] == "failed", r
    assert any("JSON" in e or "json" in e for e in r["errors"])


def test_p0_invalid_block_type_salvaged():
    """LLM uses a made-up block type but the content is clearly a table."""
    payload = {
        "protocol_version": "1.0",
        "message_id": "msg_salvage",
        "blocks": [
            # "action_link" is not a valid block type, but the content is a table
            {"type": "action_link",
             "content": {"data": {"headers": ["名称", "金额"],
                                  "rows": [["付款", "100"], ["报销", "200"]]}}},
            {"type": "text_markdown", "content": "审批明细"},
        ],
        "actions": [],
    }
    r = render_card_payload(c2a_payload=payload)
    assert r["status"] == "success", r.get("errors")
    # The salvaged block should be a data_table now
    dt = _data_table_block(r["c2a_message"])
    assert dt["content"]["data"]["headers"] == ["名称", "金额"]
    assert len(dt["content"]["data"]["rows"]) == 2


def test_p0_invalid_block_type_unsalvageable():
    """A block with a made-up type AND no recognizable content → skipped."""
    payload = {
        "protocol_version": "1.0",
        "message_id": "msg_skip",
        "blocks": [
            {"type": "mystery_block", "content": {"foo": "bar"}},
            {"type": "text_markdown", "content": "正常块"},
        ],
        "actions": [],
    }
    r = render_card_payload(c2a_payload=payload)
    assert r["status"] == "success", r.get("errors")
    # Only the text_markdown block should survive
    types = [b["type"] for b in r["c2a_message"]["blocks"]]
    assert "mystery_block" not in types
    assert "text_markdown" in types


def test_p0_all_blocks_invalid_fails():
    """All blocks unrecognizable → must return failed, not empty success."""
    payload = {
        "protocol_version": "1.0",
        "message_id": "msg_allbad",
        "blocks": [
            {"type": "nonsense1", "content": {"x": 1}},
            {"type": "nonsense2", "content": {}},
        ],
        "actions": [],
    }
    r = render_card_payload(c2a_payload=payload)
    assert r["status"] == "failed", r
    assert any("no valid blocks" in e for e in r["errors"])


def test_p0_invalid_action_intent_skipped():
    """Action with a made-up intent → skipped, rest of card survives."""
    payload = {
        "protocol_version": "1.0",
        "message_id": "msg_action",
        "blocks": [
            {"type": "text_markdown", "content": "ok"},
        ],
        "actions": [
            {"action_id": "btn1", "label": "有效", "intent": "api_call",
             "payload": {}},
            {"action_id": "btn2", "label": "无效", "intent": "view_detail",
             "payload": {}},
        ],
    }
    r = render_card_payload(c2a_payload=payload)
    assert r["status"] == "success", r.get("errors")
    actions = r["c2a_message"]["actions"]
    assert len(actions) == 1
    assert actions[0]["action_id"] == "btn1"


# ── P1: row-link-from-data tests ──────────────────────────────────────────

def test_p1_url_field_generates_row_links():
    """When data has a detail_url field, row links should use it."""
    data = {"items": [
        {"id": 1, "name": "甲", "detail_url": "/approvals/1"},
        {"id": 2, "name": "乙", "detail_url": "/approvals/2"},
    ]}
    r = render_card_payload(tool_output=data, tool_name="approval")
    assert r["status"] == "success", r.get("errors")
    dt = _data_table_block(r["c2a_message"])
    content = dt["content"]
    # row_actions should exist and point at detail_url
    assert "row_actions" in content, "expected row_actions with url field"
    va = content["row_actions"]["view_detail"]
    assert va["url_template"] == "{detail_url}"
    assert va["link_column"] == "detail_url"
    # detail_url column should be visible in headers
    assert "detail_url" in content["data"]["headers"]


def test_p1_no_url_field_no_row_links():
    """When data has NO url field, no row links should be generated."""
    data = {"items": [
        {"id": 1, "name": "甲", "amount": 100},
        {"id": 2, "name": "乙", "amount": 200},
    ]}
    r = render_card_payload(tool_output=data, tool_name="approval")
    assert r["status"] == "success", r.get("errors")
    dt = _data_table_block(r["c2a_message"])
    content = dt["content"]
    # No fake row_links
    assert "row_actions" not in content, "should not generate row links without URL"
    # No fake top-level actions either
    assert len(r["c2a_message"]["actions"]) == 0, "no fake top-level actions"


def test_p1_url_field_variants():
    """Different URL field names should all be detected."""
    for field_name in ("detail_url", "url", "link", "view_url", "page_url"):
        data = {"items": [
            {"id": 1, "name": "甲", field_name: "https://example.com/1"},
        ]}
        r = render_card_payload(tool_output=data, tool_name="t")
        assert r["status"] == "success", f"{field_name}: {r.get('errors')}"
        dt = _data_table_block(r["c2a_message"])
        assert "row_actions" in dt["content"], f"{field_name} should generate row links"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ✅ {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  ❌ {fn.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"  ❌ {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n==== {len(fns) - failed}/{len(fns)} passed ====")
    sys.exit(1 if failed else 0)
