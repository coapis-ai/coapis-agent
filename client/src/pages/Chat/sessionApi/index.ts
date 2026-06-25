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
// Constants
// ---------------------------------------------------------------------------

const DEFAULT_USER_ID = "default";
const DEFAULT_CHANNEL = "console";
const DEFAULT_SESSION_NAME = "New Chat";
const ROLE_TOOL = "tool";
const ROLE_USER = "user";
const ROLE_ASSISTANT = "assistant";
const TYPE_PLUGIN_CALL_OUTPUT = "plugin_call_output";
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
    return {
      ...c,
      file_url: toDisplayUrl((c.file_url as string) || (c.file_id as string)),
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
 * The backend uses qwenpaw's `agentscope_msg_to_message` to convert AgentScope
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
  const msgType = (msg.type as string) || "message";

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

  // Build cards: single GroupedResponseCard with ALL messages (including reasoning)
  // The GroupedResponseCard handles thinking/tool/text rendering internally.
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
   * When set, getSessionList will move the matching session to the front on the first call,
   * so the library's useMount auto-selects it instead of always defaulting to sessions[0].
   * Cleared after first use.
   */
  preferredChatId: string | null = null;

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
        lastMsg.cards = buildUserCard({
          content: [{ type: "text", text: cachedText }],
          role: ROLE_USER,
        } as Message).cards;
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
  private applyChatsToSessionList(
    chats: ChatSpec[],
  ): IAgentScopeRuntimeWebUISession[] {
    const newList = chats
      .filter((c) => c.id && c.id !== "undefined" && c.id !== "null")
      .map(chatSpecToSession)
      .reverse();

    // Track which old sessions were matched to backend data
    const matchedOldIds = new Set<string>();

    const merged = newList.map((s) => {
      // First try to match by sessionId (works when backend uses same format)
      let existing = this._sessions.find(
        (e) =>
          (e as ExtendedSession).sessionId === (s as ExtendedSession).sessionId,
      ) as ExtendedSession | undefined;

      // If not found by sessionId, try to match by id (timestamp).
      if (!existing) {
        existing = this._sessions.find(
          (e) => e.id === s.id,
        ) as ExtendedSession | undefined;
      }

      // If still not found, try to match by realId (backend UUID).
      // This handles the case where createSession already resolved the UUID
      // but the sessionId format differs (e.g. "console:admin" vs timestamp).
      if (!existing) {
        const backendId = (s as ExtendedSession).realId || s.id;
        existing = this._sessions.find(
          (e) => (e as ExtendedSession).realId === backendId,
        ) as ExtendedSession | undefined;
      }

      // NOTE: We intentionally do NOT fall back to "any unmatched local
      // timestamp session".  That strategy caused cross-chat contamination:
      // any new session would be hijacked by the first backend chat.

      if (!existing) return s;
      matchedOldIds.add(existing.id);
      const next = { ...s } as ExtendedSession;
      if (existing.realId) {
        next.id = existing.id;
        next.realId = existing.realId;
      } else if (isLocalTimestamp(existing.id)) {
        next.realId = s.id;
        next.id = existing.id;
      }
      if (existing.generating !== undefined) {
        next.generating = existing.generating;
      }
      // CRITICAL: Preserve messages from the existing session if the backend
      // session has no messages (messages: []). Without this, navigating from
      // Sessions page to /chat/{uuid} would overwrite already-loaded messages
      // with an empty array, causing the chat to appear blank.
      if ((!next.messages || next.messages.length === 0) && existing.messages && existing.messages.length > 0) {
        next.messages = existing.messages;
      }
      return next as IAgentScopeRuntimeWebUISession;
    });

    // PRESERVE unmatched local sessions (newly created but not yet in backend)
    // This prevents the race condition where a fresh session is dropped
    // during the 1.5s refresh window after createChat.
    const unmatchedLocals = this._sessions.filter(
      (e) => !matchedOldIds.has(e.id),
    );
    this._sessions = [...unmatchedLocals, ...merged];

    if (this.preferredChatId) {
      const preferredId = this.preferredChatId;
      this.preferredChatId = null;
      // Match by id OR realId — after merge, the session's id may be a local
      // timestamp while the URL contains the backend UUID (realId).
      const idx = this._sessions.findIndex(
        (s) => s.id === preferredId || (s as ExtendedSession).realId === preferredId,
      );
      if (idx > 0) {
        const [preferred] = this._sessions.splice(idx, 1);
        this._sessions.unshift(preferred);
      }
      // Ensure the preferred session's id matches the URL chatId so that
      // the library's setCurrentSessionId(sessionList[0]?.id) produces the
      // same value ChatSessionInitializer would set, avoiding a redundant
      // useAsyncEffect re-trigger that would briefly clear messages.
      if (this._sessions.length > 0) {
        const first = this._sessions[0] as ExtendedSession;
        if (first.id !== preferredId && (first.realId === preferredId || first.id === preferredId)) {
          // id already matches, no-op
        } else if (first.realId === preferredId && first.id !== preferredId) {
          // Swap: use the backend UUID as id for consistency with URL
          first.id = preferredId;
        }
      }
    }
    return [...this._sessions];
  }

  /**
   * Upsert a session into _sessions after fetching fresh data from backend.
   * This prevents applyChatsToSessionList (from getSessionList) from
   * overwriting freshly-loaded messages with stale/empty data.
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
    // Clear in-flight session requests to prevent stale data after agent switch
    this.sessionRequests.clear();
  }

  async getSessionList() {
    if (this.sessionListRequest) return this.sessionListRequest;

    this.sessionListRequest = (async () => {
      try {
        // Filter by current user to avoid loading other users' chats.
        // Filter by current agent for multi-agent isolation.
        const userId = window.currentUserId;
        const channel = window.currentChannel;
        const agentId = useAgentStore.getState().selectedAgent;
        const params: { user_id?: string; channel?: string; agent_id?: string } = {};
        if (userId) params.user_id = userId;
        if (channel) params.channel = channel;
        if (agentId) params.agent_id = agentId;
        const chats = await api.listChats(
          Object.keys(params).length > 0 ? params : undefined,
        );
        const result = this.applyChatsToSessionList(chats);
        // Notify React so the sidebar re-renders with updated names
        this.onSessionListUpdated?.(result);
        return result;
      } catch (err) {
        console.error(`[sessionApi] getSessionList error:`, err);
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
          const chatHistory = await api.getChat(fromList.realId, { limit: 50 });
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
          const chatHistory = await api.getChat(refreshed.realId, { limit: 50 });
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
      const chatHistory = await api.getChat(effectiveId, { limit: 50 });
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
      return session;
    } catch {
      return this.getLocalSession(sessionId);
    }
  }

  async updateSession(session: Partial<IAgentScopeRuntimeWebUISession>) {
    // Always clear messages before updating session list (matches QwenPaw behavior).
    // Content loss during streaming is prevented by useChatController's
    // useEffect([currentSessionId]) which skips reset when msgStatus === 'generating'.
    session.messages = [];
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

  async createSession(session?: Partial<IAgentScopeRuntimeWebUISession>) {
    // COAPIS FIX: Set a flag so useChatAnywhereSessionLoader skips its
    // clear+fetch cycle. Without this, the session loader fires during
    // handleSubmit's sleep(100) and wipes the user message just added.
    // Use a time window to cover multiple triggers:
    // 1. setCurrentSessionId(localId) from library's createSession
    // 2. setCurrentSessionId(realId) from ChatSessionInitializer after URL navigation
    (window as any)._coapisSkipSessionLoadUntil = Date.now() + 2000;

    const id = Date.now().toString();
    const extended = session as ExtendedSession | undefined;
    const newSession: ExtendedSession = {
      id,
      name: session?.name || DEFAULT_SESSION_NAME,
      sessionId: id,
      userId: extended?.userId || DEFAULT_USER_ID,
      channel: extended?.channel || DEFAULT_CHANNEL,
      messages: session?.messages || [],
      meta: extended?.meta || {},
    } as ExtendedSession;

    this.updateWindowVariables(newSession);
    this._sessions.unshift(newSession);
    // Notify React so sidebar and header update immediately
    this.onSessionListUpdated?.(this._sessions);

    // CRITICAL: The chat library's updateSession() returns the original
    // session parameter (not the newly created one). The caller then does
    // setCurrentSessionId(session.id), so we must write the generated id
    // back onto the input object for the caller to pick it up.
    if (session && !session.id) {
      (session as any).id = id;
      (session as any).sessionId = id;
    }

    // Persist to backend immediately so the session survives getSessionList refresh.
    // Without this, applyChatsToSessionList replaces sessionList with backend-only
    // data, wiping out the local-only session.
    try {
      const agentId = useAgentStore.getState().selectedAgent;
      const created = await api.createChat({
        id: undefined,  // let backend generate UUID
        name: newSession.name || DEFAULT_SESSION_NAME,
        session_id: `console:${window.currentUserId || DEFAULT_USER_ID}`,
        channel: newSession.channel || DEFAULT_CHANNEL,
        ...(agentId ? { agent_id: agentId } : {}),
      });
      // Link local session to backend session
      const localSession = this._sessions.find((s) => s.id === id) as ExtendedSession | undefined;
      if (localSession && created?.id) {
        localSession.realId = created.id;
        (session as any).realId = created.id;
      }
    } catch (err) {
      console.warn("[sessionApi] Failed to persist new chat to backend:", err);
    }

    // Fire onSessionCreated AFTER api.createChat so realId is already set.
    // The callback navigates to /chat/{realId} to survive page refresh.
    this.onSessionCreated?.(id);

    return this._sessions;
  }

  /**
   * Schedule a delayed refresh of the session list.
   * Called after each SSE response completes to pick up backend-side changes
   * (e.g. auto-rename from first user message, status updates).
   * Debounced to avoid excessive API calls during rapid message exchanges.
   */
  private _refreshTimer: ReturnType<typeof setTimeout> | null = null;

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
  }

  async removeSession(session: Partial<IAgentScopeRuntimeWebUISession>) {
    if (!session.id) return [...this._sessions];

    const { id: sessionId } = session;

    const existing = this._sessions.find((s) => s.id === sessionId) as
      | ExtendedSession
      | undefined;

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
