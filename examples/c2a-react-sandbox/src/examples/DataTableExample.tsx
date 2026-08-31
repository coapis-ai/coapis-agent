import React from 'react';
import { C2ARenderer } from '@coapis/c2a-renderer-react';
import type { C2AMessage } from '@coapis/c2a-core-types';

const dataTableMessage: C2AMessage = {
  protocol_version: "c2a-v1.0",
  message_id: "msg_datatable_001",
  context_ref: { session_id: "default_session" },
  metadata: { generated_by: "c2a-sandbox-example" },
  blocks: [
    {
      block_id: "block_table_001",
      type: "data_table",
      content: {
        data: {
          headers: ["姓名", "部门", "职位", "状态"],
          rows: [
            ["张三", "技术部", "前端工程师", "在职"],
            ["李四", "产品部", "产品经理", "在职"],
            ["王五", "运营部", "运营专员", "休假中"]
          ]
        }
      }
    }
  ],
  actions: [
    {
      action_id: "btn_refresh",
      label: "刷新数据",
      icon: "🔄",
      style: "secondary",
      disabled: false,
      intent: "api_call",
      payload: { api_endpoint: "/api/data/refresh" },
      security: { requires_auth: false, required_permissions: [], confirmation_prompt: undefined }
    }
  ],
  state: { status: "rendered" },
  extensions: {}
};

const DataTableExample: React.FC = () => {
  return (
    <div style={{ border: '1px solid #ddd', borderRadius: '8px', padding: '16px', backgroundColor: '#fff' }}>
      <C2ARenderer message={dataTableMessage} />
    </div>
  );
};

export default DataTableExample;
