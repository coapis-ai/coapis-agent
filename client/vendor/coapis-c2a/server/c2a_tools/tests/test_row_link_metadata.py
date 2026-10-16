# -*- coding: utf-8 -*-
"""Plan B: metadata-driven row links (action_templates.url_template).

Covers:
  * raw MCP wrapper response shape  {"result": "<json>", "metadata": {...}}
  * plain business dict + top-level metadata
  * row_link / view_detail template keys, {fullRoute}-style templates
  * multi-row (style=link) vs single-row (style=button)
  * P1-B fallback (url field in row data) still works without metadata
  * c2a_render_card accepting tool_output as a JSON string
"""
import json

from c2a_tools.converter import convert_tool_output_to_c2a
from c2a_tools.integrations.coapis import render_card_payload


def _oa_metadata():
    """Real OA fetch_pending_approvals metadata (from tools/list)."""
    return {
        "c2a_card_type": "approval",
        "c2a_actions": ["approve_action", "reject_action"],
        "action_templates": {
            "row_link": {
                "label": "查看详情",
                "url_template": (
                    "http://172.16.6.47:8071/bpm/process-instance/detail"
                    "?id={processInstanceId}&taskId={id}&flag=1"
                ),
                "params_mapping": {
                    "processInstanceId": "processInstanceId",
                    "id": "id",
                },
                "business_intent": "view_order_detail",
            }
        },
    }


def _oa_rows(n=3):
    return [
        {
            "id": f"task-{i}",
            "name": f"审批-{i}",
            "title": f"标题{i}",
            "status": "PENDING",
            "processInstanceId": f"proc-{i}",
            "url": None,
            "_title": f"标题{i}",
        }
        for i in range(n)
    ]


def _block_data(msg):
    blocks = [b for b in msg.blocks if b.type == "data_table"]
    assert blocks, "no data_table block"
    return blocks[0].content.data


def test_wrapper_shape_metadata_row_link():
    """Raw MCP wrapper response (result string + metadata) → row links."""
    tool_output = {
        "result": json.dumps(
            {"total": 3, "returned": 3, "data": _oa_rows()}, ensure_ascii=False
        ),
        "is_error": False,
        "metadata": _oa_metadata(),
    }
    msg = convert_tool_output_to_c2a("mcp__oa__fetch_pending_approvals",
                                     tool_output, "sess")
    assert msg is not None
    data = _block_data(msg)
    ra = data["row_actions"]["row_link"]
    assert ra["style"] == "link"
    assert "processInstanceId" in ra["url_template"]

    # row_values must carry BOTH mapped fields per row (id is a hidden col)
    assert data["id_field"] == "id"
    assert data["row_values"][0] == {
        "id": "task-0", "processInstanceId": "proc-0"
    }
    # hidden id column is not a visible header
    assert "id" not in data["data"]["headers"]
    assert "processInstanceId" in data["data"]["headers"]

    # simulate the renderer: fill placeholders from visible cells + row_values
    url = ra["url_template"]
    ctx = dict(data["row_values"][0])
    for ph in ("processInstanceId", "id"):
        url = url.replace("{" + ph + "}", str(ctx[ph]))
    assert url == ("http://172.16.6.47:8071/bpm/process-instance/detail"
                   "?id=proc-0&taskId=task-0&flag=1")


def test_plain_business_dict_with_metadata():
    """LLM passes the business dict directly, metadata merged at top level."""
    tool_output = {
        "total": 3,
        "data": _oa_rows(),
        "metadata": _oa_metadata(),
    }
    msg = convert_tool_output_to_c2a("t", tool_output, "s")
    assert msg is not None
    assert "row_link" in _block_data(msg)["row_actions"]


def test_view_detail_key_multirow_is_link():
    """fetch_project_list uses the 'view_detail' key — multi-row → link."""
    tool_output = {
        "items": [
            {"id": "P1", "name": "项目一", "amount": "100"},
            {"id": "P2", "name": "项目二", "amount": "200"},
        ],
        "metadata": {
            "c2a_card_type": "project",
            "action_templates": {
                "view_detail": {
                    "label": "查看项目详情",
                    "url_template": "http://x/tb/project/detail?id={id}",
                    "params_mapping": {"id": "id"},
                }
            },
        },
    }
    msg = convert_tool_output_to_c2a("t", tool_output, "s")
    data = _block_data(msg)
    ra = data["row_actions"]["view_detail"]
    assert ra["style"] == "link"
    assert data["row_values"][0] == {"id": "P1"}


def test_single_row_template_is_button():
    tool_output = {
        "user": [{"id": "U1", "name": "张三"}],
        "metadata": {
            "action_templates": {
                "view_detail": {
                    "label": "查看详情",
                    "url_template": "http://x/u/{id}",
                    "params_mapping": {"id": "id"},
                }
            }
        },
    }
    msg = convert_tool_output_to_c2a("t", tool_output, "s")
    ra = _block_data(msg)["row_actions"]["view_detail"]
    assert ra["style"] == "button"


def test_full_route_template():
    """fetch_permission_info: url_template is a single {fullRoute} field."""
    tool_output = {
        "data": [
            {"id": "m1", "name": "菜单A", "fullRoute": "/system/menu/a"},
            {"id": "m2", "name": "菜单B", "fullRoute": "/system/menu/b"},
        ],
        "metadata": {
            "action_templates": {
                "row_link": {
                    "label": "打开菜单",
                    "url_template": "{fullRoute}",
                    "params_mapping": {"fullRoute": "fullRoute"},
                }
            }
        },
    }
    msg = convert_tool_output_to_c2a("t", tool_output, "s")
    data = _block_data(msg)
    assert data["row_actions"]["row_link"]["url_template"] == "{fullRoute}"
    # id_field is always carried in row_values (hidden column contract)
    assert data["row_values"][1] == {"id": "m2", "fullRoute": "/system/menu/b"}


def test_no_metadata_url_field_fallback_still_works():
    """P1-B: row data carries a real URL field, no metadata → link kept."""
    tool_output = {
        "items": [
            {"id": 1, "title": "a", "url": "http://x/1"},
            {"id": 2, "title": "b", "url": "http://x/2"},
        ]
    }
    msg = convert_tool_output_to_c2a("t", tool_output, "s")
    data = _block_data(msg)
    assert "view_detail" in data["row_actions"]
    assert data["row_actions"]["view_detail"]["url_template"] == "{url}"


def test_no_metadata_no_url_field_plain_table():
    tool_output = {"items": [{"id": 1, "title": "a"}, {"id": 2, "title": "b"}]}
    msg = convert_tool_output_to_c2a("t", tool_output, "s")
    data = _block_data(msg)
    assert "row_actions" not in data
    assert data["id_field"] == "id"
    assert data["row_values"] == [{"id": 1}, {"id": 2}]


def test_metadata_without_placeholders_no_crash():
    """Static url_template (no {x}) must not break conversion."""
    tool_output = {
        "items": [{"id": 1, "title": "a"}, {"id": 2, "title": "b"}],
        "metadata": {
            "action_templates": {
                "row_link": {"label": "打开", "url_template": "http://x/portal"}
            }
        },
    }
    msg = convert_tool_output_to_c2a("t", tool_output, "s")
    assert msg is not None
    ra = _block_data(msg)["row_actions"]["row_link"]
    assert ra["url_template"] == "http://x/portal"


def test_metadata_missing_row_fields_keeps_only_existing():
    """Placeholders whose row field is absent are not put into row_values."""
    rows = [{"id": "t1", "title": "a"}]  # no processInstanceId
    tool_output = {"data": rows, "metadata": _oa_metadata()}
    msg = convert_tool_output_to_c2a("t", tool_output, "s")
    data = _block_data(msg)
    # only 'id' exists in the rows
    assert data["row_values"][0] == {"id": "t1"}


def test_render_card_payload_tool_output_as_json_string():
    """c2a_render_card accepts a JSON-string tool_output (LLM quirk)."""
    wrapper = {
        "result": json.dumps({"data": _oa_rows()}, ensure_ascii=False),
        "is_error": False,
        "metadata": _oa_metadata(),
    }
    out = render_card_payload(
        tool_output=json.dumps(wrapper, ensure_ascii=False),
        tool_name="mcp__oa__fetch_pending_approvals",
        session_id="s",
    )
    assert out["status"] == "success", out
    # wire shape: content is the table_content itself — row_actions sits at
    # the content level, content["data"] only holds headers/rows
    content = out["c2a_message"]["blocks"][0]["content"]
    assert "row_link" in content["row_actions"]
    assert content["row_values"][0] == {"id": "task-0", "processInstanceId": "proc-0"}


def test_parse_mcp_return_wrapper_shape():
    """mcp_parser accepts the wrapper shape too (parity with converter)."""
    from c2a_tools.mcp_parser import MCPC2AParser

    wrapper = {
        "result": json.dumps({"data": _oa_rows()}, ensure_ascii=False),
        "is_error": False,
        "metadata": _oa_metadata(),
    }
    msg = MCPC2AParser.generate_c2a_message_from_mcp(wrapper, "m", "s")
    blocks = [b for b in msg.blocks if b.type == "data_table"]
    assert blocks
    data = blocks[0].content.data
    assert "row_link" in data["row_actions"]
    assert data["row_values"][0] == {"id": "task-0", "processInstanceId": "proc-0"}
