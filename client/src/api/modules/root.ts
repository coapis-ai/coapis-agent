import { request } from "../request";

// Root API
export const rootApi = {
  readRoot: () => request<unknown>("/"),
  // edition 由后端回带（真源=COAPIS_EDITION 环境变量）；旧后端可能缺字段，故可选。
  getVersion: () => request<{ version: string; edition?: string }>("/version"),
};
