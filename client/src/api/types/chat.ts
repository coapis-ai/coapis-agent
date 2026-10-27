export type ChatStatus = "idle" | "running";

export interface ChatSpec {
  id: string; // Chat UUID identifier
  session_id: string; // Session identifier (channel:user_id format)
  user_id: string; // User identifier
  channel: string; // Channel name, default: "default"
  name?: string; // Chat display name
  created_at: string | null; // Chat creation timestamp (ISO 8601)
  updated_at: string | null; // Chat last update timestamp (ISO 8601)
  meta?: Record<string, unknown>; // Additional metadata
  status?: ChatStatus; // Conversation status: idle or running
  pinned?: boolean; // Whether the chat is pinned to the top
  agent_id?: string; // Agent ID for multi-agent isolation
  generating?: boolean; // Whether this chat is currently being processed (e.g. from another channel)
  /** 批次 A4：短标题（首条 user 消息前 40 字）。列表行优先显示它，
      没有它时回退 name —— 未命名会话不再整列「新聊天」。 */
  title?: string;
  /** 批次 A1：索引条目对应的会话文件是否存在（后端实测，非猜测）。 */
  session_exists?: boolean;
}

export interface Message {
  role: string;
  content: unknown;
  [key: string]: unknown;
}

export interface ChatHistory {
  messages: Message[];
  status?: ChatStatus; // Conversation status: idle or running
  /** 批次 A2：索引里有这条会话，但会话文件不存在（空壳/迁移遗留）。
      前端据此给出解释，而不是丢一个空白页。 */
  session_missing?: boolean;
}

/** 分页会话列表信封（B5 GET /chats/page）。 */
export interface ChatSpecPage {
  items: ChatSpec[];
  total: number; // 过滤后的全量条数
  offset: number;
  limit: number;
  has_more: boolean;
}

export interface ChatUpdateRequest {
  name?: string;
  pinned?: boolean;
}

export interface ChatDeleteResponse {
  success: boolean;
  chat_id: string;
}

// Legacy Session type alias for backward compatibility
export type Session = ChatSpec;
