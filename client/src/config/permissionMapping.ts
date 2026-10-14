/**
 * 权限模块映射配置
 *
 * 前端菜单 key → 后端权限模块 key
 *
 * ⚠️ 模块名必须与后端 `require_permission("<module>:<action>")` 用的名字逐字一致。
 *    后端 `has_permission()` 对不存在的模块名直接拒绝（默认拒绝、不报错），
 *    所以这里写错一个字符 = 该菜单对非管理员静默消失。
 *
 * 后端权限模块（kebab-case，共 19 个，见 data/packs/base/auth/permissions.json）：
 *   acp, admin, agents, audit, backups, channels, chat, cron-jobs, debug,
 *   evolution, heartbeat, mcp, models, profile, scene, security, skills,
 *   tag, tools
 *
 * 历史坑（2026-10 修掉）：
 *  - 'cron' / 'token_usage' 是 snake_case 幽灵名，后端不存在；
 *  - 'tools' / 'mcp' / 'scenes' / 'tags' / 'agent-config' / 'agent-stats' /
 *    'voice-transcription' 曾统一挂靠 'skills' / 'admin' / 'agents'，导致前端
 *    显示判定与后端门禁判定分属两个模块（后端收紧权限，前端不跟着变）；
 *  - 'agent-config' / 'agent-stats' / 'sessions' / 'skill-pool' / 'system' /
 *    'token-usage' / 'voice-transcription' / 'myspace' 这 8 个模块后端**没有任何
 *    路由**使用（权限键纯前端自造），已从矩阵删除并在此重映射到真实模块 ——
 *    会话走 chat:*、技能池走 skills:*、Agent 配置/语音走 agents:*、
 *    运行统计/Token 用量走 admin:*、我的空间走所有权快速通道（无权限键）。
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
  'sessions': 'chat',            // 会话路由门在 chat:*（/console/sessions）
  'cron-jobs': 'cron-jobs',
  'heartbeat': 'heartbeat',
  'skills': 'skills',
  'skill-pool': 'skills',        // 技能池路由门在 skills:*（/skills/pool）
  'tools': 'tools',
  'mcp': 'mcp',
  'token-usage': 'admin',        // /token-usage 是 admin:admin
  'backups': 'backups',

  // ── 系统管理（系统级功能）──
  'overview': 'admin',       // 概览
  'users': 'admin',          // 用户管理
  'permissions': 'admin',    // 权限管理
  'admin': 'admin',          // 管理后台
  'audit': 'audit',          // 审计日志
  'config': 'admin',         // 系统配置（原 'system' 模块后端无路由，已删）
  'system-authorization': 'admin',  // 外部系统授权管理（管理功能）
  'scenes': 'scene',         // 场景管理
  'tags': 'tag',             // 标签管理

  // ── 其他功能 ──
  'models': 'models',
  'security': 'security',
  'debug': 'debug',
  'evolution': 'evolution',
  'agent-config': 'agents',        // /agent/* 路由门在 agents:*
  'agent-stats': 'admin',          // /agent-stats 是 admin:admin
  'voice-transcription': 'agents', // 语音转写路由门在 agents:*

  // ── 别名 ──
  // 侧栏折叠态用 'workspace' 表示「我的空间」：主菜单，不受权限门控，
  // 后端对 /api/myspace/* 走所有权快速通道，矩阵里没有 myspace 模块。
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

/**
 * 菜单可见性判定的唯一实现（侧栏与设置页共用，避免两处逻辑漂移）。
 *
 * 规则：
 *  - 不在映射表中 → 不受权限门控，恒可见（主菜单项）
 *  - 在映射表中 → 只看后端返回的允许模块列表
 *
 * 注意：这里刻意**不**用菜单 key 兜底。兜底曾把映射名错的问题掩盖掉
 * （侧栏可见、设置页隐藏），使权限失效无人发现。
 *
 * @param menuKey       前端菜单 key
 * @param allowedModules 后端 /permissions/menu 返回的 modules（admin 为 ["all"]）
 * @param permissionsLoaded 权限是否已加载（加载中先放行，避免闪烁）
 */
export function isMenuKeyAllowed(
  menuKey: string,
  allowedModules: string[],
  permissionsLoaded: boolean,
): boolean {
  if (!permissionsLoaded) return true;          // 加载中放行
  if (allowedModules.includes('all')) return true; // admin
  const permModule = MENU_TO_PERMISSION_MODULE[menuKey];
  if (!permModule) return true;                 // 未纳入权限门控
  return allowedModules.includes(permModule);
}
