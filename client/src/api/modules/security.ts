import { request } from "../request";

export interface ToolGuardRule {
  id: string;
  tools?: string[];
  params?: string[];
  category: string;
  severity: string;
  patterns: string[];
  exclude_patterns?: string[];
  description: string;
  remediation?: string;
}

export interface ToolGuardConfig {
  enabled: boolean;
  guarded_tools: string[] | null;
  denied_tools: string[];
  custom_rules: ToolGuardRule[];
  disabled_rules: string[];
  shell_evasion_checks: Record<string, boolean>;
}

// ── File Guard types ──────────────────────────────────────────────

export interface FileGuardResponse {
  enabled: boolean;
  paths: string[];
}

export interface FileGuardUpdateBody {
  enabled?: boolean;
  paths?: string[];
}

// ── Skill Scanner types ────────────────────────────────────────────

export interface SkillScannerWhitelistEntry {
  skill_name: string;
  content_hash: string;
  added_at: string;
}

export type SkillScannerMode = "block" | "warn" | "off";

export interface SkillScannerConfig {
  mode: SkillScannerMode;
  timeout: number;
  whitelist: SkillScannerWhitelistEntry[];
}

export interface BlockedSkillFinding {
  severity: string;
  title: string;
  description: string;
  file_path: string;
  line_number: number | null;
  rule_id: string;
}

export interface BlockedSkillRecord {
  skill_name: string;
  blocked_at: string;
  max_severity: string;
  findings: BlockedSkillFinding[];
  content_hash: string;
  action: "blocked" | "warned";
}

export interface SecurityScanErrorResponse {
  type: "security_scan_failed";
  detail: string;
  skill_name: string;
  max_severity: string;
  findings: BlockedSkillFinding[];
}

// ── Allow No Auth Hosts types ──────────────────────────────────────

export interface AllowNoAuthHostsResponse {
  hosts: string[];
}

export interface AllowNoAuthHostsUpdateBody {
  hosts: string[];
}

// ── Input Guard types ─────────────────────────────────────────────

export interface InputGuardRule {
  id: string;
  category: string;
  severity: string;
  patterns: string[];
  description: string;
}

export interface InputGuardTestResult {
  is_safe: boolean;
  max_severity: string;
  findings: InputGuardFinding[];
}

export interface InputGuardFinding {
  id: string;
  rule_id: string;
  category: string;
  severity: string;
  title: string;
  description: string;
  matched_pattern: string | null;
  snippet: string | null;
}

// ── Shell Guard types ─────────────────────────────────────────────

export interface ShellRule {
  id: string;
  tools?: string[];
  params?: string[];
  category: string;
  severity: string;
  patterns: string[];
  exclude_patterns?: string[];
  description: string;
  remediation?: string;
  // UI extension fields (used by RuleTable)
  disabled?: boolean;
  source?: "builtin" | "custom";
}

export const securityApi = {
  // ── Tool Guard ──────────────────────────────────────────────────

  getToolGuard: () => request<ToolGuardConfig>("/config/security/tool-guard"),

  updateToolGuard: (body: ToolGuardConfig) =>
    request<ToolGuardConfig>("/config/security/tool-guard", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  getBuiltinRules: () =>
    request<ToolGuardRule[]>("/config/security/tool-guard/builtin-rules"),

  // ── File Guard ─────────────────────────────────────────────────

  getFileGuard: () => request<FileGuardResponse>("/config/security/file-guard"),

  updateFileGuard: (body: FileGuardUpdateBody) =>
    request<FileGuardResponse>("/config/security/file-guard", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  // ── Skill Scanner ───────────────────────────────────────────────

  getSkillScanner: () =>
    request<SkillScannerConfig>("/config/security/skill-scanner"),

  updateSkillScanner: (body: SkillScannerConfig) =>
    request<SkillScannerConfig>("/config/security/skill-scanner", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  getBlockedHistory: () =>
    request<BlockedSkillRecord[]>(
      "/config/security/skill-scanner/blocked-history",
    ),

  clearBlockedHistory: () =>
    request<{ cleared: boolean }>(
      "/config/security/skill-scanner/blocked-history",
      { method: "DELETE" },
    ),

  removeBlockedEntry: (index: number) =>
    request<{ removed: boolean }>(
      `/config/security/skill-scanner/blocked-history/${index}`,
      { method: "DELETE" },
    ),

  addToWhitelist: (skillName: string, contentHash: string = "") =>
    request<{ whitelisted: boolean; skill_name: string }>(
      "/config/security/skill-scanner/whitelist",
      {
        method: "POST",
        body: JSON.stringify({
          skill_name: skillName,
          content_hash: contentHash,
        }),
      },
    ),

  removeFromWhitelist: (skillName: string) =>
    request<{ removed: boolean; skill_name: string }>(
      `/config/security/skill-scanner/whitelist/${encodeURIComponent(
        skillName,
      )}`,
      { method: "DELETE" },
    ),

  // ── Allow No Auth Hosts ─────────────────────────────────────────

  getAllowNoAuthHosts: () =>
    request<AllowNoAuthHostsResponse>("/config/security/allow-no-auth-hosts"),

  updateAllowNoAuthHosts: (body: AllowNoAuthHostsUpdateBody) =>
    request<AllowNoAuthHostsResponse>("/config/security/allow-no-auth-hosts", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  // ── Input Guard ─────────────────────────────────────────────────

  getInputGuardRules: () =>
    request<InputGuardRule[]>("/input-guard/rules"),

  getInputGuardRule: (ruleId: string) =>
    request<InputGuardRule>(`/input-guard/rules/${encodeURIComponent(ruleId)}`),

  addInputGuardRule: (body: InputGuardRule) =>
    request<InputGuardRule>("/input-guard/rules", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  updateInputGuardRule: (ruleId: string, body: InputGuardRule) =>
    request<InputGuardRule>(`/input-guard/rules/${encodeURIComponent(ruleId)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  deleteInputGuardRule: (ruleId: string) =>
    request<{ status: string; id: string }>(
      `/input-guard/rules/${encodeURIComponent(ruleId)}`,
      { method: "DELETE" },
    ),

  testInputGuardText: (text: string) =>
    request<InputGuardTestResult>("/input-guard/test", {
      method: "POST",
      body: JSON.stringify({ text }),
    }),

  reloadInputGuardRules: () =>
    request<{ status: string; rule_count: number }>("/input-guard/reload", {
      method: "POST",
    }),

  // ── Shell Guard ──────────────────────────────────────────────────

  getShellGuardRules: () =>
    request<ShellRule[]>("/config/security/shell-guard/rules"),

  getShellEvasionChecks: () =>
    request<{ evasion_checks: Record<string, boolean> }>(
      "/config/security/shell-guard/evasion-checks",
    ),

  updateShellEvasionChecks: (checks: Record<string, boolean>) =>
    request<{ evasion_checks: Record<string, boolean> }>(
      "/config/security/shell-guard/evasion-checks",
      {
        method: "PUT",
        body: JSON.stringify(checks),
      },
    ),

  getShellGuardConfig: () =>
    request<{ rules_count: number; evasion_checks: Record<string, boolean> }>(
      "/config/security/shell-guard/config",
    ),

  // ── Unified Tool Guard (new) ────────────────────────────────────

  getUnifiedToolGuardConfig: () =>
    request<{
      version: string;
      description: string;
      access_control: Record<string, any>;
      commands_count: number;
      global_rules_count: number;
      evasion_checks: Record<string, boolean>;
    }>("/config/security/tool-guard/config"),

  getUnifiedCommands: () =>
    request<Record<string, { level: string; desc: string; action: string }>>(
      "/config/security/tool-guard/commands",
    ),

  getGlobalRules: () =>
    request<ShellRule[]>("/config/security/tool-guard/global-rules"),

  getUnifiedEvasionChecks: () =>
    request<{ evasion_checks: Record<string, boolean> }>(
      "/config/security/tool-guard/evasion-checks",
    ),

  updateUnifiedEvasionChecks: (checks: Record<string, boolean>) =>
    request<{ evasion_checks: Record<string, boolean> }>(
      "/config/security/tool-guard/evasion-checks",
      {
        method: "PUT",
        body: JSON.stringify({ evasion_checks: checks }),
      },
    ),

  testUnifiedCommand: (command: string) =>
    request<{
      action: string;
      level: string | null;
      command: string | null;
      matched_rules: Array<{
        id: string;
        severity: string;
        category: string;
        description: string;
        action: string;
        matched_text: string;
      }>;
      evasion_flags: Array<{
        id: string;
        severity: string;
        description: string;
      }>;
      reason: string;
      duration_ms: number;
    }>("/config/security/tool-guard/test", {
      method: "POST",
      body: JSON.stringify({ command }),
    }),

  updateSingleCommand: (
    cmdName: string,
    body: { level?: string; action?: string; desc?: string },
  ) =>
    request<{ level: string; desc: string; action: string }>(
      `/config/security/tool-guard/commands/${encodeURIComponent(cmdName)}`,
      {
        method: "PUT",
        body: JSON.stringify(body),
      },
    ),
};
