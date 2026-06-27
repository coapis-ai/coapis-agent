import { useState } from "react";
import { Button, Empty, Modal, Input, Tooltip } from "@agentscope-ai/design";
import { PlusOutlined, LockOutlined, GlobalOutlined } from "@ant-design/icons";
import type { MCPClientInfo } from "../../../api/types";
import { MCPClientCard } from "./components";
import { useMCP } from "./useMCP";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import { usePermission } from "@/hooks/usePermission";
import styles from "./index.module.less";

type MCPTransport = "stdio" | "streamable_http" | "sse";

function normalizeTransport(raw?: unknown): MCPTransport | undefined {
  if (typeof raw !== "string") return undefined;
  const value = raw.trim().toLowerCase();
  switch (value) {
    case "stdio":
      return "stdio";
    case "sse":
      return "sse";
    case "streamablehttp":
    case "streamable_http":
    case "streamable-http":
    case "http":
      return "streamable_http";
    default:
      return undefined;
  }
}

function normalizeClientData(key: string, rawData: any) {
  const transport =
    normalizeTransport(rawData.transport ?? rawData.type) ??
    (rawData.url || rawData.baseUrl || !rawData.command
      ? "streamable_http"
      : "stdio");

  const command =
    transport === "stdio" ? (rawData.command ?? "").toString() : "";

  return {
    name: rawData.name || key,
    description: rawData.description || "",
    enabled: rawData.enabled ?? rawData.isActive ?? true,
    transport,
    url: (rawData.url || rawData.baseUrl || "").toString(),
    headers: rawData.headers || {},
    command,
    args: Array.isArray(rawData.args) ? rawData.args : [],
    env: rawData.env || {},
    cwd: (rawData.cwd || "").toString(),
  };
}

function MCPPage() {
  const { t } = useTranslation();
  const {
    clients,
    globalClients,
    userClients,
    loading,
    toggleEnabled,
    deleteClient,
    createClient,
    updateClient,
  } = useMCP();
  const { hasPermission } = usePermission();
  const canWrite = hasPermission("mcp:write");
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [newClientJson, setNewClientJson] = useState(`{
  "mcpServers": {
    "example-client": {
      "command": "npx",
      "args": ["-y", "@example/mcp-server"],
      "env": {
        "API_KEY": "<YOUR_API_KEY>"
      }
    }
  }
}`);

  const handleToggleEnabled = async (
    client: MCPClientInfo,
    e?: React.MouseEvent,
  ) => {
    e?.stopPropagation();
    await toggleEnabled(client);
  };

  const handleDelete = async (client: MCPClientInfo, e?: React.MouseEvent) => {
    e?.stopPropagation();
    await deleteClient(client);
  };

  const handleCreateClient = async () => {
    try {
      const parsed = JSON.parse(newClientJson);

      const clientsToCreate: Array<{ key: string; data: any }> = [];

      if (parsed.mcpServers) {
        Object.entries(parsed.mcpServers).forEach(
          ([key, data]: [string, any]) => {
            clientsToCreate.push({
              key,
              data: normalizeClientData(key, data),
            });
          },
        );
      } else if (
        parsed.key &&
        (parsed.command || parsed.url || parsed.baseUrl)
      ) {
        const { key, ...clientData } = parsed;
        clientsToCreate.push({
          key,
          data: normalizeClientData(key, clientData),
        });
      } else {
        Object.entries(parsed).forEach(([key, data]: [string, any]) => {
          if (
            typeof data === "object" &&
            (data.command || data.url || data.baseUrl)
          ) {
            clientsToCreate.push({
              key,
              data: normalizeClientData(key, data),
            });
          }
        });
      }

      let allSuccess = true;
      for (const { key, data } of clientsToCreate) {
        const success = await createClient(key, data);
        if (!success) allSuccess = false;
      }

      if (allSuccess) {
        setCreateModalOpen(false);
        setNewClientJson(`{
  "mcpServers": {
    "example-client": {
      "command": "npx",
      "args": ["-y", "@example/mcp-server"],
      "env": {
        "API_KEY": "<YOUR_API_KEY>"
      }
    }
  }
}`);
      }
    } catch (error) {
      alert("Invalid JSON format");
    }
  };

  return (
    <div className={styles.mcpPage}>
      <PageHeader
        items={[{ title: t("nav.agent") }, { title: t("mcp.title") }]}
        extra={
          canWrite ? (
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => setCreateModalOpen(true)}
            >
              {t("mcp.create")}
            </Button>
          ) : (
            <Tooltip title={t("mcp.readOnlyHint", "需要管理员或高级用户权限")}>
              <LockOutlined style={{ color: "#999", fontSize: 16 }} />
            </Tooltip>
          )
        }
      />

      {loading ? (
        <div className={styles.loading}>
          <p>{t("common.loading")}</p>
        </div>
      ) : clients.length === 0 ? (
        <div className={styles.emptyState}>
          <Empty description={t("mcp.emptyState")} />
        </div>
      ) : (
        <>
          {/* Global MCP section */}
          {globalClients.length > 0 && (
            <div className={styles.mcpSection}>
              <div className={styles.sectionHeader}>
                <GlobalOutlined style={{ marginRight: 8 }} />
                <span>
                  {t("mcp.globalPool", "系统 MCP（管理员配置）")}
                </span>
              </div>
              <div className={styles.mcpGrid}>
                {globalClients.map((client) => (
                  <MCPClientCard
                    key={client.key}
                    client={client}
                    onToggle={canWrite ? handleToggleEnabled : undefined}
                    onDelete={canWrite ? handleDelete : undefined}
                    onUpdate={canWrite ? updateClient : undefined}
                    readOnly={!canWrite}
                  />
                ))}
              </div>
            </div>
          )}

          {/* User MCP section */}
          {userClients.length > 0 && (
            <div className={styles.mcpSection}>
              <div className={styles.sectionHeader}>
                <span>
                  {t("mcp.userClients", "我的 MCP")}
                </span>
              </div>
              <div className={styles.mcpGrid}>
                {userClients.map((client) => (
                  <MCPClientCard
                    key={client.key}
                    client={client}
                    onToggle={canWrite ? handleToggleEnabled : undefined}
                    onDelete={canWrite ? handleDelete : undefined}
                    onUpdate={canWrite ? updateClient : undefined}
                    readOnly={!canWrite}
                  />
                ))}
              </div>
            </div>
          )}
        </>
      )}

      <Modal
        title={t("mcp.create")}
        open={createModalOpen}
        onCancel={() => setCreateModalOpen(false)}
        footer={
          <div className={styles.modalFooter}>
            <Button
              onClick={() => setCreateModalOpen(false)}
              style={{ marginRight: 8 }}
            >
              {t("common.cancel")}
            </Button>
            <Button type="primary" onClick={handleCreateClient}>
              {t("common.create")}
            </Button>
          </div>
        }
        width={800}
      >
        <div className={styles.importHint}>
          <p className={styles.importHintTitle}>{t("mcp.formatSupport")}:</p>
          <ul className={styles.importHintList}>
            <li>
              {t("mcp.standardFormat")}:{" "}
              <code>{`{ "mcpServers": { "key": {...} } }`}</code>
            </li>
            <li>
              {t("mcp.directFormat")}: <code>{`{ "key": {...} }`}</code>
            </li>
            <li>
              {t("mcp.singleFormat")}:{" "}
              <code>{`{ "key": "...", "name": "...", "command": "..." }`}</code>
            </li>
          </ul>
        </div>
        <Input.TextArea
          value={newClientJson}
          onChange={(e) => setNewClientJson(e.target.value)}
          autoSize={{ minRows: 15, maxRows: 25 }}
          className={styles.jsonTextArea}
        />
      </Modal>
    </div>
  );
}

export default MCPPage;
