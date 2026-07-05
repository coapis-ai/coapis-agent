/**
 * Unified Menu & Permission Module Configuration
 * 
 * SINGLE SOURCE OF TRUTH for all menu items and permission modules.
 * Both sidebar navigation and permission management reference this file.
 * 
 * When adding/removing a menu item, only update MENU_MODULES below.
 */

export interface MenuModuleConfig {
  key: string;
  name: string;           // i18n key suffix: t("nav." + name)
  icon?: string;
  group: 'chat' | 'control' | 'agent' | 'settings';
  permission: boolean;
  order: number;
}

export const MENU_MODULES: MenuModuleConfig[] = [
  // ── Chat (top-level) ──
  { key: 'chat',        name: 'chat',        group: 'chat',     permission: true,  order: 1 },

  // ── Control group ──
  { key: 'channels',    name: 'channels',    group: 'control',  permission: true,  order: 1 },
  { key: 'sessions',    name: 'sessions',    group: 'control',  permission: true,  order: 2 },
  { key: 'cron-jobs',   name: 'cronJobs',    group: 'control',  permission: true,  order: 3 },
  { key: 'heartbeat',   name: 'heartbeat',   group: 'control',  permission: true,  order: 4 },

  // ── Agent group ──
  { key: 'myspace',     name: 'myspace',     group: 'agent',    permission: true,  order: 1 },
  { key: 'skills',      name: 'skills',      group: 'agent',    permission: true,  order: 2 },
  { key: 'tools',       name: 'tools',       group: 'agent',    permission: true,  order: 3 },
  { key: 'mcp',         name: 'mcp',         group: 'agent',    permission: true,  order: 4 },
  // { key: 'acp',         name: 'acp',         group: 'agent',    permission: true,  order: 5 },  // ACP 模块已隐藏 — 2026-06-28
  { key: 'agent-config',name: 'agentConfig', group: 'agent',    permission: true,  order: 6 },
  { key: 'agent-stats', name: 'agentStats',  group: 'agent',    permission: true,  order: 7 },

  // ── Settings group ──
  { key: 'agents',            name: 'agents',            group: 'settings', permission: true,  order: 1 },
  { key: 'models',            name: 'models',            group: 'settings', permission: true,  order: 2 },
  { key: 'skill-pool',        name: 'skillPool',         group: 'settings', permission: true,  order: 3 },
  // { key: 'environments',      name: 'environments',      group: 'settings', permission: true,  order: 4 },
  { key: 'security',          name: 'security',          group: 'settings', permission: true,  order: 5 },
  { key: 'token-usage',       name: 'tokenUsage',        group: 'settings', permission: true,  order: 6 },
  { key: 'backups',           name: 'backupCleanup',     group: 'settings', permission: true,  order: 7 },
  { key: 'voice-transcription', name: 'voiceTranscription', group: 'settings', permission: true,  order: 8 },
  { key: 'evolution',         name: 'evolution',         group: 'settings', permission: true,  order: 9 },
  // { key: 'knowledge',         name: 'knowledge',         group: 'settings', permission: true,  order: 9 },  // 知识库功能暂时隐藏
  { key: 'admin',             name: 'adminPanel',        group: 'settings', permission: true,  order: 10 },
];

/** Get all module keys that require permission checks */
export const PERMISSION_MODULE_KEYS = MENU_MODULES
  .filter(m => m.permission)
  .map(m => m.key);

/** Get modules for a sidebar group, sorted by order */
export function getModulesByGroup(group: MenuModuleConfig['group']): MenuModuleConfig[] {
  return MENU_MODULES
    .filter(m => m.group === group)
    .sort((a, b) => a.order - b.order);
}

/** Sidebar menu key → permission module key (identity map) */
export const MENU_TO_PERMISSION: Record<string, string> = Object.fromEntries(
  MENU_MODULES.filter(m => m.permission).map(m => [m.key, m.key])
);

/** Permission module key → sidebar menu key (identity map) */
export const PERMISSION_TO_MENU: Record<string, string> = Object.fromEntries(
  MENU_MODULES.filter(m => m.permission).map(m => [m.key, m.key])
);
