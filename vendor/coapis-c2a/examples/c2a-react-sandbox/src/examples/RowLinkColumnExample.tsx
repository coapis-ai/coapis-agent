import React from 'react';
import { C2ARenderer } from '@coapis/c2a-renderer-react';
import type { C2AMessage } from '@coapis/c2a-core-types';

// 与后端 mcp_parser.to_dict() 完全一致的结构：
//   content.data.headers / content.data.rows / content.row_values / content.row_actions
// link_column 指向 "标题" 列 → 只有该列的单元格渲染为蓝色 <a> 链接（新标签页打开）
const linkColumnMessage: C2AMessage = {
  protocol_version: "c2a-v1.0",
  message_id: "msg_rowlink_col_001",
  context_ref: { session_id: "default_session" },
  metadata: { generated_by: "c2a-sandbox-rowlink" },
  blocks: [
    {
      block_id: "block_approvals_001",
      type: "data_table",
      content: {
        data: {
          headers: ["标题", "金额", "提交人", "状态"],
          rows: [
            ["差旅报销", "1500", "张三", "待审批"],
            ["采购申请", "3200", "李四", "已审批"],
            ["请假申请", "—", "王五", "待审批"]
          ]
        },
        id_field: "approval_id",
        row_values: [
          { approval_id: "A001" },
          { approval_id: "A002" },
          { approval_id: "A003" }
        ],
        row_actions: {
          row_link: {
            action_id: "btn_row_link",
            label: "查看详情",
            style: "link",
            business_intent: "view_detail",
            url_template: "/oa/approvals/{approval_id}",
            link_column: "标题"
          }
        }
      } as any
    }
  ],
  actions: [],
  suggestions: [],
  state: { status: "rendered" },
  extensions: {}
};

// 对照组：不声明 link_column → 向后兼容，整行可点
const noLinkColumnMessage: C2AMessage = {
  protocol_version: "c2a-v1.0",
  message_id: "msg_rowlink_row_001",
  context_ref: { session_id: "default_session" },
  metadata: { generated_by: "c2a-sandbox-rowlink-legacy" },
  blocks: [
    {
      block_id: "block_approvals_002",
      type: "data_table",
      content: {
        data: {
          headers: ["标题", "金额", "提交人"],
          rows: [
            ["差旅报销", "1500", "张三"],
            ["采购申请", "3200", "李四"]
          ]
        },
        id_field: "approval_id",
        row_values: [
          { approval_id: "A001" },
          { approval_id: "A002" }
        ],
        row_actions: {
          row_link: {
            action_id: "btn_row_link",
            label: "查看详情",
            style: "link",
            business_intent: "view_detail",
            url_template: "/oa/approvals/{approval_id}"
          }
        }
      } as any
    }
  ],
  actions: [],
  suggestions: [],
  state: { status: "rendered" },
  extensions: {}
};

const RowLinkColumnExample: React.FC = () => {
  return (
    <div>
      <h2 style={{ marginTop: 40 }}>行链接 · 指定列（link_column = 标题）</h2>
      <p style={{ color: '#666', fontSize: 13 }}>
        仅"标题"列单元格为蓝色链接（新标签页打开 /oa/approvals/{'{A001}'})，其余列不可点；整行不再可点。
      </p>
      <div style={{ border: '1px solid #ddd', borderRadius: '8px', padding: '16px', backgroundColor: '#fff' }}>
        <C2ARenderer message={linkColumnMessage} />
      </div>

      <h2 style={{ marginTop: 40 }}>行链接 · 整行（不声明 link_column，向后兼容）</h2>
      <p style={{ color: '#666', fontSize: 13 }}>
        未声明 link_column 时回退为整行可点（旧行为）。
      </p>
      <div style={{ border: '1px solid #ddd', borderRadius: '8px', padding: '16px', backgroundColor: '#fff', marginTop: 8 }}>
        <C2ARenderer message={noLinkColumnMessage} />
      </div>
    </div>
  );
};

export default RowLinkColumnExample;
