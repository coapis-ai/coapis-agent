import { request } from "../request";

// ── Types ──────────────────────────────────────────────

export interface KnowledgeBase {
  id: string;
  name: string;
  description: string;
  scope: string;
  status: string;
  chunk_count: number;
  config: Record<string, unknown>;
  created_at: number;
  updated_at: number;
}

export interface KnowledgeDocument {
  id: string;
  kb_id: string;
  title: string;
  source: string;
  content_type: string;
  file_path: string | null;
  chunk_count: number;
  status: string;
  error_msg: string;
  created_at: number;
}

export interface KnowledgeSearchResult {
  chunk_id: string;
  kb_id: string;
  doc_id: string;
  text: string;
  source_title: string;
  score: number;
  category: string;
}

// ── API ────────────────────────────────────────────────

export const knowledgeApi = {
  // ── Knowledge Base CRUD ──

  listBases: (scope?: string) =>
    request<{ bases: KnowledgeBase[]; total: number }>(
      scope ? `/knowledge/bases?scope=${encodeURIComponent(scope)}` : "/knowledge/bases"
    ),

  createBase: (data: { name: string; description?: string; scope?: string }) => {
    const form = new FormData();
    form.append("name", data.name);
    if (data.description) form.append("description", data.description);
    if (data.scope) form.append("scope", data.scope);
    // Use fetch directly for multipart/form-data (request() sets Content-Type)
    return request<KnowledgeBase>("/knowledge/bases", {
      method: "POST",
      body: form,
      headers: {} as HeadersInit, // prevent request() from setting JSON content-type
    });
  },

  getBase: (kbId: string) =>
    request<KnowledgeBase>(`/knowledge/bases/${encodeURIComponent(kbId)}`),

  deleteBase: (kbId: string) =>
    request<{ success: boolean; message: string }>(
      `/knowledge/bases/${encodeURIComponent(kbId)}`,
      { method: "DELETE" }
    ),

  // ── Document Management ──

  listDocuments: (kbId: string) =>
    request<{ documents: KnowledgeDocument[]; total: number }>(
      `/knowledge/bases/${encodeURIComponent(kbId)}/documents`
    ),

  uploadDocument: (kbId: string, file: File, title?: string) => {
    const form = new FormData();
    form.append("file", file);
    if (title) form.append("title", title);
    return request<KnowledgeDocument>(
      `/knowledge/bases/${encodeURIComponent(kbId)}/documents`,
      {
        method: "POST",
        body: form,
        headers: {} as HeadersInit,
      }
    );
  },

  deleteDocument: (docId: string) =>
    request<{ success: boolean; message: string }>(
      `/knowledge/documents/${encodeURIComponent(docId)}`,
      { method: "DELETE" }
    ),

  // ── Search ──

  search: (query: {
    text: string;
    kb_ids?: string[];
    scopes?: string[];
    category?: string;
    limit?: number;
  }) =>
    request<{ results: KnowledgeSearchResult[]; total: number }>("/knowledge/search", {
      method: "POST",
      body: JSON.stringify(query),
    }),

  // ── Health ──

  health: () =>
    request<{ status: string; knowledge_bases: number }>("/knowledge/health"),
};
