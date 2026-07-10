import api from '@/api';

export interface ToolTag {
  tag: string;
  count: number;
}

export interface ToolCategory {
  category: string;
  count: number;
}

export interface ToolScene {
  scene: string;
  count: number;
}

export interface ToolGroup {
  group: string;
  count: number;
}

export interface ToolInfo {
  name: string;
  enabled: boolean;
  description: string;
  category: string;
  group: string;
  tags: string[];
  scene: string;
  async_execution: boolean;
  icon: string;
  builtin: boolean;
}

export interface ToolStatsSummary {
  total: number;
  enabled: number;
  disabled: number;
  groups: Record<string, number>;
  categories: Record<string, number>;
  builtin_count: number;
  plugin_count: number;
}

export default {
  /** List all tools */
  list: (params?: {
    tag?: string;
    category?: string;
    scene?: string;
    group?: string;
    search?: string;
    enabled_only?: boolean;
  }) => {
    const query = new URLSearchParams();
    if (params) {
      Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== '') {
          query.append(key, String(value));
        }
      });
    }
    const queryString = query.toString();
    return api.get(`/tools${queryString ? `?${queryString}` : ''}`).then((res: any) => res.data || res);
  },

  /** Alias for Agent/Tools page compatibility */
  listTools: function (params?: {
    tag?: string;
    category?: string;
    scene?: string;
    group?: string;
    search?: string;
    enabled_only?: boolean;
  }) {
    return this.list(params);
  },

  /** List tool tags */
  listTags: () =>
    api.get('/tools/tags').then((res: any) => res.data || res),

  /** List tool categories */
  listCategories: () =>
    api.get('/tools/categories').then((res: any) => res.data || res),

  /** List tool groups (functional TOOL_GROUPS) */
  listGroups: () =>
    api.get('/tools/groups').then((res: any) => res.data || res),

  /** List tool scenes */
  listScenes: () =>
    api.get('/tools/scenes').then((res: any) => res.data || res),

  /** Get tool stats summary */
  stats: () =>
    api.get('/tools/stats').then((res: any) => res.data || res),

  /** Toggle tool enabled/disabled */
  toggle: (toolName: string, enabled?: boolean) =>
    api.patch(`/tools/${toolName}/toggle`, enabled !== undefined ? { enabled } : undefined).then((res: any) => res.data || res),

  /** Alias for Agent/Tools page compatibility */
  toggleTool: function (toolName: string, enabled?: boolean) {
    return this.toggle(toolName, enabled);
  },

  /** Enable all tools */
  enableAll: () =>
    api.post('/tools/enable-all').then((res: any) => res.data || res),

  /** Disable all tools */
  disableAll: () =>
    api.post('/tools/disable-all').then((res: any) => res.data || res),

  /** Delete a custom tool (built-in tools cannot be deleted) */
  deleteTool: (toolName: string) =>
    api.delete(`/tools/${toolName}`).then((res: any) => res.data || res),
};
