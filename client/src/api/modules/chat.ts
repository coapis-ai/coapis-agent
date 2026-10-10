import { request } from "../request";
import { getApiUrl, getApiToken } from "../config";
import { buildAuthHeaders } from "../authHeaders";
import type {
  ChatSpec,
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

export const chatApi = {
  /** Upload a file for chat attachment. Returns URL path for content. */
  uploadFile: async (
    file: File,
    chatId?: string,
    sessionId?: string,
  ): Promise<ChatUploadResponse> => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("path", "media");
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
