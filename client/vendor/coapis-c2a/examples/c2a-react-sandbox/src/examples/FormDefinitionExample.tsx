import React from 'react';
import { C2ARenderer } from '@coapis/c2a-renderer-react';
import type { C2AMessage } from '@coapis/c2a-core-types';

const formDefinitionMessage: C2AMessage = {
  protocol_version: "c2a-v1.0",
  message_id: "msg_form_001",
  context_ref: { session_id: "default_session" },
  metadata: { generated_by: "c2a-sandbox-example" },
  blocks: [
    {
      block_id: "block_form_001",
      type: "form_definition",
      content: {
        data: {
          fields: [
            { name: "applicant_name", label: "申请人姓名", type: "text", placeholder: "请输入姓名" },
            { name: "approval_amount", label: "审批金额", type: "text", placeholder: "请输入金额" }
          ]
        }
      }
    }
  ],
  actions: [
    {
      action_id: "btn_submit",
      label: "提交申请",
      icon: "✅",
      style: "primary",
      disabled: false,
      intent: "form_submit",
      payload: { api_endpoint: "/api/workflows/submit" },
      security: { requires_auth: true, required_permissions: ["workflow:submit"], confirmation_prompt: "确认提交申请吗？" }
    },
    {
      action_id: "btn_cancel",
      label: "取消",
      icon: "❌",
      style: "secondary",
      disabled: false,
      intent: "custom_extension",
      payload: {},
      security: { requires_auth: false, required_permissions: [], confirmation_prompt: undefined }
    }
  ],
  state: { status: "interactive" },
  extensions: {}
};

const FormDefinitionExample: React.FC = () => {
  return (
    <div style={{ border: '1px solid #ddd', borderRadius: '8px', padding: '16px', backgroundColor: '#fff' }}>
      <C2ARenderer message={formDefinitionMessage} />
    </div>
  );
};

export default FormDefinitionExample;
