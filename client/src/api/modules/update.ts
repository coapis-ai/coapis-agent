import { request } from "../request";

/** `/api/updates` 应答（后端 update_api._json_response 的形状） */
export interface UpdateStatus {
  status?: string;
  installed_version?: string;
  has_update?: boolean;
  latest?: {
    version?: string;
    title?: string;
    release_date?: string;
    url?: string;
    notes?: string[];
  };
}

export const updateApi = {
  /** 只读最新版查询；无网络时后端返回 status=offline（前端静默） */
  getLatest: () => request<UpdateStatus>("/updates", { method: "GET" }),
};

export default updateApi;
