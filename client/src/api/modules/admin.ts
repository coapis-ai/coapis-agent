import { api } from '../index';

/**
 * Admin API module - system overview, user management, config, audit
 */
export const adminApi = {
  /**
   * Get system overview stats
   */
  getSystemOverview: () =>
    api.get('/admin/system/overview').then((res: any) => res.data || res),

  /**
   * Get all users (admin only)
   */
  listUsers: (page = 1, pageSize = 20, search = '') => {
    const params = new URLSearchParams();
    params.set('page', String(page));
    params.set('page_size', String(pageSize));
    if (search) params.set('search', search);
    return api.get(`/admin/users?${params.toString()}`).then((res: any) => res.data || res);
  },

  /**
   * Get user by username (admin only)
   */
  getUserByUsername: (username: string) =>
    api.get(`/admin/users/${username}`).then((res: any) => res.data || res),

  /**
   * Update user (admin only)
   */
  updateUser: (username: string, data: any) =>
    api.put(`/admin/users/${username}`, data).then((res: any) => res.data || res),

  /**
   * Create user (admin only) - supports role assignment
   */
  createUser: (data: { username: string; password: string; display_name?: string; email?: string; role: string }) =>
    api.post('/admin/users', data).then((res: any) => res.data || res),

  /**
   * Disable user (soft delete - admin only)
   */
  disableUser: (user_id: number) =>
    api.put(`/admin/users/${user_id}`, { is_active: false }).then((res: any) => res.data || res),

  /**
   * Delete user (hard delete - admin only)
   * @param user_id User ID  
   * @param options Delete options
   */
  deleteUser: (user_id: number, options?: { backup?: boolean }) => {
    const body = JSON.stringify(options || {});
    return api.delete(`/admin/users/${user_id}`, {
      body,
      headers: { 'Content-Type': 'application/json' },
    }).then((res: any) => res.data || res);
  },

  /**
   * Get global config
   */
  getGlobalConfig: () =>
    api.get('/admin/config').then((res: any) => res.data || res),

  /**
   * Update global config (admin only)
   */
  updateGlobalConfig: (data: any) =>
    api.put('/admin/config', data).then((res: any) => res.data || res),

  /**
   * Get global audit logs (admin only)
   */
  getAuditLogs: (page = 1, pageSize = 50) => {
    const params = new URLSearchParams();
    params.set('page', String(page));
    params.set('page_size', String(pageSize));
    return api.get(`/admin/audit?${params.toString()}`).then((res: any) => res.data || res);
  },

  // ── 全局模板管理 ───────────────────────────────────────────────
  /**
   * Get all global templates (SOUL.md, MEMORY.md, PROFILE.md)
   */
  getTemplates: () =>
    api.get('/admin/templates').then((res: any) => res.data || res),

  /**
   * Update a global template
   */
  updateTemplate: (filename: string, content: string) =>
    api.put(`/admin/templates/${filename}`, { content }).then((res: any) => res.data || res),

  /**
   * Reset a global template to default
   */
  resetTemplate: (filename: string) =>
    api.post(`/admin/templates/${filename}/reset`).then((res: any) => res.data || res),

  /**
   * Sync global templates to all existing user workspaces
   */
  syncTemplatesToUsers: (strategy: 'new_only' | 'overwrite' = 'new_only', files?: string[]) =>
    api.post('/admin/templates/sync-to-users', { strategy, files }).then((res: any) => res.data || res),

  // ── 全局智能体管理 ─────────────────────────────────────────────
  /**
   * List all global agents
   */
  listGlobalAgents: () =>
    api.get('/admin/global-agents').then((res: any) => res.data || res),

  /**
   * Create a new global agent
   */
  createGlobalAgent: (data: { id: string; name?: string; description?: string; role?: string; priority?: number }) =>
    api.post('/admin/global-agents', data).then((res: any) => res.data || res),

  /**
   * Get global agent details
   */
  getGlobalAgent: (agentId: string) =>
    api.get(`/admin/global-agents/${agentId}`).then((res: any) => res.data || res),

  /**
   * Update global agent config
   */
  updateGlobalAgent: (agentId: string, data: any) =>
    api.put(`/admin/global-agents/${agentId}`, data).then((res: any) => res.data || res),

  /**
   * Delete a global agent
   */
  deleteGlobalAgent: (agentId: string) =>
    api.delete(`/admin/global-agents/${agentId}`).then((res: any) => res.data || res),

  /**
   * Toggle global agent enabled/disabled
   */
  toggleGlobalAgent: (agentId: string, enabled?: boolean) =>
    api.post(`/admin/global-agents/${agentId}/toggle`, enabled !== undefined ? { enabled } : undefined).then((res: any) => res.data || res),

  /**
   * Init global agent identity from templates
   */
  initGlobalAgentIdentity: (agentId: string) =>
    api.post(`/admin/global-agents/${agentId}/init-identity`).then((res: any) => res.data || res),

  /**
   * Get global agent skills list
   */
  listGlobalAgentSkills: (agentId: string) =>
    api.get(`/admin/global-agents/${agentId}/skills`).then((res: any) => res.data || res),

  /**
   * Install skill to global agent
   */
  installSkillToGlobalAgent: (agentId: string, skillName: string) =>
    api.post(`/admin/global-agents/${agentId}/skills/install`, { skill_name: skillName }).then((res: any) => res.data || res),

  /**
   * Uninstall skill from global agent
   */
  uninstallSkillFromGlobalAgent: (agentId: string, skillName: string) =>
    api.post(`/admin/global-agents/${agentId}/skills/uninstall`, { skill_name: skillName }).then((res: any) => res.data || res),

  /**
   * Toggle global agent skill enabled/disabled
   */
  toggleGlobalAgentSkill: (agentId: string, skillName: string, enabled: boolean) =>
    api.put(`/admin/global-agents/${agentId}/skills/${skillName}/toggle`, { enabled }).then((res: any) => res.data || res),

  // ── 系统工具 ───────────────────────────────────────────────────
  /**
   * Scan system directory for stale items
   */
  scanCleanup: () =>
    api.get('/admin/tools/cleanup/scan').then((res: any) => res.data || res),

  /**
   * Execute cleanup
   */
  executeCleanup: (removeDirs: string[]) =>
    api.post('/admin/tools/cleanup/execute', { remove_dirs: removeDirs }).then((res: any) => res.data || res),

  /**
   * System health diagnosis
   */
  systemDiagnose: () =>
    api.get('/admin/tools/diagnose').then((res: any) => res.data || res),

  /**
   * List external agents
   */
  listExternalAgents: () =>
    api.get('/admin/tools/external-agents').then((res: any) => res.data || res),

  /**
   * Toggle external agent enabled/disabled
   */
  toggleExternalAgent: (agentId: string, enabled: boolean) =>
    api.post(`/admin/tools/external-agents/${agentId}/toggle`, { enabled }).then((res: any) => res.data || res),
};

// Export individual functions for direct import
export const {
  getSystemOverview,
  listUsers,
  getUserByUsername,
  createUser,
  updateUser,
  disableUser,
  deleteUser,
  getGlobalConfig,
  updateGlobalConfig,
  getAuditLogs,
  getTemplates,
  updateTemplate,
  resetTemplate,
  listGlobalAgents,
  getGlobalAgent,
  updateGlobalAgent,
  initGlobalAgentIdentity,
  listGlobalAgentSkills,
  installSkillToGlobalAgent,
  uninstallSkillFromGlobalAgent,
  toggleGlobalAgentSkill,
  scanCleanup,
  executeCleanup,
  systemDiagnose,
  listExternalAgents,
  toggleExternalAgent,
} = adminApi;
