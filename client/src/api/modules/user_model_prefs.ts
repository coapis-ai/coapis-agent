import { api } from '../index';

/**
 * User Model Preferences API
 * 用户模型偏好设置 — 普通用户选择默认模型，高级用户可添加自定义 Provider
 */
export const userModelPrefsApi = {
  /**
   * Get available models for current user (global + custom)
   */
  getAvailableModels: () =>
    api.get('/models/available').then((res: any) => res.data || res),

  /**
   * Get user model preferences
   */
  getModelPrefs: () =>
    api.get('/user/model-prefs').then((res: any) => res.data || res),

  /**
   * Update user model preferences (partial update)
   */
  updateModelPrefs: (data: {
    default_model?: string;
    model_priority?: string[];
    custom_providers?: any[];
    language?: string;
  }) =>
    api.put('/user/model-prefs', data).then((res: any) => res.data || res),

  /**
   * Get user custom providers
   */
  getCustomProviders: () =>
    api.get('/user/custom-providers').then((res: any) => res.data || res),

  /**
   * Create custom provider
   */
  createCustomProvider: (data: {
    id: string;
    name: string;
    api_base: string;
    api_key: string;
    models: string[];
    enabled: boolean;
  }) =>
    api.post('/user/custom-providers', data).then((res: any) => res.data || res),

  /**
   * Update custom provider
   */
  updateCustomProvider: (providerId: string, data: {
    id: string;
    name: string;
    api_base: string;
    api_key: string;
    models: string[];
    enabled: boolean;
  }) =>
    api.put(`/user/custom-providers/${providerId}`, data).then((res: any) => res.data || res),

  /**
   * Delete custom provider
   */
  deleteCustomProvider: (providerId: string) =>
    api.delete(`/user/custom-providers/${providerId}`).then((res: any) => res.data || res),

  /**
   * Test custom provider connection
   */
  testCustomProvider: (data: {
    id: string;
    api_base: string;
    api_key: string;
    models: string[];
  }) =>
    api.post('/user/custom-providers/test', data).then((res: any) => res.data || res),
};

export default userModelPrefsApi;
