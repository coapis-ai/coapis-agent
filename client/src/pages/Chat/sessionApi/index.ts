import {
  IAgentScopeRuntimeWebUISession,
  IAgentScopeRuntimeWebUISessionAPI,
  IAgentScopeRuntimeWebUIMessage,
} from "@agentscope-ai/chat";
import api, {
  type ChatSpec,
  type ChatHistory,
  type ChatStatus,
  type Message,
} from "../../../api";
import { useAgentStore } from "../../../stores/agentStore";
import { toDisplayUrl } from "../utils";

// ---------------------------------------------------------------------------
// Retry helper
// ---------------------------------------------------------------------------

/**
 * Retry an async function with exponential backoff.
 * @param fn The async function to retry
 * @param maxRetries Maximum number of retries (default: 3)
 * @param baseDelay Base delay in ms (default: 1000)
 * @returns The result of the function
 */
async function withRetry<T>(
  fn: () => Promise<T>,
  maxRetries: number = 3,
  baseDelay: number = 1000,
): Promise<T> {
  let lastError: Error | undefined;
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await fn();
    } catch (err) {
      lastError = err as Error;
      if (attempt < maxRetries) {
        const delay = baseDelay * Math.pow(2, attempt);
        console.warn(
          `[sessionApi] Retry ${attempt + 1}/${maxRetries} after ${delay}ms:`,
          (err as Error).message,
        );
        await new Promise((resolve) => setTimeout(resolve, delay));
      }
    }
  }
  throw lastError;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DEFAULT_USER_ID = "default";
const DEFAULT_CHANNEL = "console";
const DEFAULT_SESSION_NAME = "New Chat";
const ROLE_TOOL = "tool";
const ROLE_USER = "user";
const ROLE_ASSISTANT = "assistant";
// const CARD_REQUEST = "AgentScopeRuntimeRequestCard";
const CARD_RESPONSE = "AgentScopeRuntimeResponseCard";

// ---------------------------------------------------------------------------
// Window globals
// ---------------------------------------------------------------------------

interface CustomWindow extends Window {
  currentSessionId?: string;
  currentUserId?: string;
  currentChannel?: string;
}

declare const window: CustomWindow;

// ---------------------------------------------------------------------------
// Local helper types
// ---------------------------------------------------------------------------

/** A single item inside a message's content array. */
interface ContentItem {
  type: string;
  text?: string;
  [key: string]: unknown;
}

/** A backend message after role-normalisation (output of toOutputMessage). */
interface OutputMessage extends Omit<Message, "role"> {
  role: string;
  metadata: unknown;
  sequence_number?: number;
}

/**
 * Extended session carrying extra fields that the library type does not define
 * but our backend / window globals require.
 */
interface ExtendedSession extends IAgentScopeRuntimeWebUISession {
  /** Session identifier (channel:user_id format) */
  sessionId: string;
  /** User identifier */
  userId: string;
  /** Channel name */
  channel: string;
  /** Additional metadata */
  meta: Record<string, unknown>;
  /** Real backend UUID, used when id is overridden with a local timestamp. */
  realId?: string;
  /** Conversation status from backend. */
  status?: ChatStatus;
  /** ISO 8601 creation timestamp from backend. */
  createdAt?: string | null;
  /** ISO 8601 last-updated timestamp from backend. */
  updatedAt?: string | null;
  /** Whether the backend is still generating a response for this session. */
  generating?: boolean;
  /** Whether the chat is pinned to the top. */
  pinned?: boolean;
  /** Whether there are more (older) messages not yet loaded. */
  hasMore?: boolean;
  /** Total message count in the chat (including archived). */
  totalCount?: number;
}

// ---------------------------------------------------------------------------
// Message conversion helpers: backend flat messages → card-based UI format
// ---------------------------------------------------------------------------

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
}

/** Extract plain text from a message's content array. */
const extractTextFromContent = (content: unknown): string => {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return String(content || "");
  return (content as ContentItem[])
    .filter((c) => c.type === "text")
    .map((c) => c.text || "")
    .filter(Boolean)
    .join("\n");
};

/** Normalize absolute filesystem paths to relative paths for file preview.
 *  e.g. "/apps/ai/coapis/workspaces/admin/files/media/xxx.ppm" → "/media/xxx.ppm"
 *  If the path is already relative, return as-is. */
function normalizeFileUrl(url: string | undefined): string {
  if (!url) return "";
  // Already a relative path (starts with /media/ or similar)
  if (url.startsWith("/media/") || url.startsWith("media/")) return url;
  // Absolute path containing /files/ — extract relative part after /files/
  const filesIdx = url.indexOf("/files/");
  if (filesIdx >= 0) {
    return url.slice(filesIdx + "/files/".length);
  }
  // file:// URI — strip scheme
  if (url.startsWith("file://")) {
    const stripped = url.slice("file://".length);
    const idx = stripped.indexOf("/files/");
    if (idx >= 0) return stripped.slice(idx + "/files/".length);
  }
  return url;
}

function resolveContentItemUrl(c: ContentItem): ContentItem {
  if (c.type === "image" && c.image_url) {
    return { ...c, image_url: toDisplayUrl(c.image_url as string) };
  }
  if (c.type === "audio" && c.data) {
    return { ...c, data: toDisplayUrl(c.data as string) };
  }
  if (c.type === "video" && c.video_url) {
    return { ...c, video_url: toDisplayUrl(c.video_url as string) };
  }
  if (c.type === "file" && (c.file_url || c.file_id)) {
    const raw = (c.file_url as string) || (c.file_id as string) || "";
    const normalized = normalizeFileUrl(raw);
    return {
      ...c,
      file_url: toDisplayUrl(normalized.startsWith("/") ? normalized : `/${normalized}`),
      file_name: (c.filename as string) || (c.file_name as string) || "file",
    };
  }
  return c;
}

/** Strip [SEARCH_RESULTS]...[/SEARCH_RESULTS] blocks from user message text.
 *  Old session data may have search results injected into the user message;
 *  this filters them out so only the original user text is displayed. */
function stripSearchResults(text: string): string {
  return text.replace(/\[SEARCH_RESULTS\][\s\S]*?\[\/SEARCH_RESULTS\]\s*/g, '').trim();
}

/** Map backend message content to request card content (text + image + file). */
function contentToRequestParts(
  content: unknown,
): Array<Record<string, unknown>> {
  if (typeof content === "string") {
    return [{ type: "text", text: content, status: "created" }];
  }
  if (!Array.isArray(content)) {
    return [{ type: "text", text: stripSearchResults(String(content || "")), status: "created" }];
  }
  const parts = (content as ContentItem[])
    .map(resolveContentItemUrl)
    .map((c) => {
      // Filter [SEARCH_RESULTS] from text blocks in user messages
      if (c.type === "text" && c.text) {
        return { ...c, text: stripSearchResults(c.text), status: "created" };
      }
      return { ...c, status: "created" };
    });

  if (parts.length === 0) {
    return [{ type: "text", text: "", status: "created" }];
  }

  return parts;
}
function normalizeOutputMessageContent(content: unknown): unknown {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return content;
  return (content as ContentItem[]).map(resolveContentItemUrl);
}

/**
 * Convert a backend message to response output message(s).
 *
 * The backend uses `agentscope_msg_to_message` to convert AgentScope
 * messages into runtime Messages. Each output message already carries the
 * correct semantic `type` (message / reasoning / plugin_call / plugin_call_output
 * / mcp_call / mcp_call_output / function_call / function_call_output / error /
 * heartbeat / component_call / component_call_output).
 *
 * Content blocks within each message share the same semantic type:
 *   - reasoning messages:  content = [{ type: "text", text: "..." }]
 *   - plugin_call messages: content = [{ type: "data", data: { call_id, name, arguments } }]
 *   - plugin_call_output:  content = [{ type: "data", data: { call_id, name, output } }]
 *   - message messages:     content = [{ type: "text", text: "..." }, ...]
 *
 * Strategy: **trust msg.type** as the source of truth. Only fall back to
 * block-level type detection when msg.type is missing or generic "message".
 */
const BLOCK_TYPE_MAP: Record<string, { msgType: string; metaType?: string; role?: string }> = {
  // Legacy block-level type mappings (fallback only)
  thinking:        { msgType: "reasoning", metaType: "reasoning" },
  text:            { msgType: "message" },
  tool_use:        { msgType: "plugin_call", metaType: "plugin_call" },
  tool_result:     { msgType: "plugin_call_output", metaType: "plugin_call_output", role: "tool" },
  data:            { msgType: "data" },  // generic data — needs msg.type override
  // Message-level type mappings (primary)
  message:         { msgType: "message" },
  reasoning:       { msgType: "reasoning", metaType: "reasoning" },
  plugin_call:     { msgType: "plugin_call", metaType: "plugin_call" },
  plugin_call_output: { msgType: "plugin_call_output", metaType: "plugin_call_output", role: "tool" },
  mcp_call:        { msgType: "mcp_call", metaType: "mcp_call" },
  mcp_call_output: { msgType: "mcp_call_output", metaType: "mcp_call_output", role: "tool" },
  function_call:   { msgType: "function_call", metaType: "function_call" },
  function_call_output: { msgType: "function_call_output", metaType: "function_call_output", role: "tool" },
  component_call:  { msgType: "component_call", metaType: "component_call" },
  component_call_output: { msgType: "component_call_output", metaType: "component_call_output", role: "tool" },
  error:           { msgType: "error", metaType: "error" },
  heartbeat:       { msgType: "heartbeat" },
};

const toOutputMessage = (msg: Message): OutputMessage[] => {
  const content = msg.content;
  // Resolve message type: prefer msg.type, fallback to metadata.type, then "message"
  // Persisted messages may only have metadata.type (e.g. reasoning messages)
  const msgType = (msg.type as string) || (msg.metadata as Record<string, string>)?.type || "message";

  // Determine role: tool outputs from system role → "tool"
  const effectiveRole =
    (msgType === "plugin_call_output" || msgType === "mcp_call_output" ||
     msgType === "function_call_output" || msgType === "component_call_output")
    && msg.role === "system"
      ? ROLE_TOOL
      : msg.role;

  // --- Single message, no splitting needed ---
  // The backend already produces one semantic type per message.
  // Just map msg.type to the correct output type.
  const mapping = BLOCK_TYPE_MAP[msgType] || { msgType: "message" };

  // String content → single message
  if (typeof content === "string") {
    return [{
      ...msg,
      role: mapping.role || effectiveRole,
      metadata: mapping.metaType ? { type: mapping.metaType } : (msg.metadata ?? null),
      type: mapping.msgType,
    }];
  }

  // Array content → return as single output message (backend already split by type)
  if (Array.isArray(content)) {
    // Fallback: if msg.type is generic "message" but blocks suggest a more
    // specific type (e.g. old sessions with mixed content), split by block.
    if (msgType === "message" && content.length > 1) {
      const blockTypes = new Set(content.map(c => (c as ContentItem)?.type).filter(Boolean));
      if (blockTypes.size > 1) {
        // Mixed content — split per block
        const parts: OutputMessage[] = [];
        for (const block of content) {
          const bType = (block as ContentItem)?.type || "text";
          const bMapping = BLOCK_TYPE_MAP[bType] || { msgType: "message" };
          parts.push({
            id: msg.id,
            name: msg.name,
            role: bMapping.role || effectiveRole,
            content: [block],
            metadata: bMapping.metaType ? { type: bMapping.metaType } : (msg.metadata ?? null),
            sequence_number: msg.sequence_number,
            timestamp: msg.timestamp,
            type: bMapping.msgType,
          } as OutputMessage);
        }
        return parts.length > 0 ? parts : [{ ...msg, role: effectiveRole, metadata: msg.metadata ?? null }];
      }
    }

    // Normal case: single semantic type, return as-is
    return [{
      ...msg,
      role: mapping.role || effectiveRole,
      content,
      metadata: mapping.metaType ? { type: mapping.metaType } : (msg.metadata ?? null),
      type: mapping.msgType,
    }];
  }

  // Fallback
  return [{
    ...msg,
    role: mapping.role || effectiveRole,
    metadata: mapping.metaType ? { type: mapping.metaType } : (msg.metadata ?? null),
    type: mapping.msgType,
  }];
};

/** Build a user card (AgentScopeRuntimeRequestCard) from a user message. */
function buildUserCard(msg: Message): IAgentScopeRuntimeWebUIMessage {
  const contentParts = contentToRequestParts(msg.content);
  return {
    id: (msg.id as string) || generateId(),
    role: "user",
    cards: [
      {
        code: "AgentScopeRuntimeRequestCard",
        data: {
          input: [
            {
              role: "user",
              type: "message",
              content: contentParts,
            },
          ],
        },
      },
    ],
  };
}

/**
 * Build an assistant response card (AgentScopeRuntimeResponseCard)
 * wrapping a group of consecutive non-user output messages.
 */
const buildResponseCard = (
  outputMessages: OutputMessage[],
): IAgentScopeRuntimeWebUIMessage => {
  const now = Math.floor(Date.now() / 1000);
  const maxSeq = outputMessages.reduce(
    (max, m) => Math.max(max, m.sequence_number || 0),
    0,
  );

  const normalizedMessages = outputMessages.map((msg) => ({
    ...msg,
    content: normalizeOutputMessageContent(msg.content),
  }));

  // Build cards: single AgentScopeRuntimeResponseCard with ALL messages (including reasoning)
  // The library's default card handles thinking/tool/text rendering internally.
  const cards: Array<{ code: string; data: Record<string, unknown> }> = [];

  if (normalizedMessages.length > 0) {
    cards.push({
      code: CARD_RESPONSE,
      data: {
        id: `response_${generateId()}`,
        output: normalizedMessages,
        object: "response",
        status: "completed",
        created_at: now,
        sequence_number: maxSeq + 1,
        error: null,
        completed_at: now,
        usage: null,
      },
    });
  }

  return {
    id: generateId(),
    role: ROLE_ASSISTANT,
    cards,
    msgStatus: "finished",
  };
};

/**
 * Convert flat backend messages into the card-based format expected by
 * the @agentscope-ai/chat component.
 *
 * - User messages → AgentScopeRuntimeRequestCard
 * - Consecutive non-user messages (assistant / system / tool) → grouped
 *   into a single AgentScopeRuntimeResponseCard with all output messages.
 */
const convertMessages = (
  messages: Message[],
): IAgentScopeRuntimeWebUIMessage[] => {
  const result: IAgentScopeRuntimeWebUIMessage[] = [];
  let i = 0;

  while (i < messages.length) {
    if (messages[i].role === ROLE_USER) {
      result.push(buildUserCard(messages[i++]));
    } else {
      const outputMsgs: OutputMessage[] = [];
      while (i < messages.length && messages[i].role !== ROLE_USER) {
        outputMsgs.push(...toOutputMessage(messages[i++]));
      }
      if (outputMsgs.length) result.push(buildResponseCard(outputMsgs));
    }
  }

  return result;
};

const chatSpecToSession = (chat: ChatSpec): ExtendedSession =>
  ({
    id: chat.id,
    name: chat.name || DEFAULT_SESSION_NAME,
    sessionId: chat.session_id,
    userId: chat.user_id,
    channel: chat.channel,
    messages: [],
    meta: chat.meta || {},
    status: chat.status ?? "idle",
    createdAt: chat.created_at ?? null,
    updatedAt: chat.updated_at ?? chat.created_at ?? null,
    pinned: chat.pinned ?? false,
    generating: chat.generating ?? false,
  }) as ExtendedSession;

/** Returns true when id is a pure numeric local timestamp (not a backend UUID). */
const isLocalTimestamp = (id: string): boolean => /^\d+$/.test(id);

/** Detect if backend is still generating content for this chat. */
const isGenerating = (chatHistory: ChatHistory): boolean => {
  if (chatHistory.status === "running") return true;
  if (chatHistory.status === "idle") return false;
  const msgs = chatHistory.messages || [];
  if (msgs.length === 0) return false;
  const last = msgs[msgs.length - 1];
  return last.role === ROLE_USER;
};

/**
 * Resolve and persist the real backend UUID for a local timestamp session.
 * Stores the real UUID as realId while keeping the timestamp as id, so the
 * library's internal currentSessionId (timestamp) remains valid.
 * Returns the resolved real UUID, or null if not found.
 */
const resolveRealId = (
  sessionList: IAgentScopeRuntimeWebUISession[],
  tempSessionId: string,
): { list: IAgentScopeRuntimeWebUISession[]; realId: string | null } => {
  // First try to match by sessionId (works when backend uses same format)
  let realSession = sessionList.find(
    (s) => (s as ExtendedSession).sessionId === tempSessionId,
  );

  // If not found by sessionId, try to match by realId on the local session.
  // The local session may already have a realId from createSession()'s
  // immediate api.createChat() call.
  if (!realSession) {
    realSession = sessionList.find(
      (s) => (s as ExtendedSession).realId && isLocalTimestamp(s.id),
    ) as ExtendedSession | undefined;
  }

  // NOTE: We intentionally do NOT fall back to "newest unmatched backend
  // session".  That strategy caused any new chat to be hijacked by the
  // first backend chat in the list.

  if (!realSession) return { list: sessionList, realId: null };

  const realUUID = realSession.id;
  (realSession as ExtendedSession).realId = realUUID;
  realSession.id = tempSessionId;
  return {
    list: [realSession, ...sessionList.filter((s) => s !== realSession)],
    realId: realUUID,
  };
};

// ---------------------------------------------------------------------------
// Per-session user message persistence (survives page refresh)
// ---------------------------------------------------------------------------

const STORAGE_PREFIX = "coapis_pending_user_msg_";

function savePendingUserMessage(sessionId: string, text: string): void {
  try {
    sessionStorage.setItem(`${STORAGE_PREFIX}${sessionId}`, text);
  } catch {
    /* quota exceeded – ignore */
  }
}

function loadPendingUserMessage(sessionId: string): string {
  try {
    return sessionStorage.getItem(`${STORAGE_PREFIX}${sessionId}`) || "";
  } catch {
    return "";
  }
}

function clearPendingUserMessage(sessionId: string): void {
  try {
    sessionStorage.removeItem(`${STORAGE_PREFIX}${sessionId}`);
  } catch {
    /* ignore */
  }
}

// ---------------------------------------------------------------------------
// SessionApi
// ---------------------------------------------------------------------------

class SessionApi implements IAgentScopeRuntimeWebUISessionAPI {
  private _sessions: IAgentScopeRuntimeWebUISession[] = [];
  private _currentSessionId: string | null = null;

  /**
   * Current session id in the library context. Set by ChatSessionInitializer so
   * that external guards (e.g. the sender beforeSubmit hook) can tell whether a
   * session has already been established.
   */
  libraryCurrentSessionId?: string;

  /**
   * Injected by ChatSessionInitializer. Creates a fresh session when the user
   * is about to send the first message and no session exists yet. This splits
   * session creation and message sending into two distinct steps, avoiding the
   * race where the library's session loader clears the first user message.
   */
  createSessionIfNeeded?: () => Promise<string>;

  /**
   * Whether the library has finished loading the session list for the current
   * agent. Used by ChatSessionInitializer to decide when it is safe to auto-
   * create a session for a brand-new agent.
   */
  _sessionListLoaded = false;
  private _lastSessionListAgentId: string | null = null;

  /**
   * Guard to prevent concurrent auto-created sessions.
   */
  _autoCreatingSession = false;

  /**
   * When set, getSessionList will move the matching session to the front on the first call,
   * so the library's useMount auto-selects it instead of always defaulting to sessions[0].
   * Cleared after first use.
   */
  preferredChatId: string | null = null;

  /**
   * Polling timers for sessions that are still generating when loaded.
   * Key: realId (backend chat UUID), Value: timer reference.
   *
   * When a user navigates away during generation and comes back, the SSE
   * stream is gone but the backend task is still running.  This timer polls
   * the chat status until generation completes, then updates the session
   * messages so the UI shows the final result instead of a stuck state.
   */
  private _generatingPolls: Map<string, ReturnType<typeof setInterval>> = new Map();
  private static readonly POLL_INTERVAL_MS = 3000;
  private static readonly POLL_MAX_ATTEMPTS = 60; // 3min max (60 × 3s)

  /**
   * Cache the latest user message for a chat so it can be patched into
   * history during reconnect (the backend only persists it after generation
   * completes). Persisted to sessionStorage so it survives page refresh.
   */
  setLastUserMessage(sessionId: string, text: string): void {
    if (!sessionId || !text) return;
    savePendingUserMessage(sessionId, text);
  }

  /**
   * Deduplicates concurrent getSessionList calls so that two parallel
   * invocations share one network request and write sessionList only once,
   * preserving any realId mappings that were already resolved.
   */
  private sessionListRequest: Promise<IAgentScopeRuntimeWebUISession[]> | null =
    null;

  /**
   * Deduplicates concurrent getSession calls for the same sessionId.
   * Key: sessionId, Value: in-flight promise for getSession.
   */
  private sessionRequests: Map<
    string,
    Promise<IAgentScopeRuntimeWebUISession>
  > = new Map();

  /**
   * Called when a temporary timestamp session id is resolved to a real backend
   * UUID. Consumers (e.g. Chat/index.tsx) can register here to update the URL.
   */
  onSessionIdResolved: ((tempId: string, realId: string) => void) | null = null;

  /**
   * Called after a session is removed. Consumers can register here to clear
   * the session id from the URL.
   */
  onSessionRemoved: ((removedId: string) => void) | null = null;

  /**
   * Called when a session is selected from the session list.
   * Consumers can register here to update the URL when switching sessions.
   */
  onSessionSelected:
    | ((sessionId: string | null | undefined, realId: string | null) => void)
    | null = null;

  /**
   * Called when a new session is created.
   * Consumers can register here to update the URL with the new session id.
   */
  onSessionCreated: ((sessionId: string) => void) | null = null;

  /**
   * Called when getSessionList completes (e.g. after scheduleSessionListRefresh).
   * The Chat component uses this to sync the React state so the sidebar updates.
   */
  onSessionListUpdated: ((sessions: IAgentScopeRuntimeWebUISession[]) => void) | null = null;

  /**
   * Called when a newly created session's realId (backend UUID) is resolved
   * during createSession(). Consumers (Chat/index.tsx) use this to update
   * chatIdRef so that the first message is sent with the correct chat_id.
   */
  onSessionRealIdResolved: ((localId: string, realId: string) => void) | null = null;

  /** Public read-only access to the session list. */
  get sessionList(): IAgentScopeRuntimeWebUISession[] {
    return this._sessions;
  }

  /** Get the currently active session object. */
  get currentSession(): ExtendedSession | null {
    const id = this._currentSessionId;
    if (!id) return null;
    return (this._sessions.find(
      (s: any) => s.id === id || s.sessionId === id || s.realId === id,
    ) as ExtendedSession) || null;
  }

  /**
   * When reconnecting to a running conversation, the backend history may not
   * include the latest user message (it's only persisted after generation
   * completes). If generating, look up the cached text from sessionStorage
   * and patch it into the message list.
   *
   * When not generating the conversation is done — clear the cached entry.
   */
  private patchLastUserMessage(
    messages: IAgentScopeRuntimeWebUIMessage[],
    generating: boolean,
    backendSessionId: string,
  ): void {
    if (!generating) {
      clearPendingUserMessage(backendSessionId);
      return;
    }

    const cachedText = loadPendingUserMessage(backendSessionId);
    if (!cachedText) return;

    const lastMsg = messages[messages.length - 1];
    if (lastMsg?.role === ROLE_USER) {
      const text = extractTextFromContent(
        lastMsg?.cards?.[0]?.data?.input?.[0]?.content,
      );
      if (!text) {
        // Replace the entire message instead of mutating read-only cards property
        messages[messages.length - 1] = buildUserCard({
          content: [{ type: "text", text: cachedText }],
          role: ROLE_USER,
        } as Message);
      }
    } else {
      messages.push(
        buildUserCard({
          content: [{ type: "text", text: cachedText }],
          role: ROLE_USER,
        } as Message),
      );
    }
  }

  private createEmptySession(sessionId: string): ExtendedSession {
    window.currentSessionId = sessionId;
    this._currentSessionId = sessionId;
    // Only reset userId/channel if not already set by authentication
    // This prevents overwriting the authenticated user's identity
    // Get current username from JWT token if window.currentUserId not set
    if (!window.currentUserId) {
      try {
        const token = localStorage.getItem("coapis_auth_token");
        if (token) {
          const payload = JSON.parse(atob(token.split(".")[1] || ""));
          window.currentUserId = payload?.sub || payload?.username || DEFAULT_USER_ID;
        }
      } catch {
        // ignore
      }
    }
    if (!window.currentUserId || window.currentUserId === DEFAULT_USER_ID) {
      window.currentUserId = DEFAULT_USER_ID;
    }
    if (!window.currentChannel || window.currentChannel === DEFAULT_CHANNEL) {
      window.currentChannel = DEFAULT_CHANNEL;
    }
    return {
      id: sessionId,
      name: DEFAULT_SESSION_NAME,
      sessionId,
      userId: window.currentUserId || DEFAULT_USER_ID,
      channel: window.currentChannel || DEFAULT_CHANNEL,
      messages: [],
      meta: {},
    } as ExtendedSession;
  }

  private updateWindowVariables(session: ExtendedSession): void {
    window.currentSessionId = session.sessionId || "";
    this._currentSessionId = session.sessionId || session.id || null;
    window.currentUserId = session.userId || DEFAULT_USER_ID;
    window.currentChannel = session.channel || DEFAULT_CHANNEL;
  }

  private getLocalSession(sessionId: string): IAgentScopeRuntimeWebUISession {
    const local = this._sessions.find((s) => s.id === sessionId);
    if (local) {
      this.updateWindowVariables(local as ExtendedSession);
      return local;
    }
    return this.createEmptySession(sessionId);
  }

  /**
   * Returns the real backend UUID for a session identified by id (which may be
   * a local timestamp). Returns null when not yet resolved or not found.
   */
  getRealIdForSession(sessionId: string): string | null {
    const s = this._sessions.find((x) => x.id === sessionId) as
      | ExtendedSession
      | undefined;
    return s?.realId ?? null;
  }

  /** Apply listChats to sessionList; merge realId and generating by session_id. */
  /**
   * Upsert a session into _sessions after fetching fresh data from backend.
   * This prevents getSessionList from overwriting freshly-loaded messages
   * with stale/empty data.
   */
  private _upsertSession(session: ExtendedSession): void {
    const idx = this._sessions.findIndex(
      (s) =>
        s.id === session.id ||
        (s as ExtendedSession).realId === session.realId ||
        ((s as ExtendedSession).sessionId &&
          (s as ExtendedSession).sessionId === session.sessionId),
    );
    if (idx >= 0) {
      this._sessions[idx] = session;
    } else {
      this._sessions.push(session);
    }
    // Notify React so components (e.g. ChatSessionHeader) re-render
    this.onSessionListUpdated?.(this._sessions);
  }

  /**
   * Force-clear the cached session list so the next getSessionList() call
   * re-fetches from the backend. Used when switching agents.
   * Also clears in-flight session requests to prevent stale data.
   */
  invalidateSessionList() {
    this.sessionListRequest = null;
    this._sessions = [];
    this.lastSelectedSessionId = null;
    this._sessionListLoaded = false;
    this._lastSessionListAgentId = null;
    // Clear in-flight session requests to prevent stale data after agent switch
    this.sessionRequests.clear();
  }

  async getSessionList() {
    if (this.sessionListRequest) return this.sessionListRequest;

    // Reset the loaded flag when the agent changes, so callers can tell the
    // difference between "not loaded yet" and "no sessions exist".
    const currentAgent = useAgentStore.getState().selectedAgent;
    if (this._lastSessionListAgentId !== currentAgent) {
      this._lastSessionListAgentId = currentAgent;
      this._sessionListLoaded = false;
    }

    this.sessionListRequest = (async () => {
      try {
        // Filter by current user to avoid loading other users' chats.
        // Filter by current agent for multi-agent isolation.
        // Get userId from window or JWT token
        let userId = window.currentUserId;
        if (!userId) {
          try {
            const token = localStorage.getItem("coapis_auth_token");
            if (token) {
              const payload = JSON.parse(atob(token.split(".")[1] || ""));
              userId = payload?.sub || payload?.username || "";
            }
          } catch {
            // ignore
          }
        }
        const channel = window.currentChannel;
        const agentId = useAgentStore.getState().selectedAgent;
        if (!agentId) {
          console.warn('[sessionApi] getSessionList: no agent selected, skipping');
          this._sessionListLoaded = true;
          return [];
        }
        if (!userId) {
          console.warn('[sessionApi] getSessionList: no user_id available, skipping');
          this._sessionListLoaded = true;
          return [];
        }
        const params: { user_id?: string; channel?: string; agent_id?: string } = {};
        if (userId) params.user_id = userId;
        if (channel) params.channel = channel;
        if (agentId) params.agent_id = agentId;
        const chats = await api.listChats(
          Object.keys(params).length > 0 ? params : undefined,
        );

        // COAPIS FIX: Directly use API response instead of merging with cache.
        // This prevents duplicate entries caused by mismatched IDs between
        // local cache (timestamp) and backend (UUID).
        // Only preserve the current session's messages if they exist in cache.
        const newList = chats
          .filter((c) => c.id && c.id !== "undefined" && c.id !== "null")
          .map(chatSpecToSession)
          .reverse();

        // Preserve messages from current cache for sessions that have them
        const messagesMap = new Map<string, any[]>();
        for (const existing of this._sessions) {
          if (existing.messages && existing.messages.length > 0) {
            const key = (existing as ExtendedSession).realId || existing.id;
            messagesMap.set(key, existing.messages);
          }
        }

        // Apply preserved messages to new list
        const result = newList.map((s) => {
          const key = (s as ExtendedSession).realId || s.id;
          const messages = messagesMap.get(key);
          if (messages && (!s.messages || s.messages.length === 0)) {
            return { ...s, messages } as any;
          }
          return s;
        });

        this._sessions = result;

        // Trigger generating-poll for sessions actively processed by other channels
        // so sidebar shows "Live" and messages appear once processing completes.
        for (const session of result) {
          const ext = session as ExtendedSession;
          if (ext.generating && ext.realId) {
            this._startGeneratingPoll(ext.realId);
          }
        }

        // Handle preferredChatId (move preferred session to front)
        if (this.preferredChatId) {
          const preferredId = this.preferredChatId;
          this.preferredChatId = null;
          const idx = this._sessions.findIndex(
            (s) => s.id === preferredId || (s as ExtendedSession).realId === preferredId,
          );
          if (idx > 0) {
            const [preferred] = this._sessions.splice(idx, 1);
            this._sessions.unshift(preferred);
          }
        }

        // Notify React so the sidebar re-renders with updated names
        this.onSessionListUpdated?.(result);
        this._sessionListLoaded = true;
        return result;
      } catch (err) {
        console.error(`[sessionApi] getSessionList error:`, err);
        this._sessionListLoaded = false;
        throw err;
      } finally {
        this.sessionListRequest = null;
      }
    })();

    return this.sessionListRequest;
  }

  /** Track the last session ID that triggered onSessionSelected to avoid duplicate calls. */
  private lastSelectedSessionId: string | null = null;

  async getSession(sessionId: string) {
    const existingRequest = this.sessionRequests.get(sessionId);
    if (existingRequest) {
      return existingRequest;
    }

    const requestPromise = this._doGetSession(sessionId);
    this.sessionRequests.set(sessionId, requestPromise);

    try {
      const session = await requestPromise;
      // Trigger onSessionSelected only when session actually changes
      if (sessionId !== this.lastSelectedSessionId) {
        this.lastSelectedSessionId = sessionId;
        const extendedSession = session as ExtendedSession;
        const realId = extendedSession.realId || null;
        this.onSessionSelected?.(sessionId, realId);
      }
      return session;
    } finally {
      this.sessionRequests.delete(sessionId);
    }
  }

  private async _doGetSession(
    sessionId: string,
  ): Promise<IAgentScopeRuntimeWebUISession> {
    // --- Local timestamp ID (New Chat before first reply) ---
    if (isLocalTimestamp(sessionId)) {
      const fromList = this._sessions.find((s) => s.id === sessionId) as
        | ExtendedSession
        | undefined;

      // If realId is already resolved, use it directly to fetch history.
      if (fromList?.realId) {
        try {
          const chatHistory = await withRetry(() => api.getChat(fromList.realId!));
          const generating = isGenerating(chatHistory);
          const messages = convertMessages(chatHistory.messages || []);
          this.patchLastUserMessage(messages, generating, fromList.realId);
          // Prefer spec.name from backend (auto-renamed) over local cache
          const backendName = (chatHistory as any).spec?.name;
          const session: ExtendedSession = {
            id: sessionId,
            name: backendName || fromList.name || DEFAULT_SESSION_NAME,
            sessionId: fromList.sessionId || sessionId,
            userId: fromList.userId || DEFAULT_USER_ID,
            channel: fromList.channel || DEFAULT_CHANNEL,
            messages,
            meta: fromList.meta || {},
            realId: fromList.realId,
            generating,
            hasMore: chatHistory.has_more ?? false,
            totalCount: chatHistory.total_count,
          };
          this.updateWindowVariables(session);
          this._upsertSession(session);
          // Start polling + SSE reconnect if still generating
          if (generating) {
            this._startGeneratingPoll(fromList.realId);
            this._emitReconnectEvent(fromList.realId);
          }
          return session;
        } catch {
          // Chat may have been deleted or not yet persisted; fall through to return local session
          console.warn(`Chat ${fromList.realId} not found, returning local session`);
        }
      }

      // Pure local session (not yet sent to backend): wait until updateSession
      // resolves the realId, then fetch history with the real UUID.
      await new Promise<void>((resolve) => {
        const check = () => {
          const s = this._sessions.find((x) => x.id === sessionId) as
            | ExtendedSession
            | undefined;
          if (s?.realId) {
            resolve();
          } else {
            setTimeout(check, 100);
          }
        };
        setTimeout(check, 100);
      });

      const refreshed = this._sessions.find((s) => s.id === sessionId) as
        | ExtendedSession
        | undefined;
      if (refreshed?.realId) {
        try {
          const chatHistory = await withRetry(() => api.getChat(refreshed.realId!));
          const generating = isGenerating(chatHistory);
          const messages = convertMessages(chatHistory.messages || []);
          this.patchLastUserMessage(messages, generating, refreshed.realId);
          // Prefer spec.name from backend (auto-renamed) over local cache
          const backendName = (chatHistory as any).spec?.name;
          const session: ExtendedSession = {
            id: sessionId,
            name: backendName || refreshed.name || DEFAULT_SESSION_NAME,
            sessionId: refreshed.sessionId || sessionId,
            userId: refreshed.userId || DEFAULT_USER_ID,
            channel: refreshed.channel || DEFAULT_CHANNEL,
            messages,
            meta: refreshed.meta || {},
            realId: refreshed.realId,
            generating,
          };
          this.updateWindowVariables(session);
          this._upsertSession(session);
          // Start polling + SSE reconnect if still generating
          if (generating) {
            this._startGeneratingPoll(refreshed.realId);
            this._emitReconnectEvent(refreshed.realId);
          }
          return session;
        } catch {
        }
      }

      return this.getLocalSession(sessionId);
    }

    // --- No session selected (e.g. after delete) ---
    if (!sessionId || sessionId === "undefined" || sessionId === "null") {
      return this.createEmptySession(Date.now().toString());
    }

    // --- Regular backend UUID or sessionId lookup ---
    const fromList = this._sessions.find((s) => s.id === sessionId) as
      | ExtendedSession
      | undefined;

    // If not found by id, try to find by sessionId field (e.g. "console:user")
    const fromListBySessionId = fromList ? undefined : this._sessions.find(
      (s) => (s as ExtendedSession).sessionId === sessionId
    ) as ExtendedSession | undefined;

    // FIX Issue 1: Also try to find by realId (backend UUID).
    // When ChatSessionInitializer sets currentSessionId to the backend UUID
    // (via realId matching), the session list entries may still have local
    // timestamp IDs in the .id field. We need to match by .realId.
    const fromListByRealId = (fromList || fromListBySessionId)
      ? undefined
      : this._sessions.find(
          (s) => (s as ExtendedSession).realId === sessionId,
        ) as ExtendedSession | undefined;

    const effectiveId = fromList?.realId
      || fromListBySessionId?.realId
      || fromListByRealId?.realId
      || sessionId;
    const sessionMeta = fromList || fromListBySessionId || fromListByRealId;


    try {
      const chatHistory = await withRetry(() => api.getChat(effectiveId));
      const generating = isGenerating(chatHistory);
      const messages = convertMessages(chatHistory.messages || []);
      this.patchLastUserMessage(messages, generating, effectiveId);
      // Prefer spec.name from backend (auto-renamed) over local cache
      const backendName = (chatHistory as any).spec?.name;
      const session: ExtendedSession = {
        id: sessionId,
        name: backendName || sessionMeta?.name || sessionId,
        sessionId: sessionMeta?.sessionId || sessionId,
        userId: sessionMeta?.userId || DEFAULT_USER_ID,
        channel: sessionMeta?.channel || DEFAULT_CHANNEL,
        messages,
        meta: sessionMeta?.meta || {},
        realId: effectiveId,
        generating,
        hasMore: chatHistory.has_more ?? false,
        totalCount: chatHistory.total_count,
      };

      this.updateWindowVariables(session);
      // Sync fetched messages back into _sessions so that subsequent
      // applyChatsToSessionList (from getSessionList) won't overwrite
      // them with stale/empty data from the list endpoint.
      this._upsertSession(session);
      // Start polling if still generating (no active SSE stream on reconnect)
      // Start polling + SSE reconnect if still generating
      if (generating) {
        this._startGeneratingPoll(effectiveId);
        this._emitReconnectEvent(effectiveId);
      }
      return session;
    } catch {
      return this.getLocalSession(sessionId);
    }
  }

  async updateSession(
    session: Partial<IAgentScopeRuntimeWebUISession>,
  ): Promise<IAgentScopeRuntimeWebUISession[]> {
    // FIX Issue 1: Try to find session by id, then by realId.
    // When currentSessionId is set to a backend UUID, session.id is the UUID,
    // but _sessions entries may have local timestamp IDs in .id field.
    let index = this._sessions.findIndex((s) => s.id === session.id);
    if (index === -1) {
      index = this._sessions.findIndex(
        (s) => (s as ExtendedSession).realId === session.id,
      );
    }

    if (index > -1) {
      this._sessions[index] = { ...this._sessions[index], ...session };

      const existing = this._sessions[index] as ExtendedSession;
      if (isLocalTimestamp(existing.id) && !existing.realId) {
        const tempId = existing.id;
        const pendingName = session.name; // Capture name before async operation
        this.getSessionList().then(() => {
          const { list, realId } = resolveRealId(this._sessions, tempId);
          this._sessions = list;
          if (realId) {
            this.onSessionIdResolved?.(tempId, realId);
            // Persist pending name after realId is resolved
            if (pendingName) {
              api.updateSession(realId, { name: pendingName }).catch((err: Error) => {
                console.error("Failed to persist session name to backend:", err);
              });
            }
          }
        });
      }
    } else {
      const tempId = session.id!;
      const pendingName = session.name; // Capture name before async operation
      await this.getSessionList().then(() => {
        const { list, realId } = resolveRealId(this._sessions, tempId);
        this._sessions = list;
        if (realId) {
          this.onSessionIdResolved?.(tempId, realId);
          // Persist pending name after realId is resolved
          if (pendingName) {
            api.updateSession(realId, { name: pendingName }).catch((err: Error) => {
              console.error("Failed to persist session name to backend:", err);
            });
          }
        }
      });
    }

    // Persist session name to backend when name is provided and session already has a backend ID
    if (session.name) {
      const existingSession = this._sessions.find((s) => s.id === session.id) as ExtendedSession;
      if (existingSession) {
        const backendId = existingSession.realId || (isLocalTimestamp(existingSession.id) ? null : existingSession.id);
        if (backendId) {
          // Fire and forget - don't await to avoid blocking the UI
          api.updateSession(backendId, { name: session.name }).catch((err: Error) => {
            console.error("Failed to persist session name to backend:", err);
          });
        }
      }
    }

    return [...this._sessions];
  }

  async createSession(
    session?: Partial<IAgentScopeRuntimeWebUISession>,
  ): Promise<IAgentScopeRuntimeWebUISession[]> {
    const extended = session as ExtendedSession | undefined;
    const sessionName = session?.name || DEFAULT_SESSION_NAME;
    const channel = extended?.channel || DEFAULT_CHANNEL;
    const userId = window.currentUserId || DEFAULT_USER_ID;

    // CRITICAL: Create backend session FIRST, then add to local cache.
    // This prevents race conditions where getSessionList() is called before
    // backend session is created, causing duplicate entries.
    try {
      const agentId = useAgentStore.getState().selectedAgent;
      if (!agentId) {
        throw new Error("Cannot create chat: no agent selected");
      }
      const created = await api.createChat({
        id: undefined,  // let backend generate UUID
        name: sessionName,
        session_id: undefined,  // let backend use chat_id (UUID) for per-chat isolation
        channel: channel,
        agent_id: agentId,
      });

      if (!created?.id) {
        throw new Error("Backend did not return session ID");
      }

      // Create local session with backend UUID as id (no timestamp mismatch)
      const newSession: ExtendedSession = {
        id: created.id,  // Use backend UUID directly
        name: sessionName,
        sessionId: created.session_id || created.id,  // Use backend session_id (UUID-based)
        userId: userId,
        channel: channel,
        messages: session?.messages || [],
        meta: extended?.meta || {},
        status: created.status ?? "idle",
        createdAt: created.created_at ?? null,
        updatedAt: created.updated_at ?? null,
        pinned: created.pinned ?? false,
        realId: created.id,  // Same as id since we use backend UUID
      } as ExtendedSession;

      this.updateWindowVariables(newSession);
      this._sessions.unshift(newSession);
      // Notify React so sidebar and header update immediately
      this.onSessionListUpdated?.(this._sessions);

      // Write the backend UUID back to the input object for the caller
      if (session) {
        (session as any).id = created.id;
        (session as any).sessionId = created.session_id || created.id;
        (session as any).realId = created.id;
      }

      // Notify consumers about the realId
      this.onSessionRealIdResolved?.(created.id, created.id);

      // Fire onSessionCreated AFTER successful backend creation
      this.onSessionCreated?.(created.id);

      console.log(`[sessionApi] Created session: id=${created.id}, name=${sessionName}`);

      // COAPIS FIX: Return a copy of the session list so the library can update
      // its session list (setSessions). Also write the backend UUID back to the
      // input object so the library's createSession gets a valid id for
      // setCurrentSessionId and the message loader can identify the session.
      return [...this._sessions];

    } catch (err) {
      console.error("[sessionApi] Failed to create session:", err);
      throw err;  // Let caller handle the error
    }
  }

  /**
   * Emit a 'handleReconnect' CustomEvent to trigger the @agentscope-ai/chat
   * library's SSE reconnect flow.  The library listens for this event via
   * useChatAnywhereEventEmitter and will establish an SSE stream to show
   * real-time generation progress (tool calls, thinking, assistant output).
   *
   * Called alongside _startGeneratingPoll so that:
   * - SSE provides real-time visibility during generation
   * - Polling acts as a fallback if SSE fails or is not supported
   */
  private _emitReconnectEvent(sessionId: string): void {
    // Defer to next tick so the library has time to finish session switching
    // (setCurrentSessionId → useEffect abort → render) before we trigger reconnect.
    setTimeout(() => {
      console.log(`[sessionApi] Emitting handleReconnect for ${sessionId}`);
      document.dispatchEvent(
        new CustomEvent("handleReconnect", {
          detail: { session_id: sessionId },
        }),
      );
    }, 50);
  }

  /**
   * Start polling for a session that is still generating on load.
   * Called from _doGetSession when isGenerating returns true but there is
   * no active SSE stream (user navigated away and came back).
   */
  private _startGeneratingPoll(realId: string): void {
    // Don't start duplicate polls
    if (this._generatingPolls.has(realId)) return;

    let attempts = 0;
    console.log(`[sessionApi] Starting generating poll for ${realId}`);

    const timer = setInterval(async () => {
      attempts++;
      if (attempts > SessionApi.POLL_MAX_ATTEMPTS) {
        console.warn(`[sessionApi] Poll timeout for ${realId} after ${attempts} attempts`);
        this._stopGeneratingPoll(realId);
        return;
      }

      try {
        const chatHistory = await api.getChat(realId);
        const stillGenerating = isGenerating(chatHistory);

        if (!stillGenerating) {
          console.log(`[sessionApi] Generation complete for ${realId}, updating session`);
          this._stopGeneratingPoll(realId);

          // Update the session with final messages
          const messages = convertMessages(chatHistory.messages || []);
          const existingSession = this._sessions.find(
            (s) => (s as ExtendedSession).realId === realId || s.id === realId,
          ) as ExtendedSession | undefined;

          if (existingSession) {
            existingSession.messages = messages;
            existingSession.generating = false;
            const backendName = (chatHistory as any).spec?.name;
            if (backendName) existingSession.name = backendName;
            existingSession.hasMore = chatHistory.has_more ?? false;
            existingSession.totalCount = chatHistory.total_count;
            clearPendingUserMessage(existingSession.realId || existingSession.id);
          }

          // Trigger UI refresh via callbacks
          this.onSessionListUpdated?.(this._sessions);
        }
      } catch (err) {
        // Transient errors are expected (network blips); just log and retry
        console.debug(`[sessionApi] Poll error for ${realId}:`, (err as Error).message);
      }
    }, SessionApi.POLL_INTERVAL_MS);

    this._generatingPolls.set(realId, timer);
  }

  /**
   * Stop polling for a session.
   */
  private _stopGeneratingPoll(realId: string): void {
    const timer = this._generatingPolls.get(realId);
    if (timer) {
      clearInterval(timer);
      this._generatingPolls.delete(realId);
    }
  }

  /**
   * Schedule a delayed refresh of the session list.
   * Called after each SSE response completes to pick up backend-side changes
   * (e.g. auto-rename from first user message, status updates).
   * Debounced to avoid excessive API calls during rapid message exchanges.
   */
  private _refreshTimer: ReturnType<typeof setTimeout> | null = null;
  private _refreshTimerCascade: ReturnType<typeof setTimeout> | null = null;

  scheduleSessionListRefresh(delayMs: number = 1500): void {
    if (this._refreshTimer) {
      clearTimeout(this._refreshTimer);
    }
    this._refreshTimer = setTimeout(() => {
      this._refreshTimer = null;
      this.getSessionList().catch(() => {
        /* ignore refresh errors */
      });
    }, delayMs);

    // Cascade: schedule a second refresh after a longer delay to pick up
    // backend auto-rename (which only happens after the SSE stream ends).
    // Long-running model responses can take 10-30s, so 8s is a safety net.
    if (this._refreshTimerCascade) {
      clearTimeout(this._refreshTimerCascade);
    }
    this._refreshTimerCascade = setTimeout(() => {
      this._refreshTimerCascade = null;
      this.getSessionList().catch(() => {
        /* ignore refresh errors */
      });
    }, Math.max(delayMs * 4, 8000));
  }

  async removeSession(session: Partial<IAgentScopeRuntimeWebUISession>) {
    if (!session.id) return [...this._sessions];

    const { id: sessionId } = session;

    const existing = this._sessions.find((s) => s.id === sessionId) as
      | ExtendedSession
      | undefined;

    // Stop any active generating poll for this session
    if (existing?.realId) this._stopGeneratingPoll(existing.realId);

    const deleteId =
      existing?.realId ?? (isLocalTimestamp(sessionId) ? null : sessionId);

    if (deleteId) await api.deleteChat(deleteId);

    this._sessions = this._sessions.filter((s) => s.id !== sessionId);

    const resolvedId = existing?.realId ?? sessionId;
    this.onSessionRemoved?.(resolvedId);

    return [...this._sessions];
  }
}

export { convertMessages };
export default new SessionApi();
