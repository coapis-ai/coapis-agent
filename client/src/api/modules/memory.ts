import { request } from "../request";

// ── Types ──────────────────────────────────────────────

/** 知识沉淀条目（后端 /memory/knowledge 返回的扁平结构）。 */
export interface MemoryKnowledgeItem {
  id: number;
  scope: "user" | "workspace" | "agent" | "system" | string;
  user_id: string;
  agent_id: string;
  session_id: string;
  category: string;
  title: string;
  content: string;
  /** 0~1 */
  importance: number;
  /** timeline | user_note | promote_shared | ... */
  source: string;
  /** epoch 秒 */
  created_at: number;
  updated_at: number;
  /** null = 活跃；非空 = 已撤销 */
  deleted_at: number | null;
  archived: boolean;
}

export interface MemoryNoteRequest {
  content: string;
  session_id?: string;
  agent_id?: string;
  category?: string;
}

export interface MemoryNoteResponse {
  ok: boolean;
  id?: number | null;
  detail?: string;
}

export interface MemoryKnowledgeListParams {
  scope?: "user" | "workspace" | "all" | string;
  include_archived?: boolean;
  limit?: number;
  offset?: number;
}

export interface MemoryKnowledgeListResponse {
  ok: boolean;
  items: MemoryKnowledgeItem[];
  total: number;
  stats: Record<string, unknown>;
}

export interface MemoryKnowledgeStateResponse {
  ok: boolean;
  id?: number | null;
  state?: "active" | "revoked" | string;
}

// ── API ────────────────────────────────────────────────

/** 聊天侧「记下来」：把这条内容作为 importance=1.0 的记忆落库。 */
export const createMemoryNote = (body: MemoryNoteRequest) =>
  request<MemoryNoteResponse>("/memory/notes", {
    method: "POST",
    body: JSON.stringify({
      content: body.content,
      session_id: body.session_id ?? "",
      agent_id: body.agent_id ?? "",
      category: body.category ?? "notes",
    }),
  });

/** 知识沉淀列表（含已撤销）。 */
export const listMemoryKnowledge = (params: MemoryKnowledgeListParams = {}) => {
  const search = new URLSearchParams();
  search.set("scope", params.scope ?? "all");
  search.set("include_archived", String(params.include_archived ?? true));
  if (params.limit !== undefined) search.set("limit", String(params.limit));
  if (params.offset !== undefined) search.set("offset", String(params.offset));
  return request<MemoryKnowledgeListResponse>(`/memory/knowledge?${search.toString()}`);
};

/** 撤销一条沉淀（软删）。 */
export const undoMemoryKnowledge = (id: number | string) =>
  request<MemoryKnowledgeStateResponse>(
    `/memory/knowledge/${encodeURIComponent(String(id))}/undo`,
    { method: "POST" },
  );

/** 恢复一条被撤销的沉淀。 */
export const restoreMemoryKnowledge = (id: number | string) =>
  request<MemoryKnowledgeStateResponse>(
    `/memory/knowledge/${encodeURIComponent(String(id))}/restore`,
    { method: "POST" },
  );

export const memoryApi = {
  createMemoryNote,
  listMemoryKnowledge,
  undoMemoryKnowledge,
  restoreMemoryKnowledge,
};
