import { useCallback, useEffect, useState } from "react";
import { useAppMessage } from "../../../hooks/useAppMessage";
import api from "../../../api";
import type { MCPClientInfo } from "../../../api/types";
import { useTranslation } from "react-i18next";
import { useAgentStore } from "../../../stores/agentStore";

export function useMCP() {
  const { t } = useTranslation();
  const { selectedAgent } = useAgentStore();
  const [clients, setClients] = useState<MCPClientInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const { message } = useAppMessage();

  const loadClients = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.listMCPClients();
      setClients(data);
    } catch (error: unknown) {
      const err = error as Error & { status?: number; isForbidden?: boolean };
      if (err.isForbidden || err.status === 403) {
        console.warn("MCP: permission denied (read-only mode)");
        setClients([]);
      } else {
        console.error("Failed to load MCP clients:", error);
        message.error(t("mcp.loadError"));
      }
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    loadClients();
  }, [loadClients, selectedAgent]);

  // Derived lists: global vs user
  const globalClients = clients.filter((c) => c.source === "global");
  const userClients = clients.filter((c) => c.source === "user");

  const createClient = useCallback(
    async (
      key: string,
      clientData: {
        name: string;
        description?: string;
        command: string;
        enabled?: boolean;
        transport?: "stdio" | "streamable_http" | "sse";
        url?: string;
        headers?: Record<string, string>;
        args?: string[];
        env?: Record<string, string>;
        cwd?: string;
      },
    ) => {
      try {
        await api.createMCPClient({
          client_key: key,
          client: clientData,
        });
        message.success(t("mcp.createSuccess"));
        await loadClients();
        return true;
      } catch (error: any) {
        const errorMsg = error?.message || t("mcp.createError");
        message.error(errorMsg);
        return false;
      }
    },
    [t, loadClients],
  );

  const updateClient = useCallback(
    async (
      key: string,
      updates: {
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
      },
    ) => {
      try {
        await api.updateMCPClient(key, updates);
        message.success(t("mcp.updateSuccess"));
        await loadClients();
        return true;
      } catch (error: any) {
        const errorMsg = error?.message || t("mcp.updateError");
        message.error(errorMsg);
        return false;
      }
    },
    [t, loadClients],
  );

  const toggleEnabled = useCallback(
    async (client: MCPClientInfo) => {
      try {
        await api.toggleMCPClient(client.key);
        message.success(
          client.enabled ? t("mcp.disableSuccess") : t("mcp.enableSuccess"),
        );
        await loadClients();
      } catch (error) {
        message.error(t("mcp.toggleError"));
      }
    },
    [t, loadClients],
  );

  const deleteClient = useCallback(
    async (client: MCPClientInfo) => {
      try {
        await api.deleteMCPClient(client.key);
        message.success(t("mcp.deleteSuccess"));
        await loadClients();
      } catch (error) {
        message.error(t("mcp.deleteError"));
      }
    },
    [t, loadClients],
  );

  const installMCP = useCallback(
    async (packageName: string, installType: "pip" | "npm") => {
      try {
        const result = await api.installMCPPackage({
          package: packageName,
          install_type: installType,
        });
        if (result.status === "success" || result.status === "already_installed") {
          message.success(result.message || `Installed ${packageName}`);
          return true;
        } else {
          message.error(result.message || `Failed to install ${packageName}`);
          return false;
        }
      } catch (error: any) {
        const errorMsg = error?.message || `Failed to install ${packageName}`;
        message.error(errorMsg);
        return false;
      }
    },
    [message],
  );

  return {
    clients,
    globalClients,
    userClients,
    loading,
    createClient,
    updateClient,
    toggleEnabled,
    deleteClient,
    installMCP,
  };
}
