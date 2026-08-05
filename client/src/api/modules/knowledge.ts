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

// ── RAG Configuration Types (Enterprise Edition) ──────────────

export interface ChunkingStrategy {
  splitter_type: 'recursive_character' | 'markdown_header' | 'token';
  chunk_size?: number;
  chunk_overlap?: number;
  separators?: string[];
}

export interface RetrievalConfig {
  enable_hybrid_search: boolean;
  use_parent_document_retriever: boolean;
}

export interface KnowledgeBaseConfig {
  embedding_model_provider: string;
  embedding_model_name: string;
  chunking_strategy: ChunkingStrategy;
  retrieval_config: RetrievalConfig;
}

// Model Provider types for UI selection
export interface ModelProvider {
  provider_id: string;
  name: string;
  models?: Array<{ model_id: string; name: string }>;
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

  // ── RAG Configuration & Models (Enterprise Edition) ──

  getModels: () =>
    request<Array<ModelProvider | { provider_id: string; name: string }>>("/api/models"),

  createBaseWithConfig: (data: {
    name: string;
    description?: string;
    scope?: string;
    config: KnowledgeBaseConfig;
  }) => {
    const form = new FormData();
    form.append("name", data.name);
    if (data.description) form.append("description", data.description);
    if (data.scope) form.append("scope", data.scope);
    // Append config as JSON string
    form.append("config", JSON.stringify(data.config));
    
    return request<KnowledgeBase>("/knowledge/bases", {
      method: "POST",
      body: form,
      headers: {} as HeadersInit,
    });
  },

  updateBaseConfig: (kbId: string, config: KnowledgeBaseConfig) =>
    request<{ success: boolean }>(`/knowledge/bases/${encodeURIComponent(kbId)}/config`, {
      method: "PUT",
      body: JSON.stringify({ config }),
    }),

  // ── RAG Test / QA ──

  testRagQuery: (kbIds: string[], query: string, top_k?: number) =>
    request<{ 
      answer: string; 
      sources: Array<{ chunk_id: string; text: string; source_title: string; score: number }>;
    }>("/knowledge/rag/test", {
      method: "POST",
      body: JSON.stringify({ kb_ids: kbIds, query, top_k }),
    }),
};
