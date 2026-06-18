import { api } from '../index';

/**
 * Admin Provider Management API
 * 管理员配置全局 Provider 和可用模型池
 */
export const adminProvidersApi = {
  /**
   * Get all providers (admin only)
   */
  getAllProviders: () =>
    api.get('/admin/providers').then((res: any) => res.data || res),

  /**
   * Get available models pool (admin only)
   */
  getAvailableModels: () =>
    api.get('/admin/providers/models').then((res: any) => res.data || res),

  /**
   * Create a new provider (admin only)
   */
  createProvider: (data: {
    id: string;
    name: string;
    api_base: string;
    api_key: string;
    models: string[];
    enabled: boolean;
    visible_to_users: boolean;
    visible_models: string[];
  }) =>
    api.post('/admin/providers', data).then((res: any) => res.data || res),

  /**
   * Update provider (admin only, partial update)
   */
  updateProvider: (providerId: string, data: Partial<{
    name: string;
    api_base: string;
    api_key: string;
    models: string[];
    enabled: boolean;
    visible_to_users: boolean;
    visible_models: string[];
  }>) =>
    api.put(`/admin/providers/${providerId}`, data).then((res: any) => res.data || res),

  /**
   * Delete provider (admin only)
   */
  deleteProvider: (providerId: string) =>
    api.delete(`/admin/providers/${providerId}`).then((res: any) => res.data || res),

  /**
   * Test provider connection (admin only)
   */
  testProviderConnection: (data: {
    provider_id: string;
    api_base: string;
    api_key: string;
    model: string;
  }) =>
    api.post('/admin/providers/test', data).then((res: any) => res.data || res),
};

export default adminProvidersApi;
