import { useState, useEffect, useCallback } from "react";
import {
  Table,
  Tag,
  Button,
  Modal,
  Form,
  Input,
  Select,
  Popconfirm,
} from "@agentscope-ai/design";
import { Space, Spin, message } from "antd";
import { Plus, Pencil, Trash2, RefreshCw, FlaskConical } from "lucide-react";
import { useTranslation } from "react-i18next";
import { securityApi } from "../../../../api/modules/security";
import type {
  InputGuardRule,
  InputGuardTestResult,
} from "../../../../api/modules/security";
import { useTheme } from "../../../../contexts/ThemeContext";

const SEVERITY_COLORS: Record<string, string> = {
  CRITICAL: "red",
  HIGH: "orange",
  MEDIUM: "gold",
  LOW: "blue",
  SAFE: "green",
};

const CATEGORIES = [
  { value: "command_injection", label: "command_injection" },
  { value: "prompt_injection", label: "prompt_injection" },
  { value: "data_exfiltration", label: "data_exfiltration" },
  { value: "credential_exposure", label: "credential_exposure" },
];

const SEVERITIES = [
  { value: "CRITICAL", label: "CRITICAL" },
  { value: "HIGH", label: "HIGH" },
  { value: "MEDIUM", label: "MEDIUM" },
  { value: "LOW", label: "LOW" },
];

export default function InputGuardTab() {
  const { t } = useTranslation();
  const { isDark } = useTheme();

  const [rules, setRules] = useState<InputGuardRule[]>([]);
  const [loading, setLoading] = useState(false);
  const [editModal, setEditModal] = useState(false);
  const [editingRule, setEditingRule] = useState<InputGuardRule | null>(null);
  const [form] = Form.useForm();
  const [testModal, setTestModal] = useState(false);
  const [testText, setTestText] = useState("");
  const [testResult, setTestResult] = useState<InputGuardTestResult | null>(null);
  const [testLoading, setTestLoading] = useState(false);
  const [reloading, setReloading] = useState(false);

  const fetchRules = useCallback(async () => {
    setLoading(true);
    try {
      const data = await securityApi.getInputGuardRules();
      setRules(data);
    } catch (e: any) {
      message.error(e.message || "Failed to load rules");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchRules();
  }, [fetchRules]);

  // ── Add / Edit ──

  const openAdd = () => {
    setEditingRule(null);
    form.resetFields();
    form.setFieldsValue({ patterns: [""] });
    setEditModal(true);
  };

  const openEdit = (rule: InputGuardRule) => {
    setEditingRule(rule);
    form.setFieldsValue(rule);
    setEditModal(true);
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      // Filter empty patterns
      values.patterns = (values.patterns || []).filter(
        (p: string) => p && p.trim(),
      );
      if (values.patterns.length === 0) {
        message.warning("At least one pattern is required");
        return;
      }
      if (editingRule) {
        await securityApi.updateInputGuardRule(editingRule.id, values);
        message.success("Rule updated");
      } else {
        await securityApi.addInputGuardRule(values);
        message.success("Rule added");
      }
      setEditModal(false);
      fetchRules();
    } catch (e: any) {
      if (e.errorFields) return; // form validation error
      message.error(e.message || "Save failed");
    }
  };

  const handleDelete = async (ruleId: string) => {
    try {
      await securityApi.deleteInputGuardRule(ruleId);
      message.success("Rule deleted");
      fetchRules();
    } catch (e: any) {
      message.error(e.message || "Delete failed");
    }
  };

  // ── Reload ──

  const handleReload = async () => {
    setReloading(true);
    try {
      const res = await securityApi.reloadInputGuardRules();
      message.success(`Reloaded ${res.rule_count} rules`);
      fetchRules();
    } catch (e: any) {
      message.error(e.message || "Reload failed");
    } finally {
      setReloading(false);
    }
  };

  // ── Test ──

  const handleTest = async () => {
    if (!testText.trim()) {
      message.warning("Please enter test text");
      return;
    }
    setTestLoading(true);
    setTestResult(null);
    try {
      const res = await securityApi.testInputGuardText(testText);
      setTestResult(res);
    } catch (e: any) {
      message.error(e.message || "Test failed");
    } finally {
      setTestLoading(false);
    }
  };

  // ── Table columns ──

  const columns = [
    {
      title: "ID",
      dataIndex: "id",
      key: "id",
      width: 180,
      render: (id: string) => (
        <span style={{ fontFamily: "monospace", fontSize: 13 }}>{id}</span>
      ),
    },
    {
      title: t("security.inputGuard.category"),
      dataIndex: "category",
      key: "category",
      width: 180,
      render: (cat: string) => <Tag color="blue">{cat}</Tag>,
    },
    {
      title: t("security.inputGuard.severity"),
      dataIndex: "severity",
      key: "severity",
      width: 110,
      render: (sev: string) => (
        <Tag color={SEVERITY_COLORS[sev] || "default"}>{sev}</Tag>
      ),
    },
    {
      title: t("security.inputGuard.patterns"),
      dataIndex: "patterns",
      key: "patterns",
      ellipsis: true,
      render: (patterns: string[]) => (
        <span style={{ fontSize: 12, fontFamily: "monospace", opacity: 0.8 }}>
          {patterns.length} pattern(s)
        </span>
      ),
    },
    {
      title: t("security.inputGuard.description"),
      dataIndex: "description",
      key: "description",
      ellipsis: true,
    },
    {
      title: t("common.actions"),
      key: "actions",
      width: 120,
      render: (_: unknown, record: InputGuardRule) => (
        <Space size="small">
          <Button
            type="text"
            size="small"
            icon={<Pencil size={14} />}
            onClick={() => openEdit(record)}
          />
          <Popconfirm
            title={t("security.inputGuard.confirmDelete")}
            onConfirm={() => handleDelete(record.id)}
          >
            <Button
              type="text"
              size="small"
              danger
              icon={<Trash2 size={14} />}
            />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      {/* Toolbar */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          marginBottom: 16,
        }}
      >
        <Space>
          <Button type="primary" icon={<Plus size={14} />} onClick={openAdd}>
            {t("security.inputGuard.addRule")}
          </Button>
          <Button
            icon={<FlaskConical size={14} />}
            onClick={() => {
              setTestText("");
              setTestResult(null);
              setTestModal(true);
            }}
          >
            {t("security.inputGuard.test")}
          </Button>
        </Space>
        <Button
          icon={<RefreshCw size={14} className={reloading ? "spin-icon" : ""} />}
          onClick={handleReload}
          loading={reloading}
        >
          {t("security.inputGuard.reload")}
        </Button>
      </div>

      {/* Rules table */}
      <Table
        dataSource={rules}
        columns={columns}
        rowKey="id"
        loading={loading}
        pagination={false}
        size="small"
        scroll={{ y: 460 }}
      />

      {/* Add / Edit modal */}
      <Modal
        title={
          editingRule
            ? t("security.inputGuard.editRule")
            : t("security.inputGuard.addRule")
        }
        open={editModal}
        onCancel={() => setEditModal(false)}
        onOk={handleSave}
        width={640}
        destroyOnClose
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="id"
            label="ID"
            rules={[{ required: true, message: "ID is required" }]}
          >
            <Input
              placeholder="e.g. CMD_INJECTION_CUSTOM"
              disabled={!!editingRule}
              style={{ fontFamily: "monospace" }}
            />
          </Form.Item>
          <div style={{ display: "flex", gap: 16 }}>
            <Form.Item
              name="category"
              label={t("security.inputGuard.category")}
              rules={[{ required: true }]}
              style={{ flex: 1 }}
            >
              <Select options={CATEGORIES} />
            </Form.Item>
            <Form.Item
              name="severity"
              label={t("security.inputGuard.severity")}
              rules={[{ required: true }]}
              style={{ flex: 1 }}
            >
              <Select options={SEVERITIES} />
            </Form.Item>
          </div>
          <Form.Item
            name="description"
            label={t("security.inputGuard.description")}
          >
            <Input placeholder="Brief description of what this rule catches" />
          </Form.Item>
          <Form.Item label={t("security.inputGuard.patterns")} required>
            <Form.List name="patterns">
              {(fields, { add, remove }) => (
                <>
                  {fields.map((field, index) => (
                    <div
                      key={field.key}
                      style={{
                        display: "flex",
                        gap: 8,
                        marginBottom: 8,
                        alignItems: "center",
                      }}
                    >
                      <Form.Item
                        {...field}
                        noStyle
                        rules={[
                          { required: index === 0, message: "Pattern required" },
                        ]}
                      >
                        <Input
                          placeholder="regex pattern"
                          style={{ fontFamily: "monospace" }}
                        />
                      </Form.Item>
                      {fields.length > 1 && (
                        <Button
                          type="text"
                          danger
                          size="small"
                          icon={<Trash2 size={14} />}
                          onClick={() => remove(field.name)}
                        />
                      )}
                    </div>
                  ))}
                  <Button
                    type="dashed"
                    size="small"
                    onClick={() => add()}
                    icon={<Plus size={14} />}
                    style={{ width: "100%" }}
                  >
                    {t("security.inputGuard.addPattern")}
                  </Button>
                </>
              )}
            </Form.List>
          </Form.Item>
        </Form>
      </Modal>

      {/* Test modal */}
      <Modal
        title={t("security.inputGuard.testTitle")}
        open={testModal}
        onCancel={() => setTestModal(false)}
        footer={null}
        width={640}
      >
        <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
          <Input.TextArea
            value={testText}
            onChange={(e) => setTestText(e.target.value)}
            placeholder={t("security.inputGuard.testPlaceholder")}
            rows={3}
            style={{ flex: 1 }}
          />
        </div>
        <Button
          type="primary"
          onClick={handleTest}
          loading={testLoading}
          style={{ marginBottom: 16 }}
        >
          {t("security.inputGuard.runTest")}
        </Button>

        {testLoading && <Spin />}

        {testResult && (
          <div
            style={{
              padding: 16,
              borderRadius: 8,
              background: testResult.is_safe
                ? isDark
                  ? "#1a3a1a"
                  : "#f0fff0"
                : isDark
                  ? "#3a1a1a"
                  : "#fff0f0",
              border: `1px solid ${testResult.is_safe ? "#52c41a" : "#ff4d4f"}`,
            }}
          >
            <div style={{ fontWeight: 600, marginBottom: 8 }}>
              {testResult.is_safe ? "✅ Safe" : "🚫 Blocked"}
              {!testResult.is_safe && (
                <Tag
                  color={SEVERITY_COLORS[testResult.max_severity] || "default"}
                  style={{ marginLeft: 8 }}
                >
                  {testResult.max_severity}
                </Tag>
              )}
            </div>
            {testResult.findings.length > 0 && (
              <Table
                dataSource={testResult.findings}
                rowKey="id"
                pagination={false}
                size="small"
                columns={[
                  {
                    title: "Rule",
                    dataIndex: "rule_id",
                    key: "rule_id",
                    width: 180,
                    render: (v: string) => (
                      <span style={{ fontFamily: "monospace" }}>{v}</span>
                    ),
                  },
                  {
                    title: "Severity",
                    dataIndex: "severity",
                    key: "severity",
                    width: 100,
                    render: (v: string) => (
                      <Tag color={SEVERITY_COLORS[v] || "default"}>{v}</Tag>
                    ),
                  },
                  {
                    title: "Matched",
                    dataIndex: "snippet",
                    key: "snippet",
                    ellipsis: true,
                    render: (v: string | null) =>
                      v ? (
                        <code
                          style={{
                            fontSize: 12,
                            background: isDark ? "#1f1f1f" : "#f5f5f5",
                            padding: "2px 6px",
                            borderRadius: 4,
                          }}
                        >
                          {v}
                        </code>
                      ) : (
                        "—"
                      ),
                  },
                ]}
              />
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}
