import { useCallback, useEffect, useState } from "react";
import { useAppMessage } from "../../../hooks/useAppMessage";
import api from "../../../api";
import type {
  ToolInfo,
  ToolTag,
  ToolGroup,
} from "../../../api/modules/tools";
import { useTranslation } from "react-i18next";
import { useAgentStore } from "../../../stores/agentStore";

export function useTools() {
  const { t } = useTranslation();
  const { selectedAgent } = useAgentStore();

  // ── Core state ──
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [tags, setTags] = useState<ToolTag[]>([]);
  const [groups, setGroups] = useState<ToolGroup[]>([]);
  const [loading, setLoading] = useState(false);
  const [batchLoading, setBatchLoading] = useState(false);

  // ── Filter state ──
  const [search, setSearch] = useState("");
  const [selectedTag, setSelectedTag] = useState<string | null>(null);
  const [selectedGroup, setSelectedGroup] = useState<string | null>(null);

  // ── Detail drawer ──
  const [selectedTool, setSelectedTool] = useState<ToolInfo | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const { message } = useAppMessage();

  // ── Load tools ──
  const loadTools = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.tools.listTools({
        tag: selectedTag ?? undefined,
        group: selectedGroup ?? undefined,
        search: search || undefined,
      });
      setTools(data);
    } catch (error: unknown) {
      const err = error as Error & { status?: number; isForbidden?: boolean };
      if (err.isForbidden || err.status === 403) {
        setTools([]);
      } else {
        message.error(t("tools.loadError"));
      }
    } finally {
      setLoading(false);
    }
  }, [t, selectedTag, selectedGroup, search]);

  const loadTags = useCallback(async () => {
    try {
      const data = await api.tools.listTags();
      setTags(data);
    } catch {
      // silent
    }
  }, []);

  const loadGroups = useCallback(async () => {
    try {
      const data = await api.tools.listGroups();
      setGroups(data || []);
    } catch {
      // silent
    }
  }, []);

  useEffect(() => {
    loadTools();
  }, [loadTools, selectedAgent]);

  useEffect(() => {
    loadTags();
    loadGroups();
  }, [loadTags, loadGroups]);

  // ── Toggle ──
  const toggleEnabled = useCallback(
    async (tool: ToolInfo) => {
      setTools((prev) =>
        prev.map((t) =>
          t.name === tool.name ? { ...t, enabled: !t.enabled } : t,
        ),
      );
      try {
        const result = await api.tools.toggleTool(tool.name);
        setTools((prev) =>
          prev.map((t) => (t.name === result.name ? result : t)),
        );
        message.success(
          tool.enabled ? t("tools.disableSuccess") : t("tools.enableSuccess"),
        );
        loadTags();
      } catch {
        setTools((prev) =>
          prev.map((t) =>
            t.name === tool.name ? { ...t, enabled: tool.enabled } : t,
          ),
        );
        message.error(t("tools.toggleError"));
      }
    },
    [t, loadTags],
  );

  // ── Enable / Disable all ──
  const enableAll = useCallback(async () => {
    setBatchLoading(true);
    try {
      const result = await api.tools.enableAll();
      message.success(`已启用 ${result.enabled.length} 个工具`);
      loadTools();
      loadTags();
      loadGroups();
    } catch {
      message.error("批量启用失败");
    } finally {
      setBatchLoading(false);
    }
  }, [loadTools, loadTags, loadGroups]);

  const disableAll = useCallback(async () => {
    setBatchLoading(true);
    try {
      const result = await api.tools.disableAll();
      message.success(`已禁用 ${result.enabled.length} 个工具`);
      loadTools();
      loadTags();
      loadGroups();
    } catch {
      message.error("批量禁用失败");
    } finally {
      setBatchLoading(false);
    }
  }, [loadTools, loadTags, loadGroups]);

  // ── Delete ──
  const deleteTool = useCallback(
    async (toolName: string) => {
      try {
        await api.tools.deleteTool(toolName);
        message.success(`已删除自定义工具: ${toolName}`);
        setTools((prev) => prev.filter((t) => t.name !== toolName));
        loadTags();
      } catch {
        message.error("删除工具失败（仅支持删除自定义工具）");
      }
    },
    [loadTags],
  );

  // ── Detail ──
  const openDetail = useCallback((tool: ToolInfo) => {
    setSelectedTool(tool);
    setDrawerOpen(true);
  }, []);

  const closeDetail = useCallback(() => {
    setDrawerOpen(false);
    setSelectedTool(null);
  }, []);

  return {
    tools,
    tags,
    groups,
    loading,
    batchLoading,
    search,
    setSearch,
    selectedTag,
    setSelectedTag,
    selectedGroup,
    setSelectedGroup,
    toggleEnabled,
    enableAll,
    disableAll,
    deleteTool,
    selectedTool,
    drawerOpen,
    openDetail,
    closeDetail,
    refresh: loadTools,
  };
}
