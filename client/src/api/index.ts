export * from "./types";

export { request } from "./request";

export { getApiUrl, getApiToken } from "./config";

import { request as _request } from "./request";
import { rootApi } from "./modules/root";
// import { acpApi } from "./modules/acp";  // ACP 模块已隐藏 — 2026-06-28
import { channelApi } from "./modules/channel";
import { heartbeatApi } from "./modules/heartbeat";
import { cronJobApi } from "./modules/cronjob";
import { chatApi, sessionApi } from "./modules/chat";
import { envApi } from "./modules/env";
import { providerApi } from "./modules/provider";
import { skillApi } from "./modules/skill";
import { agentApi } from "./modules/agent";
import { agentsApi } from "./modules/agents";
import { workspaceApi } from "./modules/workspace";
import { localModelApi } from "./modules/localModel";
import { mcpApi } from "./modules/mcp";
import { tokenUsageApi } from "./modules/tokenUsage";
import { agentStatsApi } from "./modules/agentStats";
import { toolsApi } from "./modules/tools";
import { securityApi } from "./modules/security";
import { userTimezoneApi } from "./modules/userTimezone";
import { languageApi } from "./modules/language";
import { backupApi } from "./modules/backup";
import { cleanupApi } from "./modules/cleanup";
import { knowledgeApi } from "./modules/knowledge";

// Generic HTTP methods for direct API calls
export const api = {
  // Generic methods
  get: <T = unknown>(path: string, options?: RequestInit) => _request<T>(path, { ...options, method: "GET" }),
  post: <T = unknown>(path: string, data?: unknown, options?: RequestInit) => _request<T>(path, { ...options, method: "POST", body: data ? JSON.stringify(data) : undefined }),
  put: <T = unknown>(path: string, data?: unknown, options?: RequestInit) => _request<T>(path, { ...options, method: "PUT", body: data ? JSON.stringify(data) : undefined }),
  delete: <T = unknown>(path: string, options?: RequestInit) => _request<T>(path, { ...options, method: "DELETE" }),

  // Root
  ...rootApi,

  // ACP — 模块已隐藏 2026-06-28
  // ...acpApi,

  // Channels
  ...channelApi,

  // Heartbeat
  ...heartbeatApi,

  // Cron Jobs
  ...cronJobApi,

  // Chats
  ...chatApi,

  // Sessions（Legacy aliases）
  ...sessionApi,

  // Environment Variables
  ...envApi,

  // Providers
  ...providerApi,

  // Agent
  ...agentApi,

  // Skills
  ...skillApi,

  // Workspace
  ...workspaceApi,

  // Local Models
  ...localModelApi,

  // MCP Clients
  ...mcpApi,

  // Token Usage
  ...tokenUsageApi,
  // Agent Statistics
  ...agentStatsApi,
  // Tools (namespaced)
  tools: toolsApi,

  // Security
  ...securityApi,

  // User Timezone
  ...userTimezoneApi,

  // Language
  ...languageApi,

  // Backups
  ...backupApi,

  // Cleanup & Archive
  ...cleanupApi,

  // Knowledge Base
  ...knowledgeApi,
};

export default api;

// Export individual APIs for direct access
export { agentsApi, skillApi };
