import { useEffect } from "react";
import { Modal, Form, Input, Select, Tag } from "@agentscope-ai/design";

export interface CommandRule {
  id: string;
  desc: string;
  level: string;
  action: string;
  patterns?: string[];
  exclude_patterns?: string[];
  safe_paths?: string[];
  scope?: string;
}

interface CommandRuleModalProps {
  open: boolean;
  ruleType: "exception" | "demotion";
  editingRule: CommandRule | null;
  cmdName: string;
  cmdDefaultAction: string;
  onOk: (rule: CommandRule) => void;
  onCancel: () => void;
}

const LEVEL_OPTIONS = ["L0", "L1", "L2", "L3", "L4"];

function generateId(cmdName: string, type: string): string {
  const hex = Math.random().toString(16).slice(2, 8);
  return `${cmdName}_${type}_${hex}`;
}

export function CommandRuleModal({
  open,
  ruleType,
  editingRule,
  cmdName,
  cmdDefaultAction: _cmdDefaultAction,
  onOk,
  onCancel,
}: CommandRuleModalProps) {
  const [form] = Form.useForm();

  const isException = ruleType === "exception";

  // Determine valid action options based on type
  const ACTION_OPTIONS = isException
    ? [
        { label: "block (拦截)", value: "block" },
        { label: "confirm (确认)", value: "confirm" },
        { label: "audit (审计)", value: "audit" },
      ]
    : [
        { label: "allow (放行)", value: "allow" },
        { label: "audit (审计)", value: "audit" },
        { label: "confirm (确认)", value: "confirm" },
      ];

  useEffect(() => {
    if (open) {
      if (editingRule) {
        form.setFieldsValue({
          ...editingRule,
          patterns: editingRule.patterns?.join("\n") || "",
          exclude_patterns: editingRule.exclude_patterns?.join("\n") || "",
          safe_paths: editingRule.safe_paths?.join("\n") || "",
        });
      } else {
        const newId = generateId(cmdName, isException ? "exc" : "dem");
        form.resetFields();
        form.setFieldsValue({
          id: newId,
          desc: "",
          level: isException ? "L3" : "L0",
          action: isException ? "block" : "allow",
          patterns: "",
          exclude_patterns: "",
          safe_paths: "",
          scope: null,
        });
      }
    }
  }, [open, editingRule, form, cmdName, isException]);

  const handleOk = async () => {
    try {
      const values = await form.validateFields();
      const rule: CommandRule = {
        id: values.id,
        desc: values.desc || "",
        level: values.level,
        action: values.action,
        patterns: values.patterns
          ? values.patterns.split("\n").map((s: string) => s.trim()).filter(Boolean)
          : [],
        exclude_patterns: values.exclude_patterns
          ? values.exclude_patterns.split("\n").map((s: string) => s.trim()).filter(Boolean)
          : [],
        safe_paths: values.safe_paths
          ? values.safe_paths.split("\n").map((s: string) => s.trim()).filter(Boolean)
          : [],
        scope: values.scope || null,
      };
      onOk(rule);
    } catch {
      // validation failed
    }
  };

  return (
    <Modal
      title={`${editingRule ? "编辑" : "新增"}${isException ? "例外规则" : "降级规则"} — ${cmdName}`}
      open={open}
      onOk={handleOk}
      onCancel={onCancel}
      width={600}
      destroyOnClose
    >
      <Form form={form} layout="vertical" size="small">
        <Form.Item name="id" label="规则 ID" rules={[{ required: true }]}>
          <Input disabled={!!editingRule} style={{ fontFamily: "monospace" }} />
        </Form.Item>
        <Form.Item name="desc" label="描述">
          <Input placeholder="描述这条规则的作用" />
        </Form.Item>
        <div style={{ display: "flex", gap: 16 }}>
          <Form.Item name="level" label="风险级别" style={{ flex: 1 }} rules={[{ required: true }]}>
            <Select options={LEVEL_OPTIONS.map(l => ({ label: l, value: l }))} />
          </Form.Item>
          <Form.Item name="action" label="动作" style={{ flex: 1 }} rules={[{ required: true }]}>
            <Select options={ACTION_OPTIONS} />
          </Form.Item>
          <Form.Item name="scope" label="作用域" style={{ flex: 1 }}>
            <Select
              allowClear
              placeholder="可选"
              options={[
                { label: "workspace（仅工作空间）", value: "workspace" },
              ]}
            />
          </Form.Item>
        </div>
        <Form.Item name="patterns" label={<span>匹配模式 <Tag>OR 逻辑</Tag></span>} extra="每行一个正则表达式，命令命中任一即匹配">
          <Input.TextArea rows={3} placeholder={"\\s/(etc|usr|bin)\\b\n\\s--no-preserve-root"} style={{ fontFamily: "monospace", fontSize: 12 }} />
        </Form.Item>
        <Form.Item name="exclude_patterns" label="排除模式" extra="每行一个正则，命中任一则不匹配">
          <Input.TextArea rows={2} placeholder={"-X\\s+(POST|PUT|DELETE)"} style={{ fontFamily: "monospace", fontSize: 12 }} />
        </Form.Item>
        <Form.Item name="safe_paths" label="安全路径" extra="每行一个路径前缀，所有绝对路径必须在这些前缀下">
          <Input.TextArea rows={2} placeholder={"/tmp/\n/var/tmp/"} style={{ fontFamily: "monospace", fontSize: 12 }} />
        </Form.Item>
      </Form>
    </Modal>
  );
}
