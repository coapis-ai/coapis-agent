import { request } from "../request";

export interface ToolInfo {
  name: string;
  enabled: boolean;
  description: string;
  category: string;
  tags: string[];
  scene: string;
  async_execution: boolean;
  icon: string;
  builtin: boolean;
}

export interface ToolTag {
  tag: string;
  count: number;
}

export interface ToolCategory {
  category: string;
  count: number;
}

export interface ToolStats {
  total: number;
  enabled: number;
  disabled: number;
  categories: Record<string, number>;
  builtin_count: number;
  plugin_count: number;
}

export const toolsApi = {
  /** List all tools with optional filters */
  listTools: (params?: {
    tag?: string;
    category?: string;
    scene?: string;
    search?: string;
    enabled_only?: boolean;
  }) => {
    const query = new URLSearchParams();
    if (params?.tag) query.set("tag", params.tag);
    if (params?.category) query.set("category", params.category);
    if (params?.scene) query.set("scene", params.scene);
    if (params?.search) query.set("search", params.search);
    if (params?.enabled_only !== undefined)
      query.set("enabled_only", String(params.enabled_only));
    const qs = query.toString();
    return request<ToolInfo[]>(`/tools${qs ? `?${qs}` : ""}`);
  },

  /** Get tool detail */
  getTool: (toolName: string) =>
    request<ToolInfo>(`/tools/${encodeURIComponent(toolName)}`),

  /** Toggle tool enabled status */
  toggleTool: (toolName: string) =>
    request<ToolInfo>(`/tools/${encodeURIComponent(toolName)}/toggle`, {
      method: "PATCH",
    }),

  /** Enable a tool */
  enableTool: (toolName: string) =>
    request<ToolInfo>(`/tools/${encodeURIComponent(toolName)}/enable`, {
      method: "PATCH",
    }),

  /** Disable a tool */
  disableTool: (toolName: string) =>
    request<ToolInfo>(`/tools/${encodeURIComponent(toolName)}/disable`, {
      method: "PATCH",
    }),

  /** Update async execution */
  updateAsyncExecution: (toolName: string, asyncExecution: boolean) =>
    request<ToolInfo>(
      `/tools/${encodeURIComponent(toolName)}/async-execution`,
      {
        method: "PATCH",
        body: JSON.stringify({ async_execution: asyncExecution }),
      },
    ),

  /** Enable all tools */
  enableAll: () => request<{ enabled: number; total: number }>("/tools/enable-all", { method: "POST" }),

  /** Disable all tools */
  disableAll: () => request<{ disabled: number; total: number }>("/tools/disable-all", { method: "POST" }),

  /** List all tags with counts */
  listTags: () => request<ToolTag[]>("/tools/tags"),

  /** List all categories with counts */
  listCategories: () => request<ToolCategory[]>("/tools/categories"),

  /** Get tool stats summary */
  getStats: () => request<ToolStats>("/tools/stats"),

  /** Delete a custom/plugin tool */
  deleteTool: (toolName: string) =>
    request<{ deleted: string }>(`/tools/${encodeURIComponent(toolName)}`, {
      method: "DELETE",
    }),
};
