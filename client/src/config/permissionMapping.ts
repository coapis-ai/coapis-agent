/**
 * 权限模块映射配置
 * 
 * 前端菜单 key → 后端权限模块 key
 * 
 * 权限模块列表（来自 permissions.json）：
 * - chat, skills, models, agents, admin, system, audit, token_usage
 * - cron, heartbeat, channels, config, workspace, myspace, security
 * - backups, debug, evolution, knowledge, user_system, sessions, files
 */

/**
 * 前端菜单 key → 后端权限模块 key 映射
 */
export const MENU_TO_PERMISSION_MODULE: Record<string, string> = {
  // ── 主菜单（社区版）──
  // 主菜单项不涉及权限，对所有用户开放，不在此映射中
  // 'chat': 'chat',        // 主菜单，所有用户可见
  // 'workbench': 'chat',   // 主菜单，所有用户可见
  // 'my-scenes': 'chat',   // 主菜单，所有用户可见
  // 'myspace': 'myspace',  // 主菜单，所有用户可见
  // 'settings': 'config',  // ❌ 设置是主菜单，所有用户可见，不应映射权限

  // ── 用户管理（用户级功能）──
  'agents': 'agents',
  'channels': 'channels',
  'sessions': 'sessions',
  'cron-jobs': 'cron',
  'heartbeat': 'heartbeat',
  'skills': 'skills',
  'tools': 'skills',  // 工具 = 技能权限
  'mcp': 'skills',    // MCP = 技能权限
  'token-usage': 'token_usage',
  'backups': 'backups',

  // ── 系统管理（系统级功能）──
  'overview': 'admin',       // 概览
  'users': 'admin',          // 用户管理
  'permissions': 'admin',    // 权限管理
  'audit': 'audit',          // 审计日志
  'config': 'system',        // 系统配置
  'scenes': 'admin',         // 场景管理
  'tags': 'admin',           // 标签管理

  // ── 其他功能 ──
  'models': 'models',
  'security': 'security',
  'debug': 'debug',
  'evolution': 'evolution',
  'knowledge': 'knowledge',
  'user-system': 'user_system',
  'agent-config': 'agents',
  'agent-stats': 'agents',
  'voice-transcription': 'agents',
};

/**
 * 检查菜单 key 是否需要权限
 * 
 * @param menuKey 前端菜单 key
 * @returns 是否需要权限检查
 */
export function requiresPermission(menuKey: string): boolean {
  return menuKey in MENU_TO_PERMISSION_MODULE;
}

/**
 * 获取菜单 key 对应的权限模块 key
 * 
 * @param menuKey 前端菜单 key
 * @returns 权限模块 key，如果不需要权限则返回 null
 */
export function getPermissionModule(menuKey: string): string | null {
  return MENU_TO_PERMISSION_MODULE[menuKey] || null;
}
