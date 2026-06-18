import { useState, useEffect, useCallback, useRef } from "react";
import { Drawer, Form, Input, Button, Select, Tabs, Tag, Table, Progress, Empty, Tooltip } from "@agentscope-ai/design";
import { useAppMessage } from "../../../../hooks/useAppMessage";
import { useTranslation } from "react-i18next";
import { ThunderboltOutlined, StopOutlined, SearchOutlined, HistoryOutlined, DownloadOutlined } from "@ant-design/icons";
import type { FormInstance } from "antd";
import type { SkillSpec, CategorySpec } from "../../../../api/types";
import { MarkdownCopy } from "../../../../components/MarkdownCopy/MarkdownCopy";
import { api, skillApi } from "../../../../api";

/** Parse YAML frontmatter from a `---`-delimited content string. */
export function parseFrontmatter(
  content: string,
): Record<string, string> | null {
  try {
    const trimmed = content.trim();
    if (!trimmed.startsWith("---")) return null;
    const endIndex = trimmed.indexOf("---", 3);
    if (endIndex === -1) return null;
    const frontmatterBlock = trimmed.slice(3, endIndex).trim();
    if (!frontmatterBlock) return null;
    const result: Record<string, string> = {};
    for (const line of frontmatterBlock.split("\n")) {
      const colonIndex = line.indexOf(":");
      if (colonIndex > 0) {
        const key = line.slice(0, colonIndex).trim();
        const value = line.slice(colonIndex + 1).trim();
        result[key] = value;
      }
    }
    return result;
  } catch {
    return null;
  }
}

const CHANNEL_OPTIONS = [
  { label: "all", value: "all" },
  { label: "console", value: "console" },
  { label: "discord", value: "discord" },
  { label: "telegram", value: "telegram" },
  { label: "dingtalk", value: "dingtalk" },
  { label: "feishu", value: "feishu" },
  { label: "imessage", value: "imessage" },
  { label: "qq", value: "qq" },
  { label: "mattermost", value: "mattermost" },
  { label: "wecom", value: "wecom" },
  { label: "mqtt", value: "mqtt" },
];

export const MAX_TAGS = 8;
export const MAX_TAG_LENGTH = 16;

export interface SkillDrawerFormValues {
  name: string;
  description?: string;
  content: string;
  enabled?: boolean;
  channels?: string[];
  tags?: string[];
  source?: string;
  category?: string;
  config?: Record<string, unknown>;
}

interface SkillDrawerProps {
  open: boolean;
  editingSkill: SkillSpec | null;
  form: FormInstance<SkillDrawerFormValues>;
  availableTags?: string[];
  categoryOptions?: CategorySpec[];
  onClose: () => void;
  onSubmit: (values: SkillSpec) => void;
  onContentChange?: (content: string) => void;
  onExport?: (skillNames: string[]) => Promise<void>;
}

function TriggerAnalysisTab({ skillName }: { skillName: string }) {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<{
    triggers: Array<{ keyword: string; type: string; priority: number }>;
    trigger_stats: Record<string, { count: number; precision: number }>;
  } | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await skillApi.getSkillTriggers(skillName) as any;
        if (!cancelled) setData(res);
      } catch { /* silent */ }
      finally { if (!cancelled) setLoading(false); }
    })();
    return () => { cancelled = true; };
  }, [skillName]);

  if (loading) return <div style={{ padding: 16, textAlign: "center" }}>加载中...</div>;
  if (!data) return <Empty description="暂无触发数据" />;

  return (
    <div style={{ fontSize: 13 }}>
      <div style={{ marginBottom: 12 }}>
        <strong>触发词 ({data.triggers.length})</strong>
        <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 4 }}>
          {data.triggers.map((t) => (
            <Tag key={t.keyword} color={t.type === "pattern" ? "blue" : "green"}>
              {t.keyword}
            </Tag>
          ))}
          {data.triggers.length === 0 && <span style={{ color: "#999" }}>无触发词</span>}
        </div>
      </div>
      <div>
        <strong>触发统计</strong>
        {Object.keys(data.trigger_stats).length === 0 ? (
          <Empty description="暂无触发记录" />
        ) : (
          <Table
            size="small"
            pagination={false}
            dataSource={Object.entries(data.trigger_stats).map(([kw, s]) => ({ key: kw, ...s }))}
            columns={[
              { title: "关键词", dataIndex: "key", key: "kw" },
              { title: "触发次数", dataIndex: "count", key: "count", sorter: (a: { count: number }, b: { count: number }) => a.count - b.count },
              {
                title: "准确率", dataIndex: "precision", key: "precision",
                render: (v: number) => (
                  <Progress
                    percent={Math.round(v * 100)} size="small"
                    strokeColor={v >= 0.7 ? "#52c41a" : v >= 0.4 ? "#faad14" : "#ff4d4f"}
                    style={{ width: 80 }}
                  />
                ),
              },
            ]}
          />
        )}
      </div>
    </div>
  );
}

function VersionHistoryTab({ skillName }: { skillName: string }) {
  const [loading, setLoading] = useState(true);
  const [versions, setVersions] = useState<Array<{
    version: string; changelog: string; created_at: string; active: boolean; content_size: number;
  }>>([]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await skillApi.getSkillVersions(skillName) as any;
        if (!cancelled) setVersions(res.versions || []);
      } catch { /* silent */ }
      finally { if (!cancelled) setLoading(false); }
    })();
    return () => { cancelled = true; };
  }, [skillName]);

  if (loading) return <div style={{ padding: 16, textAlign: "center" }}>加载中...</div>;
  if (versions.length === 0) return <Empty description="暂无版本历史" />;

  return (
    <div style={{ fontSize: 13 }}>
      {versions.map((v) => (
        <div key={v.version} style={{ padding: "8px 0", borderBottom: "1px solid #f0f0f0" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span>
              <Tag color={v.active ? "green" : "default"}>
                v{v.version} {v.active && "(当前)"}
              </Tag>
            </span>
            <span style={{ color: "#999", fontSize: 12 }}>
              {v.created_at ? new Date(v.created_at).toLocaleDateString() : ""}
              {v.content_size > 0 && ` · ${Math.round(v.content_size / 1024)}KB`}
            </span>
          </div>
          {v.changelog && <div style={{ marginTop: 4, color: "#666" }}>{v.changelog}</div>}
        </div>
      ))}
    </div>
  );
}

export function SkillDrawer({
  open,
  editingSkill,
  form,
  availableTags = [],
  categoryOptions = [],
  onClose,
  onSubmit,
  onContentChange,
  onExport,
}: SkillDrawerProps) {
  const { t, i18n } = useTranslation();
  const [showMarkdown, setShowMarkdown] = useState(true);
  const [contentValue, setContentValue] = useState("");
  const [optimizing, setOptimizing] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const [configText, setConfigText] = useState("{}");
  const [configError, setConfigError] = useState("");
  const { message } = useAppMessage();

  const validateFrontmatter = useCallback(
    (_: unknown, value: string) => {
      const content = contentValue || value;
      if (!content || !content.trim()) {
        return Promise.reject(new Error(t("skills.pleaseInputContent")));
      }
      const fm = parseFrontmatter(content);
      if (!fm) {
        return Promise.reject(new Error(t("skills.frontmatterRequired")));
      }
      if (!fm.name) {
        return Promise.reject(new Error(t("skills.frontmatterNameRequired")));
      }
      if (!fm.description) {
        return Promise.reject(
          new Error(t("skills.frontmatterDescriptionRequired")),
        );
      }
      return Promise.resolve();
    },
    [contentValue, t],
  );

  useEffect(() => {
    if (editingSkill) {
      const channels = editingSkill.channels || ["all"];
      const fallbackConfigText = JSON.stringify(
        editingSkill.config || {},
        null,
        2,
      );
      setContentValue(editingSkill.content);
      setConfigText(fallbackConfigText);
      form.setFieldsValue({
        name: editingSkill.name,
        content: editingSkill.content,
        channels,
        tags: editingSkill.tags || [],
        category: editingSkill.category || undefined,
        source: editingSkill.source,
      });
      setConfigError("");
      let active = true;
      api
        .getSkillConfig(editingSkill.name)
        .then((res) => {
          if (!active) return;
          setConfigText(JSON.stringify(res.config || {}, null, 2));
        })
        .catch(() => {
          if (!active) return;
          setConfigText(fallbackConfigText);
        });
      return () => {
        active = false;
      };
    } else {
      setContentValue("");
      setConfigText("{}");
      setConfigError("");
      form.resetFields();
    }
  }, [editingSkill, form, t]);

  const handleSubmit = async (values: SkillDrawerFormValues) => {
    let parsedConfig: Record<string, unknown> | undefined;
    const trimmed = configText.trim();
    if (!trimmed) {
      parsedConfig = {};
    } else {
      try {
        parsedConfig = JSON.parse(trimmed);
        setConfigError("");
      } catch {
        setConfigError(t("skills.configInvalidJson"));
        return;
      }
    }
    onSubmit({
      ...editingSkill,
      ...values,
      content: contentValue || values.content,
      source: editingSkill?.source || "",
      config: parsedConfig,
    });
  };

  const handleContentChange = (content: string) => {
    setContentValue(content);
    form.setFieldsValue({ content });
    form.validateFields(["content"]).catch(() => {});
    if (onContentChange) {
      onContentChange(content);
    }
  };

  const handleOptimize = async () => {
    if (!contentValue.trim()) {
      message.warning(t("skills.noContentToOptimize"));
      return;
    }

    setOptimizing(true);
    abortControllerRef.current = new AbortController();
    const originalContent = contentValue;
    setContentValue(""); // Clear content for streaming output

    try {
      await api.streamOptimizeSkill(
        originalContent,
        (textChunk) => {
          setContentValue((prev) => {
            const newContent = prev + textChunk;
            form.setFieldsValue({ content: newContent });
            return newContent;
          });
        },
        abortControllerRef.current.signal,
        i18n.language, // Pass current language to API
      );
      message.success(t("skills.optimizeSuccess"));
    } catch (error: unknown) {
      const aborted =
        error instanceof DOMException && error.name === "AbortError";
      if (!aborted) {
        message.error(
          error instanceof Error ? error.message : t("skills.optimizeFailed"),
        );
      }
    } finally {
      setOptimizing(false);
      abortControllerRef.current = null;
    }
  };

  const handleStopOptimize = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      setOptimizing(false);
      abortControllerRef.current = null;
    }
  };

  const drawerFooter = !editingSkill ? (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        width: "100%",
      }}
    >
      <div>
        {!optimizing ? (
          <Button
            type="default"
            icon={<ThunderboltOutlined />}
            onClick={handleOptimize}
            disabled={!contentValue.trim()}
          >
            {t("skills.optimizeWithAI")}
          </Button>
        ) : (
          <Button
            type="default"
            danger
            icon={<StopOutlined />}
            onClick={handleStopOptimize}
          >
            {t("skills.stopOptimize")}
          </Button>
        )}
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button type="primary" onClick={() => form.submit()}>
          {t("skills.create")}
        </Button>
      </div>
    </div>
  ) : (
    <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
      {onExport && editingSkill ? (
        <Tooltip title={t("skills.exportZipHint")}>
          <Button
            icon={<DownloadOutlined />}
            onClick={() => editingSkill && onExport([editingSkill.name])}
          >
            {t("skills.exportZip")}
          </Button>
        </Tooltip>
      ) : null}
      <Button onClick={onClose}>{t("common.cancel")}</Button>
      <Button type="primary" onClick={() => form.submit()}>
        {t("common.save")}
      </Button>
    </div>
  );

  return (
    <Drawer
      width={520}
      placement="right"
      title={editingSkill ? t("skills.viewSkill") : t("skills.createSkill")}
      open={open}
      onClose={onClose}
      destroyOnClose
      footer={drawerFooter}
    >
      <Form form={form} layout="vertical" onFinish={handleSubmit}>
        {!editingSkill ? (
          <Form.Item
            name="name"
            label="Name"
            rules={[{ required: true, message: t("skills.pleaseInputName") }]}
          >
            <Input placeholder={t("skills.skillNamePlaceholder")} />
          </Form.Item>
        ) : (
          <Form.Item name="name" label="Name">
            <Input />
          </Form.Item>
        )}

        <Form.Item
          name="content"
          label="Content"
          rules={[{ required: true, validator: validateFrontmatter }]}
        >
          <MarkdownCopy
            content={contentValue}
            showMarkdown={showMarkdown}
            onShowMarkdownChange={setShowMarkdown}
            editable={true}
            onContentChange={handleContentChange}
            textareaProps={{
              ...(!editingSkill && {
                placeholder: t("skills.contentPlaceholder"),
              }),
              rows: 12,
            }}
          />
        </Form.Item>

        <Form.Item name="channels" label={t("skills.channels")}>
          <Select mode="multiple" options={CHANNEL_OPTIONS} />
        </Form.Item>

        <Form.Item
          name="tags"
          label={t("skillPool.tags")}
          rules={[
            {
              validator: (_, value: string[] | undefined) => {
                const bad = (value || []).find(
                  (v) => v.length > MAX_TAG_LENGTH,
                );
                if (bad)
                  return Promise.reject(
                    t("skillPool.tagTooLong", { max: MAX_TAG_LENGTH }),
                  );
                return Promise.resolve();
              },
            },
          ]}
        >
          <Select
            mode="tags"
            options={availableTags.map((tag) => ({
              label: tag,
              value: tag,
            }))}
            placeholder={t("skillPool.tagsPlaceholder")}
            maxCount={MAX_TAGS}
          />
        </Form.Item>

        {categoryOptions.length > 0 && (
          <Form.Item name="category" label="分类">
            <Select
              placeholder="选择分类"
              allowClear
              options={categoryOptions.map((c) => ({
                label: `${c.emoji || ""} ${c.label}`,
                value: c.key,
              }))}
            />
          </Form.Item>
        )}

        <Form.Item
          label={t("skills.config")}
          validateStatus={configError ? "error" : undefined}
          help={configError || undefined}
        >
          <Input.TextArea
            rows={4}
            value={configText}
            onChange={(e) => {
              setConfigText(e.target.value);
              setConfigError("");
            }}
            placeholder={t("skills.configPlaceholder")}
          />
        </Form.Item>

        {editingSkill && (
          <>
            <Form.Item name="source" label={t("skills.type")}>
              <Input disabled />
            </Form.Item>

            <Tabs
              size="small"
              items={[
                {
                  key: "triggers",
                  label: <><SearchOutlined /> 触发分析</>,
                  children: <TriggerAnalysisTab skillName={editingSkill.name} />,
                },
                {
                  key: "versions",
                  label: <><HistoryOutlined /> 版本历史</>,
                  children: <VersionHistoryTab skillName={editingSkill.name} />,
                },
              ]}
            />
          </>
        )}
      </Form>
    </Drawer>
  );
}
