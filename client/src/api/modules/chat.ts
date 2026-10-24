import { request } from "../request";
import { getApiUrl, getApiToken } from "../config";
import { buildAuthHeaders } from "../authHeaders";
import type {
  ChatSpec,
  ChatSpecPage,
  ChatHistory,
  ChatDeleteResponse,
  ChatUpdateRequest,
  Session,
} from "../types";

/** Response from POST /console/upload. url = filename only; agent_id from header. */
export interface ChatUploadResponse {
  url: string;
  file_name: string;
  stored_name?: string;
}

const FILES_PREVIEW = "/files/preview";

/** 会话资源条目（B2 读接口 GET /chats/{id}/resources 的元素）。 */
export interface ChatResourceItem {
  resource_key?: string;
  kind: "file" | "web" | "kb" | "mcp" | "db";
  /** file → 工作区相对路径（files/x.md）；web → URL */
  path: string;
  title: string;
  role: "producer" | "reference" | "attachment" | "export";
  ref_count?: number;
  status?: string;
  updated_at?: number | string;
  last_seen_at?: number;
  size?: number | null;
  exists?: boolean;
  /** 交付版本号：首次=1，内容（大小）变了才 +1 */
  version?: number;
  /** 台账软删标记（灰显「已删除」） */
  deleted?: boolean;
  /** 产出这条资源的那条消息 id（L2「定位到消息」用；引用类没有） */
  messageId?: string;
}

export interface ChatResourceList {
  items: ChatResourceItem[];
  total: number;
  offset: number;
  limit: number;
}

/** 在途的会话资源请求（批次 B4 并发合并用），落地即摘除 */
const resourceInflight = new Map<string, Promise<ChatResourceList>>();

export const chatApi = {
  /**
   * 会话资源清单（权威源=资源台账，刷新后仍可还原）。
   *
   * 批次 B4：切一次会话，顶栏(L1)、左栏资源条(L2)、资源抽屉(L3)会同时来要
   * 同一份清单 —— 各发一次就是 3 个请求。这里做**并发合并**：同一
   * (chatId, limit, offset) 在途时复用同一个 Promise，请求落地即从表里摘除，
   * 所以只省掉同时发生的重复，不会把旧数据当新数据用（无陈旧风险）。
   */
  listChatResources: (
    chatId: string,
    limit = 200,
    offset = 0,
  ): Promise<ChatResourceList> => {
    const key = `${chatId}|${limit}|${offset}`;
    const inflight = resourceInflight.get(key);
    if (inflight) return inflight;
    const req = request<ChatResourceList>(
      `/chats/${encodeURIComponent(chatId)}/resources?limit=${limit}&offset=${offset}`,
    );
    const paged = req.then(
      (res) => {
        resourceInflight.delete(key);
        return res;
      },
      (err) => {
        resourceInflight.delete(key);
        throw err;
      },
    );
    resourceInflight.set(key, paged);
    return paged;
  },

  /** Upload a file for chat attachment. Returns URL path for content. */
  uploadFile: async (
    file: File,
    chatId?: string,
    sessionId?: string,
  ): Promise<ChatUploadResponse> => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("path", "media");
    // 同名即更新：用户空间内的重复上传是「更新这个文件」，不是冲突
    formData.append("overwrite", "true");
    // 聊天 UUID：后端写入文件台账的 chat_id，"本会话文件"过滤依赖它
    if (chatId) formData.append("chat_id", chatId);
    // 本地会话 id：新会话建号前上传时 chat_id 为空，靠它事后补写
    if (sessionId) formData.append("session_id", sessionId);
    const response = await fetch(getApiUrl("/myfiles/upload"), {
      method: "POST",
      headers: buildAuthHeaders(),
      body: formData,
    });
    if (!response.ok) {
      const text = await response.text().catch(() => "");
      throw new Error(
        `Upload failed: ${response.status} ${response.statusText}${
          text ? ` - ${response.statusText}` : ""
        }`,
      );
    }
    return response.json();
  },

  /** 把建会话前上传的台账行补写 chat_id（只改 chat_id 为空的行）。 */
  attachChatFiles: async (
    sessionId: string,
    chatId: string,
  ): Promise<{ success: boolean; updated: number }> => {
    const response = await fetch(
      getApiUrl("/myfiles/records/attach-chat"),
      {
        method: "POST",
        headers: buildAuthHeaders(),
        body: JSON.stringify({ session_id: sessionId, chat_id: chatId }),
      },
    );
    if (!response.ok) {
      const text = await response.text().catch(() => "");
      throw new Error(
        `attach-chat failed: ${response.status} ${response.statusText}${
          text ? ` - ${text}` : ""
        }`,
      );
    }
    return response.json();
  },

  filePreviewUrl: (filename: string): string => {
    if (!filename) return "";
    if (filename.startsWith("http://") || filename.startsWith("https://"))
      return filename;
    // Strip any existing /files/preview/ or /api/files/preview/ prefix to
    // avoid double-prefixing when the URL is resolved a second time (e.g.
    // when reloading chat history). See GitHub issue #3600.
    let cleaned = filename.replace(/^\/+/, "");
    // Strip query parameters (e.g. ?token=xxx from previous replaceMediaURL call)
    const qIdx = cleaned.indexOf("?");
    if (qIdx !== -1) cleaned = cleaned.slice(0, qIdx);
    const previewPrefix = FILES_PREVIEW.replace(/^\/+/, "");
    if (cleaned.startsWith(`api/${previewPrefix}/`)) {
      cleaned = cleaned.slice(`api/${previewPrefix}/`.length);
    } else if (cleaned.startsWith(`${previewPrefix}/`)) {
      cleaned = cleaned.slice(`${previewPrefix}/`.length);
    }
    const path = `${FILES_PREVIEW}/${cleaned}`;
    const url = getApiUrl(path);

    const token = getApiToken();
    if (token) {
      return `${url}?token=${encodeURIComponent(token)}`;
    }

    return url;
  },
  listChats: (params?: { user_id?: string; channel?: string; agent_id?: string }) => {
    const searchParams = new URLSearchParams();
    if (params?.user_id) searchParams.append("user_id", params.user_id);
    if (params?.channel) searchParams.append("channel", params.channel);
    if (params?.agent_id) searchParams.append("agent_id", params.agent_id);
    const query = searchParams.toString();
    const headers: Record<string, string> = {};
    if (params?.agent_id) headers["X-Agent-Id"] = params.agent_id;
    return request<ChatSpec[]>(`/chats${query ? `?${query}` : ""}`, { headers });
  },

  /** 左栏分页列表（B5）：首屏只取一页，滚到底再取下一页。
   *  total 是「过滤后的全量条数」，不是本页条数。 */
  listChatsPage: (params: {
    offset?: number;
    limit?: number;
    channel?: string;
    agent_id?: string;
  }) => {
    const searchParams = new URLSearchParams();
    searchParams.append("offset", String(params.offset ?? 0));
    searchParams.append("limit", String(params.limit ?? 20));
    if (params.channel) searchParams.append("channel", params.channel);
    if (params.agent_id) searchParams.append("agent_id", params.agent_id);
    const headers: Record<string, string> = {};
    if (params.agent_id) headers["X-Agent-Id"] = params.agent_id;
    return request<ChatSpecPage>(`/chats/page?${searchParams.toString()}`, {
      headers,
    });
  },

  createChat: (chat: Partial<ChatSpec>) =>
    request<ChatSpec>("/chats", {
      method: "POST",
      body: JSON.stringify(chat),
      headers: chat.agent_id ? { "X-Agent-Id": chat.agent_id } : undefined,
    }),

  getChat: (chatId: string, opts?: { limit?: number; before?: string; agent_id?: string }) => {
    const params = new URLSearchParams();
    if (opts?.limit) params.append("limit", String(opts.limit));
    if (opts?.before) params.append("before", opts.before);
    const qs = params.toString();
    const headers: Record<string, string> | undefined = opts?.agent_id 
      ? { "X-Agent-Id": opts.agent_id } 
      : undefined;
    return request<ChatHistory & ChatSpec & { total_count?: number; has_more?: boolean }>(
      `/chats/${encodeURIComponent(chatId)}${qs ? `?${qs}` : ""}`,
      { headers }
    );
  },

  getArchivedMessages: (chatId: string, opts?: { before?: string; limit?: number }) => {
    const params = new URLSearchParams();
    if (opts?.before) params.append("before", opts.before);
    if (opts?.limit) params.append("limit", String(opts.limit));
    const qs = params.toString();
    return request<{ messages: any[]; count: number; has_more: boolean }>(
      `/chats/${encodeURIComponent(chatId)}/archived${qs ? `?${qs}` : ""}`
    );
  },

  updateChat: (chatId: string, chat: ChatUpdateRequest) =>
    request<ChatSpec>(`/chats/${encodeURIComponent(chatId)}`, {
      method: "PUT",
      body: JSON.stringify(chat),
    }),

  deleteChat: (chatId: string) =>
    request<ChatDeleteResponse>(`/chats/${encodeURIComponent(chatId)}`, {
      method: "DELETE",
    }),

  batchDeleteChats: (chatIds: string[]) =>
    request<{ success: boolean; deleted_count: number }>(
      "/chats/batch-delete",
      {
        method: "POST",
        body: JSON.stringify(chatIds),
      },
    ),

  stopChat: (chatId: string) =>
    request<void>(`/console/chat/stop?chat_id=${encodeURIComponent(chatId)}`, {
      method: "POST",
    }),
};

export const sessionApi = {
  listSessions: (params?: { user_id?: string; channel?: string; agent_id?: string }) => {
    const searchParams = new URLSearchParams();
    if (params?.user_id) searchParams.append("user_id", params.user_id);
    if (params?.channel) searchParams.append("channel", params.channel);
    if (params?.agent_id) searchParams.append("agent_id", params.agent_id);
    const query = searchParams.toString();
    const headers: Record<string, string> = {};
    if (params?.agent_id) headers["X-Agent-Id"] = params.agent_id;
    return request<Session[]>(`/chats${query ? `?${query}` : ""}`, { headers });
  },

  getSession: (sessionId: string) =>
    request<ChatHistory>(`/chats/${encodeURIComponent(sessionId)}`),

  deleteSession: (sessionId: string) =>
    request<ChatDeleteResponse>(`/chats/${encodeURIComponent(sessionId)}`, {
      method: "DELETE",
    }),

  createSession: (session: Partial<Session>) =>
    request<Session>("/chats", {
      method: "POST",
      body: JSON.stringify(session),
    }),

  updateSession: (sessionId: string, session: ChatUpdateRequest) =>
    request<Session>(`/chats/${encodeURIComponent(sessionId)}`, {
      method: "PUT",
      body: JSON.stringify(session),
    }),

  batchDeleteSessions: (sessionIds: string[]) =>
    request<{ success: boolean; deleted_count: number }>(
      "/chats/batch-delete",
      {
        method: "POST",
        body: JSON.stringify(sessionIds),
      },
    ),
};
