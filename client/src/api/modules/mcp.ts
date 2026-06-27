import { request } from "../request";
import type {
  MCPClientInfo,
  MCPClientCreateRequest,
  MCPClientUpdateRequest,
  MCPToolInfo,
} from "../types";

export const mcpApi = {
  /**
   * List effective MCP clients (global + user merged)
   */
  listMCPClients: () => request<MCPClientInfo[]>("/mcp"),

  /**
   * List global MCP pool (admin-configured)
   */
  listGlobalMCPClients: () => request<MCPClientInfo[]>("/mcp/global"),

  /**
   * Get details of a specific MCP client
   */
  getMCPClient: (clientKey: string) =>
    request<MCPClientInfo>(`/mcp/${encodeURIComponent(clientKey)}`),

  /**
   * Create a new MCP client (personal)
   */
  createMCPClient: (body: MCPClientCreateRequest) =>
    request<MCPClientInfo>("/mcp", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  /**
   * Create a global MCP client (admin only)
   */
  createGlobalMCPClient: (body: MCPClientCreateRequest) =>
    request<MCPClientInfo>("/mcp/global", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  /**
   * Update an existing MCP client
   */
  updateMCPClient: (clientKey: string, body: MCPClientUpdateRequest) =>
    request<MCPClientInfo>(`/mcp/${encodeURIComponent(clientKey)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  /**
   * Toggle MCP client enabled status
   */
  toggleMCPClient: (clientKey: string) =>
    request<MCPClientInfo>(`/mcp/${encodeURIComponent(clientKey)}/toggle`, {
      method: "PATCH",
    }),

  /**
   * Delete a personal MCP client
   */
  deleteMCPClient: (clientKey: string) =>
    request<{ message: string }>(`/mcp/${encodeURIComponent(clientKey)}`, {
      method: "DELETE",
    }),

  /**
   * Delete a global MCP client (admin only)
   */
  deleteGlobalMCPClient: (clientKey: string) =>
    request<{ message: string }>(
      `/mcp/global/${encodeURIComponent(clientKey)}`,
      { method: "DELETE" },
    ),

  /**
   * List tools from a connected MCP server
   */
  listMCPTools: (clientKey: string) =>
    request<MCPToolInfo[]>(`/mcp/${encodeURIComponent(clientKey)}/tools`),
};
