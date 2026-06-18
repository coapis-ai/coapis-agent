import { request } from "../request";
import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";
import type {
  BuiltinImportSpec,
  BuiltinUpdateNotice,
  CategorySpec,
  HubInstallTaskResponse,
  HubSkillSpec,
  PoolSkillSpec,
  SkillSpec,
  WorkspaceSkillSummary,
} from "../types";

// Declare VITE_API_BASE_URL as global (injected by Vite)
declare const VITE_API_BASE_URL: string;

// Simple in-memory cache with TTL
const CACHE_TTL_MS = 30000; // 30 seconds
const apiCache = new Map<string, { data: unknown; timestamp: number }>();

function getCached<T>(key: string): T | null {
  const cached = apiCache.get(key);
  if (!cached) return null;
  if (Date.now() - cached.timestamp > CACHE_TTL_MS) {
    apiCache.delete(key);
    return null;
  }
  return cached.data as T;
}

function setCache<T>(key: string, data: T): void {
  apiCache.set(key, { data, timestamp: Date.now() });
}

export function invalidateSkillCache(options?: {
  agentId?: string;
  workspaces?: boolean;
  pool?: boolean;
}): void {
  // Clear all skill-related cache entries
  for (const key of Array.from(apiCache.keys())) {
    if (!key.startsWith("/skills")) continue;

    // If no specific options provided, clear all
    if (!options) {
      apiCache.delete(key);
      continue;
    }

    // Targeted invalidation based on options
    if (options.pool && key === "/skills/pool") {
      apiCache.delete(key);
      apiCache.delete("/skills/pool/builtin-notice");
      apiCache.delete("/skills/pool/builtin-sources");
    } else if (options.workspaces && key === "/skills/workspaces") {
      apiCache.delete(key);
    } else if (options.agentId && key === `/skills?agent=${options.agentId}`) {
      apiCache.delete(key);
    } else if (options.agentId && key === "/skills") {
      // Also clear generic /skills cache when specific agent cache is invalidated
      apiCache.delete(key);
    }
  }
}

function getStreamApiUrl(): string {
  const base = typeof VITE_API_BASE_URL === "string" ? VITE_API_BASE_URL : "";
  return `${base}/api`;
}

async function _uploadZip(
  endpoint: string,
  file: File,
  options?: {
    enable?: boolean;
    target_name?: string;
    rename_map?: Record<string, string>;
  },
): Promise<Record<string, unknown>> {
  const formData = new FormData();
  formData.append("file", file);

  const params = new URLSearchParams();
  if (options?.enable !== undefined) {
    params.set("enable", String(options.enable));
  }
  if (options?.target_name) {
    params.set("target_name", options.target_name);
  }
  if (options?.rename_map && Object.keys(options.rename_map).length) {
    params.set("rename_map", JSON.stringify(options.rename_map));
  }
  const qs = params.toString();
  const url = getApiUrl(`${endpoint}${qs ? `?${qs}` : ""}`);

  const headers = buildAuthHeaders();

  const response = await fetch(url, {
    method: "POST",
    headers,
    body: formData,
  });

  if (!response.ok) {
    throw new Error(await response.text());
  }

  return await response.json();
}

export const skillApi = {
  listSkills: async (agentId?: string) => {
    const cacheKey = `/skills${agentId ? `?agent=${agentId}` : ""}`;
    const cached = getCached<SkillSpec[]>(cacheKey);
    if (cached) return cached;

    const opts: RequestInit = {};
    if (agentId) opts.headers = new Headers({ "X-Agent-Id": agentId });
    const data = await request<SkillSpec[]>("/skills", opts);
    setCache(cacheKey, data);
    return data;
  },

  listSkillWorkspaces: async () => {
    const cacheKey = "/skills/workspaces";
    const cached = getCached<WorkspaceSkillSummary[]>(cacheKey);
    if (cached) return cached;

    const data = await request<WorkspaceSkillSummary[]>("/skills/workspaces");
    setCache(cacheKey, data);
    return data;
  },

  listSkillPoolSkills: async () => {
    const cacheKey = "/skills/pool";
    const cached = getCached<PoolSkillSpec[]>(cacheKey);
    if (cached) return cached;

    const data = await request<PoolSkillSpec[]>("/skills/pool");
    // Ensure data is an array
    if (!Array.isArray(data)) {
      throw new Error(
        `Expected array from /skills/pool but got ${typeof data}`,
      );
    }
    setCache(cacheKey, data);
    return data;
  },

  refreshSkills: async (agentId?: string) => {
    const opts: RequestInit = { method: "POST" };
    if (agentId) opts.headers = new Headers({ "X-Agent-Id": agentId });
    const data = await request<SkillSpec[]>("/skills/refresh", opts);
    const cacheKey = `/skills${agentId ? `?agent=${agentId}` : ""}`;
    setCache(cacheKey, data);
    return data;
  },

  refreshSkillPool: async () => {
    const data = await request<PoolSkillSpec[]>("/skills/pool/refresh", {
      method: "POST",
    });
    // Ensure data is an array
    if (!Array.isArray(data)) {
      throw new Error(
        `Expected array from /skills/pool/refresh but got ${typeof data}`,
      );
    }
    setCache("/skills/pool", data);
    return data;
  },

  searchHubSkills: (q: string, limit: number = 20) =>
    request<HubSkillSpec[]>(
      `/skills/hub/search?q=${encodeURIComponent(q)}&limit=${limit}`,
    ),

  createSkill: (
    skillName: string,
    content: string,
    config?: Record<string, unknown>,
    enable?: boolean,
  ) =>
    request<{ created: boolean; name: string }>("/skills", {
      method: "POST",
      body: JSON.stringify({
        name: skillName,
        content,
        config,
        enable,
      }),
    }),

  saveSkill: (payload: {
    name: string;
    content: string;
    source_name?: string;
    config?: Record<string, unknown>;
    category?: string | null;
    overwrite?: boolean;
  }) =>
    request<{
      success: boolean;
      mode: "edit" | "rename" | "noop";
      name: string;
    }>("/skills/save", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  createSkillPoolSkill: (payload: {
    name: string;
    content: string;
    config?: Record<string, unknown>;
  }) =>
    request<{ created: boolean; name: string }>("/skills/pool/create", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  saveSkillPoolSkill: (payload: {
    name: string;
    content: string;
    source_name?: string;
    config?: Record<string, unknown>;
    overwrite?: boolean;
  }) =>
    request<{
      success: boolean;
      mode: "edit" | "rename" | "noop";
      name: string;
    }>("/skills/pool/save", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  enableSkill: (skillName: string) =>
    request<void>(`/skills/${encodeURIComponent(skillName)}/enable`, {
      method: "POST",
    }),

  disableSkill: (skillName: string) =>
    request<void>(`/skills/${encodeURIComponent(skillName)}/disable`, {
      method: "POST",
    }),

  batchEnableSkills: (skillNames: string[]) =>
    request<void>("/skills/batch-enable", {
      method: "POST",
      body: JSON.stringify(skillNames),
    }),

  batchDeleteSkills: (skillNames: string[]) =>
    request<{
      results: Record<string, { success: boolean; reason?: string }>;
    }>("/skills/batch-delete", {
      method: "POST",
      body: JSON.stringify(skillNames),
    }),

  batchDeletePoolSkills: (skillNames: string[]) =>
    request<{
      results: Record<string, { success: boolean; reason?: string }>;
    }>("/skills/pool/batch-delete", {
      method: "POST",
      body: JSON.stringify(skillNames),
    }),

  deleteSkill: (skillName: string) =>
    request<{ deleted: boolean }>(`/skills/${encodeURIComponent(skillName)}`, {
      method: "DELETE",
    }),

  startHubSkillInstall: (payload: {
    bundle_url: string;
    version?: string;
    enable?: boolean;
    target_name?: string;
  }) =>
    request<HubInstallTaskResponse>("/skills/hub/install/start", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  importPoolSkillFromHub: (payload: {
    bundle_url: string;
    version?: string;
    target_name?: string;
  }) =>
    request<{
      installed: boolean;
      name: string;
      enabled: boolean;
      source_url: string;
    }>("/skills/pool/import", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  getHubSkillInstallStatus: (taskId: string) =>
    request<HubInstallTaskResponse>(
      `/skills/hub/install/status/${encodeURIComponent(taskId)}`,
    ),

  cancelHubSkillInstall: (taskId: string) =>
    request<{ task_id: string; status: string }>(
      `/skills/hub/install/cancel/${encodeURIComponent(taskId)}`,
      {
        method: "POST",
      },
    ),

  listPoolBuiltinSources: () =>
    request<BuiltinImportSpec[]>("/skills/pool/builtin-sources"),

  getPoolBuiltinNotice: async () => {
    const cacheKey = "/skills/pool/builtin-notice";
    const cached = getCached<BuiltinUpdateNotice>(cacheKey);
    if (cached) return cached;

    const data = await request<BuiltinUpdateNotice>(
      "/skills/pool/builtin-notice",
    );
    setCache(cacheKey, data);
    return data;
  },

  importSelectedPoolBuiltins: (payload: {
    imports: Array<{ skill_name: string; language: string }>;
    overwrite_conflicts?: boolean;
  }) =>
    request<{
      imported: string[];
      updated: string[];
      unchanged: string[];
      conflicts: Array<{
        skill_name: string;
        language?: string;
        status?: string;
        source_name?: string;
        source_version_text?: string;
        current_version_text?: string;
        current_source?: string;
        current_language?: string;
      }>;
    }>("/skills/pool/import-builtin", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  updatePoolBuiltin: (skillName: string, language: string) =>
    request<Record<string, unknown>>(
      `/skills/pool/${encodeURIComponent(skillName)}/update-builtin`,
      {
        method: "POST",
        body: JSON.stringify({ language }),
      },
    ),

  deleteSkillPoolSkill: (skillName: string) =>
    request<{ deleted: boolean }>(
      `/skills/pool/${encodeURIComponent(skillName)}`,
      {
        method: "DELETE",
      },
    ),

  uploadWorkspaceSkillToPool: (payload: {
    workspace_id: string;
    skill_name: string;
    overwrite?: boolean;
    preview_only?: boolean;
  }) =>
    request<{ success: boolean; name: string }>("/skills/pool/upload", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  downloadSkillPoolSkill: (payload: {
    skill_name: string;
    targets: Array<{ workspace_id: string }>;
    all_workspaces?: boolean;
    overwrite?: boolean;
    preview_only?: boolean;
  }) =>
    request<{
      downloaded: Array<{
        workspace_id: string;
        workspace_name?: string;
        name: string;
      }>;
      conflicts?: Array<{
        reason?: string;
        skill_name?: string;
        workspace_id?: string;
        workspace_name?: string;
        suggested_name?: string;
        current_version_text?: string;
        source_version_text?: string;
      }>;
    }>("/skills/pool/download", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  updateSkillChannels: (skillName: string, channels: string[]) =>
    request<{ updated: boolean; channels: string[] }>(
      `/skills/${encodeURIComponent(skillName)}/channels`,
      {
        method: "PUT",
        body: JSON.stringify(channels),
      },
    ),

  updateSkillTags: (skillName: string, tags: string[]) =>
    request<{ updated: boolean; tags: string[] }>(
      `/skills/${encodeURIComponent(skillName)}/tags`,
      {
        method: "PUT",
        body: JSON.stringify(tags),
      },
    ),

  updatePoolSkillTags: (skillName: string, tags: string[]) =>
    request<{ updated: boolean; tags: string[] }>(
      `/skills/pool/${encodeURIComponent(skillName)}/tags`,
      {
        method: "PUT",
        body: JSON.stringify(tags),
      },
    ),

  getSkillConfig: (skillName: string) =>
    request<{ config: Record<string, unknown> }>(
      `/skills/${encodeURIComponent(skillName)}/config`,
    ),

  updateSkillConfig: (skillName: string, config: Record<string, unknown>) =>
    request<{ updated: boolean }>(
      `/skills/${encodeURIComponent(skillName)}/config`,
      {
        method: "PUT",
        body: JSON.stringify({ config }),
      },
    ),

  deleteSkillConfig: (skillName: string) =>
    request<{ cleared: boolean }>(
      `/skills/${encodeURIComponent(skillName)}/config`,
      { method: "DELETE" },
    ),

  getPoolSkillConfig: (skillName: string) =>
    request<{ config: Record<string, unknown> }>(
      `/skills/pool/${encodeURIComponent(skillName)}/config`,
    ),

  updatePoolSkillConfig: (skillName: string, config: Record<string, unknown>) =>
    request<{ updated: boolean }>(
      `/skills/pool/${encodeURIComponent(skillName)}/config`,
      {
        method: "PUT",
        body: JSON.stringify({ config }),
      },
    ),

  deletePoolSkillConfig: (skillName: string) =>
    request<{ cleared: boolean }>(
      `/skills/pool/${encodeURIComponent(skillName)}/config`,
      { method: "DELETE" },
    ),

  // ── Skill Evolution / Metrics ──────────────────────────────────────

  getSkillMetrics: async (params?: {
    sort_by?: string;
    limit?: number;
    refresh?: boolean;
  }) => {
    const qs = new URLSearchParams();
    if (params?.sort_by) qs.set("sort_by", params.sort_by);
    if (params?.limit) qs.set("limit", String(params.limit));
    if (params?.refresh) qs.set("refresh", "true");
    const q = qs.toString();
    return request<{
      metrics: Array<{
        skill_name: string;
        precision: number;
        reliability: number;
        effectiveness: number;
        satisfaction: number;
        robustness: number;
        composite_score: number;
        total_triggers: number;
        skill_tool_used_count: number;
        tool_success_count: number;
        tool_error_count: number;
        user_followup_count: number;
        last_triggered_at: string;
        last_computed_at: string;
        top_keywords: string[];
      }>;
      funnel: {
        funnel: Array<{ stage: string; count: number }>;
        rates: {
          trigger_to_use: number;
          use_to_success: number;
          overall_satisfaction: number;
        };
      };
      total_skills: number;
    }>(`/skills/metrics${q ? `?${q}` : ""}`);
  },

  getSkillMetricDetail: (skillName: string) =>
    request<{
      skill_name: string;
      precision: number;
      reliability: number;
      effectiveness: number;
      satisfaction: number;
      robustness: number;
      composite_score: number;
      total_triggers: number;
      skill_tool_used_count: number;
      tool_success_count: number;
      tool_error_count: number;
      user_followup_count: number;
      last_triggered_at: string;
      last_computed_at: string;
      top_keywords: string[];
    }>(`/skills/metrics/${encodeURIComponent(skillName)}`),

  refreshSkillMetrics: () =>
    request<{ skills_count: number; total_triggers: number; computed_at: string }>(
      "/skills/metrics/refresh",
      { method: "POST" },
    ),

  getSkillVersions: (skillName: string) =>
    request<{
      skill_name: string;
      versions: Array<{
        version: string;
        archived_at: string;
        size_bytes: number;
        file_count?: number;
        description: string;
      }>;
      total: number;
    }>(`/skills/${encodeURIComponent(skillName)}/versions`),

  rollbackSkillVersion: (skillName: string, version: string) =>
    request<{
      success: boolean;
      skill_name: string;
      restored_version: string;
      versions_count: number;
    }>(`/skills/${encodeURIComponent(skillName)}/rollback/${encodeURIComponent(version)}`, {
      method: "POST",
    }),

  getSkillTriggers: (skillName: string) =>
    request<{
      skill_name: string;
      base_triggers: string[];
      effective_triggers: string[];
      overrides: {
        added_keywords: string[];
        removed_keywords: string[];
        refined_keywords: string[];
      };
    }>(`/skills/${encodeURIComponent(skillName)}/triggers`),

  updateSkillTriggers: (
    skillName: string,
    body: {
      added_keywords?: string[];
      removed_keywords?: string[];
      refined_keywords?: string[];
      reset?: boolean;
    },
  ) =>
    request<{
      success: boolean;
      skill_name: string;
      action: string;
      overrides?: Record<string, string[]>;
      effective_triggers: string[];
    }>(`/skills/${encodeURIComponent(skillName)}/triggers`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  // ── Skill Categories ──────────────────────────────────────────────

  listCategories: async () => {
    const cacheKey = "/skills/categories";
    const cached = getCached<CategorySpec[]>(cacheKey);
    if (cached) return cached;
    const data = await request<CategorySpec[]>("/skills/categories");
    setCache(cacheKey, data);
    return data;
  },

  createCategory: (payload: { key: string; label: string; emoji?: string }) =>
    request<CategorySpec>("/skills/categories", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  updateCategory: (
    key: string,
    payload: { label?: string; emoji?: string; sort_order?: number; new_key?: string },
  ) =>
    request<CategorySpec>(`/skills/categories/${encodeURIComponent(key)}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  deleteCategory: (key: string) =>
    request<{ deleted: string }>(`/skills/categories/${encodeURIComponent(key)}`, {
      method: "DELETE",
    }),

  streamOptimizeSkill: async function (
    content: string,
    onChunk: (text: string) => void,
    signal: AbortSignal,
    language: string = "en",
  ): Promise<void> {
    const apiUrl = getStreamApiUrl();

    const response = await fetch(`${apiUrl}/skills/ai/optimize/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ content, language }),
      signal,
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error("No reader available");
    }

    const decoder = new TextDecoder();
    let buffer = "";

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");

        for (let i = 0; i < lines.length - 1; i++) {
          const line = lines[i].trim();
          if (line.startsWith("data: ")) {
            const data = line.slice(6);
            try {
              const parsed = JSON.parse(data);
              if (parsed.text) {
                onChunk(parsed.text);
              } else if (parsed.error) {
                throw new Error(parsed.error);
              } else if (parsed.done) {
                return;
              }
            } catch {
              // Ignore malformed chunks.
            }
          }
        }

        buffer = lines[lines.length - 1];
      }
    } finally {
      reader.releaseLock();
    }
  },

  uploadSkill: (
    file: File,
    options?: {
      enable?: boolean;
      target_name?: string;
      rename_map?: Record<string, string>;
    },
  ) =>
    _uploadZip("/skills/upload", file, options) as Promise<{
      imported: string[];
      count: number;
      enabled: boolean;
      conflicts?: Array<{
        reason: string;
        skill_name: string;
        suggested_name: string;
      }>;
    }>,

  uploadSkillPoolZip: (
    file: File,
    options?: {
      target_name?: string;
      rename_map?: Record<string, string>;
    },
  ) =>
    _uploadZip("/skills/pool/upload-zip", file, options) as Promise<{
      imported: string[];
      count: number;
      conflicts?: Array<{
        reason: string;
        skill_name: string;
        suggested_name: string;
      }>;
    }>,

  // ── 晋升/退役管理 ──

  getPromotionCandidates: () =>
    request("/api/skills/promotion/candidates") as Promise<{
      candidates: Array<{
        skill_name: string;
        composite_score: number;
        user_count: number;
        users: string[];
        age_days: number;
        total_triggers: number;
        status: string;
      }>;
      total: number;
    }>,

  approvePromotion: (skillName: string) =>
    request(`/api/skills/promotion/${encodeURIComponent(skillName)}/approve`, { method: "POST" }) as Promise<{
      success: boolean;
      candidate: Record<string, unknown>;
    }>,

  rejectPromotion: (skillName: string) =>
    request(`/api/skills/promotion/${encodeURIComponent(skillName)}/reject`, { method: "POST" }) as Promise<{
      success: boolean;
      candidate: Record<string, unknown>;
    }>,

  getRetirementCandidates: () =>
    request("/api/skills/retirement/candidates") as Promise<{
      candidates: Array<{
        skill_name: string;
        composite_score: number;
        total_triggers: number;
        days_since_last_trigger: number;
        consecutive_failures: number;
        reasons: string[];
        status: string;
      }>;
      total: number;
    }>,

  getTriggerAggregation: (skillName: string) =>
    request(`/api/skills/cross-agent/trigger-aggregation/${encodeURIComponent(skillName)}`) as Promise<{
      skill_name: string;
      aggregation: Array<{
        keyword: string;
        signal_type: string;
        user_count: number;
        users: string[];
        total_reports: number;
        promotable: boolean;
      }>;
      total: number;
      promotable_count: number;
    }>,

  // ── 改进建议 ──

  getSkillSuggestions: (params?: { skill_name?: string; status?: string }) => {
    const qs = params ? "?" + new URLSearchParams(params as Record<string, string>).toString() : "";
    return request(`/api/skills/suggestions${qs}`) as Promise<{
      suggestions: Array<Record<string, unknown>>;
      total: number;
    }>;
  },

  approveSuggestion: (suggestionId: string) =>
    request(`/api/skills/suggestions/${encodeURIComponent(suggestionId)}/approve`, { method: "POST" }) as Promise<{
      success: boolean;
      suggestion: Record<string, unknown>;
    }>,

  rejectSuggestion: (suggestionId: string) =>
    request(`/api/skills/suggestions/${encodeURIComponent(suggestionId)}/reject`, { method: "POST" }) as Promise<{
      success: boolean;
      suggestion: Record<string, unknown>;
    }>,

  analyzeSkillIssues: (skillName: string) =>
    request(`/api/skills/${encodeURIComponent(skillName)}/improve/analyze`) as Promise<{
      skill_name: string;
      trigger_issues: Record<string, unknown>;
      content_issues: Record<string, unknown>;
      has_issues: boolean;
    }>,

  generateSkillSuggestion: (skillName: string, body?: Record<string, unknown>) =>
    request(`/api/skills/${encodeURIComponent(skillName)}/improve/suggest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    }) as Promise<{
      skill_name: string;
      suggestions: Array<Record<string, unknown>>;
      total: number;
    }>,

  exportSkills: async (skillNames: string[], workspaceId: string) => {
    const url = getApiUrl("/skills/export");
    const resp = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...buildAuthHeaders(),
      },
      body: JSON.stringify({ skill_names: skillNames, workspace_id: workspaceId }),
    });
    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(`Export failed (${resp.status}): ${text}`);
    }
    const blob = await resp.blob();
    const disposition = resp.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^";\n]+)"?/);
    const filename = match?.[1] || "skills.zip";
    return { blob, filename };
  },
};
