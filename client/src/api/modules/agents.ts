import { request } from "../request";
import type {
  AgentListResponse,
  AgentProfileConfig,
  CreateAgentRequest,
  AgentProfileRef,
  ReorderAgentsResponse,
} from "../types/agents";

// Multi-agent management API
export const agentsApi = {
  // List all agents
  listAgents: () => request<AgentListResponse>("/agents"),

  // Get agent details
  getAgent: (agentId: string) =>
    request<AgentProfileConfig>(`/agents/${agentId}`),

  // Create new agent
  createAgent: (agent: CreateAgentRequest) =>
    request<AgentProfileRef>("/agents", {
      method: "POST",
      body: JSON.stringify(agent),
    }),

  // Update agent configuration
  updateAgent: (agentId: string, agent: AgentProfileConfig) =>
    request<AgentProfileConfig>(`/agents/${agentId}`, {
      method: "PUT",
      body: JSON.stringify(agent),
    }),

  // Delete agent
  deleteAgent: (agentId: string) =>
    request<{ success: boolean; agent_id: string }>(`/agents/${agentId}`, {
      method: "DELETE",
    }),

  // Persist ordered agent ids
  reorderAgents: (agentIds: string[]) =>
    request<ReorderAgentsResponse>("/agents/order", {
      method: "PUT",
      body: JSON.stringify({ agent_ids: agentIds }),
    }),

  // Toggle agent enabled state
  toggleAgentEnabled: (agentId: string, enabled: boolean) =>
    request<{ success: boolean; agent_id: string; enabled: boolean }>(
      `/agents/${agentId}/toggle`,
      {
        method: "PATCH",
        body: JSON.stringify({ enabled }),
      },
    ),

  // ── Identity file management (SOUL.md, MEMORY.md, PROFILE.md, etc.) ──

  /** List working markdown files for an agent */
  listWorkingFiles: (agentId: string) =>
    request<Array<{ name: string; path: string; size: number; modified: string }>>(
      "/agent/files",
      { headers: { "X-Agent-Id": agentId } }
    ),

  /** Read a working file content */
  readWorkingFile: (agentId: string, fileName: string) =>
    request<{ content: string }>(
      `/agent/files/${encodeURIComponent(fileName)}`,
      { headers: { "X-Agent-Id": agentId } }
    ),

  /** Write/update a working file content */
  writeWorkingFile: (agentId: string, fileName: string, content: string) =>
    request<{ written: boolean }>(
      `/agent/files/${encodeURIComponent(fileName)}`,
      {
        method: "PUT",
        headers: { "X-Agent-Id": agentId },
        body: JSON.stringify({ content }),
      }
    ),

  /** List memory files for an agent */
  listMemoryFiles: (agentId: string) =>
    request<Array<{ name: string; path: string; size: number; modified: string }>>(
      "/agent/memory",
      { headers: { "X-Agent-Id": agentId } }
    ),

  /** Read a memory file content */
  readMemoryFile: (agentId: string, fileName: string) =>
    request<{ content: string }>(
      `/agent/memory/${encodeURIComponent(fileName)}`,
      { headers: { "X-Agent-Id": agentId } }
    ),

  /** Write/update a memory file content */
  writeMemoryFile: (agentId: string, fileName: string, content: string) =>
    request<{ written: boolean }>(
      `/agent/memory/${encodeURIComponent(fileName)}`,
      {
        method: "PUT",
        headers: { "X-Agent-Id": agentId },
        body: JSON.stringify({ content }),
      }
    ),
};
