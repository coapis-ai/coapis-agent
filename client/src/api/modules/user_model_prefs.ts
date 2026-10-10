import { api } from '../index';

/**
 * User Model Preferences API
 * 用户模型偏好设置（用户全局，不分智能体/场景）。
 *
 * 模型以 (provider_id, model) 成对存储：同名模型可能来自不同 provider
 * （如 dev 环境 a3/A3 与 local3-new/A3），只存模型名会选错 provider。
 */
export interface UserModelPrefs {
  username: string;
  default_model: string | null;
  default_provider_id: string | null;
  language: string;
}

/** 偏好更新字段：空字符串 = 清除该项（回退系统默认） */
export interface ModelPrefsUpdate {
  default_model?: string;
  default_provider_id?: string;
}

export const userModelPrefsApi = {
  /** 可用模型池（带 model_type，可按类型过滤） */
  getAvailableModels: (types?: string) =>
    api.get(
      types
        ? `/models/available?types=${encodeURIComponent(types)}`
        : '/models/available',
    ).then((res: any) => res.data || res),

  getModelPrefs: (): Promise<UserModelPrefs> =>
    api.get('/user/model-prefs').then((res: any) => res.data || res),

  /** 部分更新；后端对聊天模型变更会热重载智能体 */
  updateModelPrefs: (data: ModelPrefsUpdate) =>
    api.put('/user/model-prefs', data).then((res: any) => res.data || res),
};

export default userModelPrefsApi;
