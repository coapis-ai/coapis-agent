/**
 * MCP (Model Context Protocol) client types
 */

export interface MCPClientOAuthStatus {
  authorized: boolean;
  expires_at: number;
  scope: string;
  client_id: string;
}

export interface MCPAccessSummary {
  default_effect: "allow" | "ask" | "deny";
  overrides_count: number;
}

export interface MCPClientInfo {
  /** Unique client key identifier */
  key: string;
  /** Client display name */
  name: string;
  /** Client description */
  description: string;
  /** Whether the client is enabled */
  enabled: boolean;
  /** MCP transport type */
  transport: "stdio" | "streamable_http" | "sse";
  /** Remote MCP endpoint URL for HTTP/SSE transport */
  url: string;
  /** HTTP headers for remote transport */
  headers: Record<string, string>;
  /** Command to launch the MCP server */
  command: string;
  /** Command-line arguments */
  args: string[];
  /** Environment variables */
  env: Record<string, string>;
  /** Working directory for stdio command */
  cwd: string;
  /** Configuration source: 'global' (from admin) or 'user' (personal) */
  source: "global" | "user";
  /** Tool whitelist. Only listed tools will be loaded. */
  tools?: string[] | null;
  /** OAuth status */
  oauth_status?: MCPClientOAuthStatus | null;
  /** Summarised MCP access policy */
  access_summary: MCPAccessSummary;
}

export interface MCPClientCreateRequest {
  /** Unique client key identifier */
  client_key: string;
  /** Client configuration */
  client: {
    /** Client display name */
    name: string;
    /** Client description */
    description?: string;
    /** Whether to enable the client */
    enabled?: boolean;
    /** MCP transport type */
    transport?: "stdio" | "streamable_http" | "sse";
    /** Remote MCP endpoint URL for HTTP/SSE transport */
    url?: string;
    /** HTTP headers for remote transport */
    headers?: Record<string, string>;
    /** Command to launch the MCP server */
    command?: string;
    /** Command-line arguments */
    args?: string[];
    /** Environment variables */
    env?: Record<string, string>;
    /** Working directory for stdio command */
    cwd?: string;
    /** Tool whitelist. Only listed tools will be loaded. */
    tools?: string[] | null;
  };
}

export interface MCPToolInfo {
  /** Tool name */
  name: string;
  /** Tool description */
  description: string;
  /** JSON Schema for the tool's input parameters */
  input_schema: Record<string, unknown>;
}

export interface MCPClientUpdateRequest {
  /** Client display name */
  name?: string;
  /** Client description */
  description?: string;
  /** Whether to enable the client */
  enabled?: boolean;
  /** MCP transport type */
  transport?: "stdio" | "streamable_http" | "sse";
  /** Remote MCP endpoint URL for HTTP/SSE transport */
  url?: string;
  /** HTTP headers for remote transport */
  headers?: Record<string, string>;
  /** Command to launch the MCP server */
  command?: string;
  /** Command-line arguments */
  args?: string[];
  /** Environment variables */
  env?: Record<string, string>;
  /** Working directory for stdio command */
  cwd?: string;
  /** Tool whitelist (omit to leave unchanged). Set to null to remove. */
  tools?: string[] | null;
}

export interface MCPAccessRule {
  source_type: "channel" | "role" | "user";
  source_value: string;
  subject_type: "all" | "user" | "role";
  subject_value: string;
  effect: "allow" | "ask" | "deny";
}

export interface MCPToolDefaultPolicy {
  tool_name: string;
  effect: "allow" | "ask" | "deny";
}

export interface MCPToolAccessOverride extends MCPAccessRule {
  tool_name: string;
}

export interface MCPAccessPolicy {
  default_effect: "allow" | "ask" | "deny";
  client_overrides: MCPAccessRule[];
  tool_defaults: MCPToolDefaultPolicy[];
  tool_overrides: MCPToolAccessOverride[];
  unmanaged_rules_count: number;
}

export interface MCPInstallRequest {
  /** Package name (e.g. 'mcp-server-time') */
  package: string;
  /** Package manager type */
  install_type: "pip" | "npm";
}

export interface MCPInstallResponse {
  /** Installation result status */
  status: "success" | "error" | "already_installed";
  /** Result message */
  message: string;
  /** Package name */
  package: string;
  /** Install type used */
  install_type: string;
}
