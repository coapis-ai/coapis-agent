import { api } from '../index';

/**
 * User Model Preferences API
 * 用户模型偏好设置 — 选择默认模型和排序
 */
export const userModelPrefsApi = {
  /**
   * Get available models for current user
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
    language?: string;
  }) =>
    api.put('/user/model-prefs', data).then((res: any) => res.data || res),
};

export default userModelPrefsApi;
