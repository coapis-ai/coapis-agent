import {
  Card,
  Button,
  Modal,
  Tooltip,
  Input,
  Empty,
  Tag,
  Form,
  Select,
  Space,
} from "@agentscope-ai/design";
import { Spin } from "antd";
import type { MCPClientInfo, MCPToolInfo, MCPAccessPolicy } from "../../../../api/types";
import { useTranslation } from "react-i18next";
import React, { useState, useCallback } from "react";
import { useTheme } from "../../../../contexts/ThemeContext";
import {
  EyeOutlined,
  EyeInvisibleOutlined,
  ToolOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import api from "../../../../api";
import styles from "../index.module.less";

interface MCPClientUpdate {
  name?: string;
  description?: string;
  command?: string;
  enabled?: boolean;
  transport?: "stdio" | "streamable_http" | "sse";
  url?: string;
  headers?: Record<string, string>;
  args?: string[];
  env?: Record<string, string>;
  cwd?: string;
  tools?: string[] | null;
}

interface MCPClientCardProps {
  client: MCPClientInfo;
  onToggle?: (client: MCPClientInfo, e: React.MouseEvent) => void;
  onDelete?: (client: MCPClientInfo, e: React.MouseEvent) => void;
  onUpdate?: (key: string, updates: MCPClientUpdate) => Promise<boolean>;
  readOnly?: boolean;
}

export const MCPClientCard = React.memo(function MCPClientCard({
  client,
  onToggle,
  onDelete,
  onUpdate,
  readOnly,
}: MCPClientCardProps) {
  const { t } = useTranslation();
  const { isDark } = useTheme();
  const [isHovered, setIsHovered] = useState(false);
  const [jsonModalOpen, setJsonModalOpen] = useState(false);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [toolsModalOpen, setToolsModalOpen] = useState(false);
  const [accessPolicyModalOpen, setAccessPolicyModalOpen] = useState(false);
  const [tools, setTools] = useState<MCPToolInfo[]>([]);
  const [toolsLoading, setToolsLoading] = useState(false);
  const [toolsError, setToolsError] = useState<string | null>(null);
  const [editedJson, setEditedJson] = useState("");
  const [isEditing, setIsEditing] = useState(false);

  // Access policy state
  const [accessPolicy, setAccessPolicy] = useState<MCPAccessPolicy | null>(null);
  const [loadingPolicy, setLoadingPolicy] = useState(false);

  // Determine if MCP client is remote or local based on command
  const isRemote =
    client.transport === "streamable_http" || client.transport === "sse";
  const clientType = isRemote ? "Remote" : "Local";

  const handleToggleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    onToggle?.(client, e);
  };

  const handleDeleteClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    setDeleteModalOpen(true);
  };

  const confirmDelete = () => {
    setDeleteModalOpen(false);
    onDelete?.(client, null as unknown as React.MouseEvent);
  };

  const handleCardClick = () => {
    const jsonStr = JSON.stringify(client, null, 2);
    setEditedJson(jsonStr);
    setIsEditing(false);
    setJsonModalOpen(true);
  };

  const handleSaveJson = async () => {
    try {
      const parsed = JSON.parse(editedJson);
      const { key: _key, ...updates } = parsed;

      // Send all updates directly to backend, let backend handle env masking check
      const success = await onUpdate?.(client.key, updates);
      if (success) {
        setJsonModalOpen(false);
        setIsEditing(false);
      }
    } catch {
      alert("Invalid JSON format");
    }
  };

  const handleShowTools = useCallback(
    async (e: React.MouseEvent) => {
      e.stopPropagation();
      setToolsModalOpen(true);
      setToolsLoading(true);
      setToolsError(null);
      setTools([]);
      try {
        const data = await api.listMCPTools(client.key);
        setTools(data);
      } catch (err: any) {
        const msg = err?.message || "";
        if (msg.includes("connecting") || msg.includes("not ready")) {
          setToolsError(t("mcp.toolsConnecting"));
        } else {
          setToolsError(msg || t("mcp.toolsLoadError"));
        }
      } finally {
        setToolsLoading(false);
      }
    },
    [client.key, t],
  );

  const handleShowAccessPolicy = useCallback(
    async (e: React.MouseEvent) => {
      e.stopPropagation();
      setAccessPolicyModalOpen(true);
      setLoadingPolicy(true);
      try {
        const data = await api.getMCPAccessPolicy(client.key);
        setAccessPolicy(data);
      } catch (err: any) {
        console.error("Failed to load access policy:", err);
      } finally {
        setLoadingPolicy(false);
      }
    },
    [client.key],
  );

  const handleSaveAccessPolicy = async (policy: MCPAccessPolicy) => {
    try {
      await api.updateMCPAccessPolicy(client.key, policy);
      setAccessPolicy(policy);
      setAccessPolicyModalOpen(false);
    } catch (err: any) {
      console.error("Failed to save access policy:", err);
      alert(t("mcp.accessPolicySaveError") || "保存访问策略失败");
    }
  };

  const clientJson = JSON.stringify(client, null, 2);

  return (
    <>
      <Card
        hoverable
        onClick={handleCardClick}
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
        className={`${styles.mcpCard} ${
          client.enabled ? styles.enabledCard : ""
        } ${isHovered ? styles.hover : styles.normal}`}
      >
        <div className={styles.cardHeader}>
          <Tooltip title={client.name}>
            <h3 className={styles.mcpTitle}>
              <span>{client.name}</span>
              <span
                className={`${styles.typeBadge} ${
                  isRemote ? styles.remote : styles.local
                }`}
              >
                {clientType}
              </span>
            </h3>
          </Tooltip>
          <div className={styles.statusContainer}>
            <span className={styles.statusDot} />
            <span className={styles.statusText}>
              {client.enabled ? t("common.enabled") : t("common.disabled")}
            </span>
          </div>
        </div>

        <p className={styles.mcpDescription}>{client.description || "-"}</p>

        <div className={styles.cardFooter}>
          <Button
            className={styles.toolsButton}
            onClick={handleShowTools}
            icon={<ToolOutlined />}
            disabled={!client.enabled || toolsLoading}
            loading={toolsLoading}
          >
            {t("mcp.tools")}
          </Button>
          {!readOnly && (
            <Button
              className={styles.policyButton}
              onClick={handleShowAccessPolicy}
              icon={<SettingOutlined />}
            >
              {t("mcp.accessPolicy", "访问策略")}
            </Button>
          )}
          {!readOnly && (
            <>
              <Button
                className={styles.toggleButton}
                onClick={(e) => {
                  e.stopPropagation();
                  handleToggleClick(e);
                }}
                icon={client.enabled ? <EyeInvisibleOutlined /> : <EyeOutlined />}
              >
                {client.enabled ? t("common.disable") : t("common.enable")}
              </Button>
              <Button
                className={styles.deleteButton}
                danger
                onClick={(e) => {
                  e.stopPropagation();
                  handleDeleteClick(e);
                }}
              >
                {t("common.delete")}
              </Button>
            </>
          )}
        </div>
      </Card>

      <Modal
        title={t("common.confirm")}
        open={deleteModalOpen}
        onOk={confirmDelete}
        onCancel={() => setDeleteModalOpen(false)}
        okText={t("common.confirm")}
        cancelText={t("common.cancel")}
        okButtonProps={{ danger: true }}
      >
        <p>{t("mcp.deleteConfirm")}</p>
      </Modal>

      <Modal
        title={`${client.name} - ${t("mcp.tools")}`}
        open={toolsModalOpen}
        onCancel={() => setToolsModalOpen(false)}
        footer={
          <div style={{ textAlign: "right" }}>
            <Button onClick={() => setToolsModalOpen(false)}>
              {t("common.close")}
            </Button>
          </div>
        }
        width={700}
      >
        {toolsLoading ? (
          <div className={styles.toolsLoading}>
            <Spin />
          </div>
        ) : toolsError ? (
          <div className={styles.toolsError}>{toolsError}</div>
        ) : tools.length === 0 ? (
          <Empty description={t("mcp.noTools")} />
        ) : (
          <div className={styles.toolsList}>
            {tools.map((tool) => (
              <div key={tool.name} className={styles.toolItem}>
                <div className={styles.toolHeader}>
                  <Tag color="blue">{tool.name}</Tag>
                </div>
                {tool.description && (
                  <p className={styles.toolDescription}>{tool.description}</p>
                )}
                {tool.input_schema &&
                  Object.keys(tool.input_schema).length > 0 && (
                    <details className={styles.toolSchema}>
                      <summary>{t("mcp.toolSchema")}</summary>
                      <pre className={styles.toolSchemaContent}>
                        {JSON.stringify(tool.input_schema, null, 2)}
                      </pre>
                    </details>
                  )}
              </div>
            ))}
          </div>
        )}
      </Modal>

      <Modal
        title={`${client.name} - Configuration`}
        open={jsonModalOpen}
        onCancel={() => setJsonModalOpen(false)}
        footer={
          <div style={{ textAlign: "right" }}>
            <Button
              onClick={() => setJsonModalOpen(false)}
              style={{ marginRight: 8 }}
            >
              {t("common.cancel")}
            </Button>
            {!readOnly && isEditing ? (
              <Button type="primary" onClick={handleSaveJson}>
                {t("common.save")}
              </Button>
            ) : !readOnly ? (
              <Button type="primary" onClick={() => setIsEditing(true)}>
                {t("common.edit")}
              </Button>
            ) : null}
          </div>
        }
        width={700}
      >
        <div className={styles.maskedFieldHint}>{t("mcp.maskedFieldHint")}</div>
        {isEditing ? (
          <Input.TextArea
            value={editedJson}
            onChange={(e) => setEditedJson(e.target.value)}
            autoSize={{ minRows: 15, maxRows: 25 }}
            style={{
              fontFamily: "Monaco, Courier New, monospace",
              fontSize: 13,
            }}
          />
        ) : (
          <pre
            style={{
              backgroundColor: isDark ? "#1f1f1f" : "#f5f5f5",
              color: isDark ? "rgba(255,255,255,0.85)" : "rgba(0,0,0,0.88)",
              padding: 16,
              borderRadius: 8,
              maxHeight: 500,
              overflow: "auto",
            }}
          >
            {clientJson}
          </pre>
        )}
      </Modal>

      <Modal
        title={`${client.name} - ${t("mcp.accessPolicy", "访问策略")}`}
        open={accessPolicyModalOpen}
        onCancel={() => !loadingPolicy && setAccessPolicyModalOpen(false)}
        footer={
          <div style={{ textAlign: "right" }}>
            <Button
              onClick={() => setAccessPolicyModalOpen(false)}
              style={{ marginRight: 8 }}
              disabled={loadingPolicy}
            >
              {t("common.cancel")}
            </Button>
            {!readOnly && accessPolicy ? (
              <Button
                type="primary"
                onClick={() => handleSaveAccessPolicy(accessPolicy)}
                loading={loadingPolicy}
              >
                {t("common.save")}
              </Button>
            ) : null}
          </div>
        }
        width={800}
      >
        {loadingPolicy ? (
          <div className={styles.toolsLoading}>
            <Spin />
          </div>
        ) : accessPolicy ? (
          <AccessPolicyEditor
            policy={accessPolicy}
            clientInfo={client}
            onChange={(p) => setAccessPolicy(p)}
            readOnly={readOnly}
            t={t}
          />
        ) : null}
      </Modal>
    </>
  );
});

// Access Policy Editor Component
interface AccessPolicyEditorProps {
  policy: MCPAccessPolicy;
  clientInfo?: MCPClientInfo;
  onChange: (policy: MCPAccessPolicy) => void;
  readOnly?: boolean;
  t: any;
}

const AccessPolicyEditor = React.memo(function AccessPolicyEditor({
  policy,
  clientInfo,
  onChange,
  readOnly,
  t,
}: AccessPolicyEditorProps) {
  const updateDefaultEffect = (effect: "allow" | "ask" | "deny") => {
    onChange({ ...policy, default_effect: effect });
  };

  return (
    <div className={styles.accessPolicyEditor}>
      <Form layout="vertical">
        <Form.Item label={t("mcp.policyDefaultEffect", "默认访问效果")} required>
          <Select
            value={policy.default_effect}
            onChange={updateDefaultEffect}
            disabled={readOnly}
            options={[
              { label: t("mcp.effectAllow", "允许"), value: "allow" },
              { label: t("mcp.effectAsk", "询问"), value: "ask" },
              { label: t("mcp.effectDeny", "拒绝"), value: "deny" },
            ]}
          />
        </Form.Item>

        <div className={styles.policySummary}>
          <p>
            {t(
              "mcp.policySummary",
              "当前策略摘要：默认效果为「{default_effect}」，覆盖规则数：{overrides_count}",
            )
              .replace("{default_effect}", policy.default_effect)
              .replace("{overrides_count}", String(policy.access_summary?.overrides_count || 0))}
          </p>
        </div>

        <div className={styles.toolsWhitelistSection}>
          <h4>{t("mcp.toolWhitelist", "工具白名单")}</h4>
          {clientInfo && clientInfo.tools && clientInfo.tools.length > 0 ? (
            <Tag.Group>
              {clientInfo.tools.map((tool) => (
                <Tag key={tool} color="blue">
                  {tool}
                </Tag>
              ))}
            </Tag.Group>
          ) : (
            <p style={{ color: "#999" }}>{t("mcp.noToolWhitelist", "未设置工具白名单（允许所有工具）")}</p>
          )}
        </div>

        {clientInfo && clientInfo.oauth_status && (
          <div className={styles.oauthStatusSection}>
            <h4>{t("mcp.oauthStatus", "OAuth 状态")}</h4>
            <Tag color={clientInfo.oauth_status.authorized ? "green" : "default"}>
              {clientInfo.oauth_status.authorized
                ? t("mcp.oauthAuthorized", "已授权")
                : t("mcp.oauthNotAuthorized", "未授权")}
            </Tag>
            {clientInfo.oauth_status.expires_at > 0 && (
              <span style={{ marginLeft: 8, color: "#666" }}>
                {t("mcp.expiresAt", "过期时间")}:{" "}
                {new Date(clientInfo.oauth_status.expires_at * 1000).toLocaleString()}
              </span>
            )}
          </div>
        )}
      </Form>
    </div>
  );
});
