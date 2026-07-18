import {
  AgentScopeRuntimeWebUI,
  IAgentScopeRuntimeWebUIOptions,
  type IAgentScopeRuntimeWebUIRef,
} from "@agentscope-ai/chat";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button, Modal, Result, Tooltip, Drawer } from "antd";
import { useAppMessage } from "../../hooks/useAppMessage";
import {
  ExclamationCircleOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import { SparkCopyLine, SparkAttachmentLine } from "@agentscope-ai/icons";
import { usePlugins } from "../../plugins/PluginContext";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import sessionApi from "./sessionApi";
import defaultConfig, { getDefaultConfig } from "./OptionsPanel/defaultConfig";
import { chatApi } from "../../api/modules/chat";
import { getApiUrl } from "../../api/config";
import { buildAuthHeaders } from "../../api/authHeaders";
import { providerApi } from "../../api/modules/provider";
import type { ProviderInfo, ModelInfo } from "../../api/types";
import { useTheme } from "../../contexts/ThemeContext";
import useIsMobile from "../../hooks/useIsMobile";
import { useUser } from "../../contexts/UserContext";
import { useAgentStore } from "../../stores/agentStore";
import { useChatAnywhereInput, useChatAnywhereSessionsState } from "@agentscope-ai/chat";
import styles from "./index.module.less";
import { IconButton } from "@agentscope-ai/design";
import ChatSessionInitializer from "./components/ChatSessionInitializer";
import ChatSessionHeader from "./components/ChatSessionHeader";
import ChatErrorBoundary from "./components/ChatErrorBoundary";
import { ApprovalCard } from "../../components/ApprovalCard/ApprovalCard";
import { commandsApi } from "../../api/modules/commands";
import { useApprovalContext } from "../../contexts/ApprovalContext";
import { planApi } from "../../api/modules/plan";
import {
  ChatDisplayConfigContext,
} from "./components/SimplifiedResponseCard";
import ChatDisplaySettings from "./components/ChatDisplaySettings";
import { useChatDisplayFromUser } from "../../hooks/useChatDisplayFromUser";
import EnhancedToolCallCard from "./components/EnhancedToolCallCard";
import CoApisDeepThinking from "./components/CoApisDeepThinking";
import OnboardingModal from "../../components/OnboardingModal";
import { useRecommendations } from "../../components/Recommendation";
import { ChatToolbarSidebar, useToolbarState, ChatInputFooter, ModelCapabilityTag } from "../../components/Chat";

interface ApprovalMessageData {
  requestId: string;
  sessionId: string;
  rootSessionId?: string;
  agentId: string;
  toolName: string;
  severity: string;
  findingsCount: number;
  findingsSummary: string;
  toolParams: Record<string, unknown>;
  createdAt: number;
  timeoutSeconds: number;
}

import {
  toDisplayUrl,
  copyText,
  extractCopyableText,
  buildModelError,
  normalizeContentUrls,
  extractTextFromMessage,
  setTextareaValue,
  type CopyableResponse,
  type RuntimeLoadingBridgeApi,
} from "./utils";

const CHAT_ATTACHMENT_MAX_MB = 10;

interface SessionInfo {
  session_id?: string;
  user_id?: string;
  channel?: string;
}

interface CustomWindow extends Window {
  currentSessionId?: string;
  currentUserId?: string;
  currentChannel?: string;
}

declare const window: CustomWindow;

interface CommandSuggestion {
  command: string;
  value: string;
  description: string;
}

// ---------------------------------------------------------------------------
// Enhanced tool render config — 注册 EnhancedToolCallCard 到所有已知工具
// ---------------------------------------------------------------------------
const _ENHANCED_TOOL_NAMES = [
  'execute_shell_command',
  'read_file', 'write_file', 'edit_file',
  'grep_search', 'glob_search',
  'web_search', 'browser_use',
  'memory_search',
  'send_file_to_user',
  'get_current_time', 'set_user_timezone',
  'chat_with_agent', 'submit_to_agent', 'check_agent_task', 'spawn_subagent',
  'create_plan', 'revise_current_plan', 'finish_plan', 'view_historical_plans', 'recover_historical_plan',
  'get_token_usage',
  'view_image', 'view_video', 'desktop_screenshot',
  'list_agents',
];
const _enhancedToolRenderConfig: Record<string, React.FC<any>> = {};
for (const name of _ENHANCED_TOOL_NAMES) {
  _enhancedToolRenderConfig[name] = EnhancedToolCallCard;
}

function messageRequestsHistoryClear(message: unknown): boolean {
  if (!message || typeof message !== "object") return false;
  const metadata = (message as Record<string, unknown>).metadata;
  if (!metadata || typeof metadata !== "object") return false;

  const meta = metadata as Record<string, unknown>;
  if (meta.clear_history === true) return true;

  const nested = meta.metadata;
  return (
    !!nested &&
    typeof nested === "object" &&
    (nested as Record<string, unknown>).clear_history === true
  );
}

function payloadRequestsHistoryClear(payload: unknown): boolean {
  if (!payload || typeof payload !== "object") return false;

  const record = payload as Record<string, unknown>;
  const candidates: unknown[] = [];

  if (record.object === "message") {
    candidates.push(record);
  }

  if (record.object === "response" && Array.isArray(record.output)) {
    candidates.push(...record.output);
  }

  return candidates.some(messageRequestsHistoryClear);
}

function payloadCompletesResponse(payload: unknown): boolean {
  if (!payload || typeof payload !== "object") return false;

  const record = payload as Record<string, unknown>;
  if (record.object !== "response") return false;
  
  // Recognize ALL terminal statuses, not just "completed".
  // The backend may send "failed" for normal completions in some configurations.
  const status = record.status as string;
  return status === "completed" || status === "failed" || status === "canceled";
}

// ---------------------------------------------------------------------------
// Plugin call message type tracker
// ---------------------------------------------------------------------------
// Tracks which message IDs are PLUGIN_CALL so we can adapt their content
// deltas (add data.call_id/name) for the library's mergeToolMessages.
const _pluginCallMsgTypes = new Map<string, string>();

function renderSuggestionLabel(command: string, description: string) {
  return (
    <div className={styles.suggestionLabel}>
      <span className={styles.suggestionCommand}>{command}</span>
      <span className={styles.suggestionDescription}>{description}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DEFAULT_USER_ID = "default";
const DEFAULT_CHANNEL = "console";

// ---------------------------------------------------------------------------
// Active model cache (avoid redundant getActiveModels calls per chat request)
// ---------------------------------------------------------------------------
const _activeModelCache: {
  key: string;
  data: Awaited<ReturnType<typeof providerApi.getActiveModels>> | null;
  ts: number;
} = { key: "", data: null, ts: 0 };
const ACTIVE_MODEL_CACHE_TTL_MS = 30_000; // 30 seconds

async function getActiveModelCached(
  agentId: string | undefined,
): Promise<Awaited<ReturnType<typeof providerApi.getActiveModels>> | null> {
  const key = agentId || "__global__";
  const now = Date.now();
  if (_activeModelCache.key === key && _activeModelCache.data && now - _activeModelCache.ts < ACTIVE_MODEL_CACHE_TTL_MS) {
    return _activeModelCache.data;
  }
  const data = await providerApi.getActiveModels({
    scope: "effective",
    agent_id: agentId,
  });
  _activeModelCache.key = key;
  _activeModelCache.data = data;
  _activeModelCache.ts = now;
  return data;
}

// ---------------------------------------------------------------------------
// Custom hooks
// ---------------------------------------------------------------------------

/** Handle IME composition events to prevent premature Enter key submission. */
function useIMEComposition(isChatActive: () => boolean) {
  const isComposingRef = useRef(false);

  useEffect(() => {
    const handleCompositionStart = () => {
      if (!isChatActive()) return;
      isComposingRef.current = true;
    };

    const handleCompositionEnd = () => {
      if (!isChatActive()) return;
      // Small delay for Safari on macOS, which fires keydown after
      // compositionend within the same event loop tick.  Keep this as
      // short as possible so fast typists who hit Space+Enter in quick
      // succession are not blocked.
      setTimeout(() => {
        isComposingRef.current = false;
      }, 50);
    };

    const suppressImeEnter = (e: KeyboardEvent) => {
      if (!isChatActive()) return;
      const target = e.target as HTMLElement;
      if (target?.tagName === "TEXTAREA" && e.key === "Enter" && !e.shiftKey) {
        // e.isComposing is the standard flag; isComposingRef covers the
        // post-compositionend grace period needed by Safari.
        if (isComposingRef.current || (e as any).isComposing) {
          e.stopPropagation();
          e.stopImmediatePropagation();
          e.preventDefault();
          return false;
        }
      }
    };

    document.addEventListener("compositionstart", handleCompositionStart, true);
    document.addEventListener("compositionend", handleCompositionEnd, true);
    // Listen on both keydown (Safari) and keypress (legacy) in capture phase.
    document.addEventListener("keydown", suppressImeEnter, true);
    document.addEventListener("keypress", suppressImeEnter, true);

    return () => {
      document.removeEventListener(
        "compositionstart",
        handleCompositionStart,
        true,
      );
      document.removeEventListener(
        "compositionend",
        handleCompositionEnd,
        true,
      );
      document.removeEventListener("keydown", suppressImeEnter, true);
      document.removeEventListener("keypress", suppressImeEnter, true);
    };
  }, [isChatActive]);

  return isComposingRef;
}

/** Fetch and track multimodal capabilities for the active model. */
function useMultimodalCapabilities(
  refreshKey: number,
  locationPathname: string,
  isChatActive: () => boolean,
  selectedAgent: string,
) {
  const [multimodalCaps, setMultimodalCaps] = useState<{
    supportsMultimodal: boolean;
    supportsImage: boolean;
    supportsVideo: boolean;
  }>({ supportsMultimodal: false, supportsImage: false, supportsVideo: false });

  const fetchMultimodalCaps = useCallback(async () => {
    try {
      const [providers, activeModels] = await Promise.all([
        providerApi.listProviders(),
        getActiveModelCached(selectedAgent),
      ]);
      const activeProviderId = activeModels?.active_llm?.provider_id;
      const activeModelId = activeModels?.active_llm?.model;
      if (!activeProviderId || !activeModelId) {
        setMultimodalCaps({
          supportsMultimodal: false,
          supportsImage: false,
          supportsVideo: false,
        });
        return;
      }
      const provider = (providers as ProviderInfo[]).find(
        (p) => p.id === activeProviderId,
      );
      if (!provider) {
        setMultimodalCaps({
          supportsMultimodal: false,
          supportsImage: false,
          supportsVideo: false,
        });
        return;
      }
      const allModels: ModelInfo[] = [...(provider.models ?? [])];
      const model = allModels.find((m) => m.id === activeModelId);
      setMultimodalCaps({
        supportsMultimodal: model?.supports_multimodal ?? false,
        supportsImage: model?.supports_image ?? false,
        supportsVideo: model?.supports_video ?? false,
      });
    } catch {
      setMultimodalCaps({
        supportsMultimodal: false,
        supportsImage: false,
        supportsVideo: false,
      });
    }
  }, [selectedAgent]);

  // Fetch caps on mount and whenever refreshKey changes
  useEffect(() => {
    fetchMultimodalCaps();
  }, [fetchMultimodalCaps, refreshKey]);

  // Also poll caps when navigating back to chat
  useEffect(() => {
    if (isChatActive()) {
      fetchMultimodalCaps();
    }
  }, [locationPathname, fetchMultimodalCaps, isChatActive]);

  // Listen for model-switched event from ModelSelector
  useEffect(() => {
    const handler = () => {
      fetchMultimodalCaps();
    };
    window.addEventListener("model-switched", handler);
    return () => window.removeEventListener("model-switched", handler);
  }, [fetchMultimodalCaps]);

  return multimodalCaps;
}

function useMessageHistoryNavigation(
  chatRef: React.RefObject<IAgentScopeRuntimeWebUIRef | null>,
  isChatActive: () => boolean,
  isComposingRef: React.RefObject<boolean>,
) {
  const historyIndexRef = useRef<number>(-1);
  const draftRef = useRef<string>("");

  /** Cached user messages to avoid re-computing on every keydown */
  const userMessagesCacheRef = useRef<string[]>([]);
  const cachedMessageCountRef = useRef<number>(0);

  const getUserMessagesWithText = useCallback((): string[] => {
    if (!chatRef.current?.messages?.getMessages) return [];

    const allMessages = chatRef.current.messages.getMessages();
    if (!Array.isArray(allMessages)) return [];

    const currentCount = allMessages.length;
    if (
      userMessagesCacheRef.current.length > 0 &&
      cachedMessageCountRef.current === currentCount
    ) {
      return userMessagesCacheRef.current;
    }

    const userMessages = allMessages
      .filter((msg) => msg.role === "user")
      .map((msg) => extractTextFromMessage(msg))
      .filter((text) => text.trim().length > 0);

    userMessagesCacheRef.current = userMessages;
    cachedMessageCountRef.current = currentCount;

    return userMessages;
  }, [chatRef]);

  interface MessageResult {
    index: number;
    text: string;
  }

  const findMessageInDirection = (
    messages: string[],
    startIndex: number,
    direction: 1 | -1,
  ): MessageResult | null => {
    const MAX_LOOKUP = 100;
    let lookupIndex = startIndex;
    let steps = 0;

    while (
      lookupIndex >= 0 &&
      lookupIndex < messages.length &&
      steps < MAX_LOOKUP
    ) {
      const messageText = messages[messages.length - 1 - lookupIndex];
      if (messageText) {
        return { index: lookupIndex, text: messageText };
      }
      lookupIndex += direction;
      steps += 1;
    }

    return null;
  };

  const isSuggestionPopupOpen = (textarea: HTMLTextAreaElement): boolean =>
    textarea.value.startsWith("/");

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!isChatActive()) return;

      const target = e.target as HTMLElement;
      const isChatSender =
        target?.tagName === "TEXTAREA" &&
        target?.closest('[class*="sender"]') !== null;

      if (!isChatSender) return;
      if (isComposingRef.current || (e as any).isComposing) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;

      const textarea = target as HTMLTextAreaElement;
      const hasSelection = textarea.selectionStart !== textarea.selectionEnd;
      if (hasSelection) return;

      const userMessages = getUserMessagesWithText();

      if (e.key === "ArrowUp") {
        if (isSuggestionPopupOpen(textarea)) return;

        const cursorPosition = textarea.selectionStart || 0;
        const textBeforeCursor = textarea.value.substring(0, cursorPosition);
        const lineBreaks = textBeforeCursor.split("\n").length - 1;
        if (lineBreaks > 0) return;

        if (userMessages.length === 0) return;

        if (historyIndexRef.current === -1) {
          draftRef.current = textarea.value;
        }

        const startIndex = historyIndexRef.current + 1;
        const messageText = findMessageInDirection(userMessages, startIndex, 1);

        if (messageText) {
          e.preventDefault();
          historyIndexRef.current = messageText.index;
          setTextareaValue(textarea, messageText.text);
        }
      } else if (e.key === "ArrowDown") {
        if (historyIndexRef.current < 0) return;

        const cursorPosition = textarea.selectionStart || 0;
        const textAfterCursor = textarea.value.substring(cursorPosition);
        if (textAfterCursor.includes("\n")) return;

        const startIndex = historyIndexRef.current - 1;
        const messageText = findMessageInDirection(
          userMessages,
          startIndex,
          -1,
        );

        if (messageText) {
          e.preventDefault();
          historyIndexRef.current = messageText.index;
          setTextareaValue(textarea, messageText.text);
        } else {
          e.preventDefault();
          historyIndexRef.current = -1;
          setTextareaValue(textarea, draftRef.current);
        }
      }
    };

    const handleFocus = (e: FocusEvent) => {
      const target = e.target as HTMLElement;
      const isChatSender =
        target?.tagName === "TEXTAREA" &&
        target?.closest('[class*="sender"]') !== null;

      if (isChatSender) {
        historyIndexRef.current = -1;
        draftRef.current = "";
      }
    };

    document.addEventListener("keydown", handleKeyDown, true);
    document.addEventListener("focusin", handleFocus, true);

    return () => {
      document.removeEventListener("keydown", handleKeyDown, true);
      document.removeEventListener("focusin", handleFocus, true);
    };
  }, [isChatActive, isComposingRef, getUserMessagesWithText]);
}

function RuntimeLoadingBridge({
  bridgeRef,
}: {
  bridgeRef: { current: RuntimeLoadingBridgeApi | null };
}) {
  const { setLoading, getLoading } = useChatAnywhereInput(
    (value) =>
      ({
        setLoading: value.setLoading,
        getLoading: value.getLoading,
      }) as RuntimeLoadingBridgeApi,
  );

  useEffect(() => {
    if (!setLoading || !getLoading) {
      bridgeRef.current = null;
      return;
    }

    bridgeRef.current = {
      setLoading,
      getLoading,
    };
    // Expose on window as fallback for responseParser completion handler
    (window as any).__chatSetLoading = setLoading;

    return () => {
      if (bridgeRef.current?.setLoading === setLoading) {
        bridgeRef.current = null;
      }
      if ((window as any).__chatSetLoading === setLoading) {
        delete (window as any).__chatSetLoading;
      }
    };
  }, [getLoading, setLoading, bridgeRef]);

  return null;
}

export default function ChatPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const { isDark } = useTheme();
  const isMobile = useIsMobile();
  const { user } = useUser();
  
  // 读取场景参数（嵌入式模式通过window注入）
  const chatMode = useMemo(() => {
    return (window as any).__CHAT_MODE__ || 'full';
  }, []);
  
  const isEmbeddedMode = chatMode === 'embedded';
  
  const sceneSessionId = useMemo(() => {
    return (window as any).__CHAT_SESSION_ID__;
  }, []);
  
  const sceneId = useMemo(() => {
    return (window as any).__CHAT_SCENE_ID__;
  }, []);
  
  // 场景ID用于后续场景智能体相关逻辑
  useEffect(() => {
    if (sceneId && isEmbeddedMode) {
      console.log('[Chat] Scene mode activated:', sceneId);
    }
  }, [sceneId, isEmbeddedMode]);
  
  const sceneName = useMemo(() => {
    return (window as any).__CHAT_SCENE_NAME__;
  }, []);
  
  const sceneWelcomeMessage = useMemo(() => {
    return (window as any).__CHAT_WELCOME_MESSAGE__;
  }, []);
  
  const sceneShowToolbar = useMemo(() => {
    const val = (window as any).__CHAT_SHOW_TOOLBAR__;
    return val !== undefined ? val : true;
  }, []);
  
  const chatId = useMemo(() => {
    // 嵌入式模式：使用场景会话ID
    if (isEmbeddedMode && sceneSessionId) {
      return sceneSessionId;
    }
    // 完整模式：从路由获取
    const match = location.pathname.match(/^\/chat\/(.+)$/);
    return match?.[1];
  }, [isEmbeddedMode, sceneSessionId, location.pathname]);
  const [showModelPrompt, setShowModelPrompt] = useState(false);
  const { selectedAgent } = useAgentStore();
  const { toolRenderConfig } = usePlugins();
  const [refreshKey, setRefreshKey] = useState(0);
  const runtimeLoadingBridgeRef = useRef<RuntimeLoadingBridgeApi | null>(null);
  const { message } = useAppMessage();
  const { approvals } = useApprovalContext();
  const [approvalRequests, setApprovalRequests] = useState<
    Map<string, ApprovalMessageData>
  >(new Map());
  const [planEnabled, setPlanEnabled] = useState(false);

  // Onboarding state
  const [showOnboarding, setShowOnboarding] = useState(false);

  // Chat display configuration — synced with UserContext (backend preferences)
  const {
    displayConfig,
    setDisplayConfig,
  } = useChatDisplayFromUser();
  const [showDisplaySettings, setShowDisplaySettings] = useState(false);

  // 工具栏状态管理
  const {
    visible: toolbarOpen,
    closeToolbar,
    toggleToolbar,
    selectedFiles,
    selectedKnowledge,
    setSelectedFiles,
    setSelectedKnowledge,
  } = useToolbarState();

  // 工具栏功能回调
  const handleSettingsClick = useCallback(() => {
    setShowDisplaySettings(true);
  }, []);

  // Sync authenticated username to window for AgentScope Runtime session API
  // IMPORTANT: Set immediately on mount to ensure window.currentUserId is available
  // before any API calls that depend on it (e.g., sessionApi.getSessionList)
  useEffect(() => {
    if (user?.username) {
      window.currentUserId = user.username;
      console.log(`[Chat] Set window.currentUserId = ${user.username}`);
    }
  }, [user?.username]);
  
  // Also set on initial mount if user is already loaded
  useEffect(() => {
    if (user?.username && !window.currentUserId) {
      window.currentUserId = user.username;
      console.log(`[Chat] Initial mount: Set window.currentUserId = ${user.username}`);
    }
  }, []); // Run once on mount

  useEffect(() => {
    let cancelled = false;
    planApi
      .getPlanConfig(selectedAgent || undefined)
      .then((cfg) => {
        if (!cancelled) setPlanEnabled(cfg.enabled);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [selectedAgent]);

  // Check for first login and show onboarding
  useEffect(() => {
    const isFirstLogin = localStorage.getItem("coapis_first_login") === "true";
    if (isFirstLogin) {
      setShowOnboarding(true);
      localStorage.removeItem("coapis_first_login");
    }
  }, []);

  // Dynamic recommendations for welcome prompts
  const { recommendations: dynamicRecommendations } = useRecommendations({
    scene: "chat_welcome",
    limit: 4,
    enabled: true,
  });

  const isChatActiveRef = useRef(false);
  isChatActiveRef.current =
    location.pathname === "/" || location.pathname.startsWith("/chat");

  const isChatActive = useCallback(() => isChatActiveRef.current, []);

  // Consume approvals from Context and filter by current session
  useEffect(() => {
    // Get current session ID from multiple sources
    // Priority: chatId (UUID from URL) > window.currentSessionId
    // chatId is the actual chat UUID used by backend for approval routing
    const currentSessionId = chatId || window.currentSessionId || "";

    // Filter approvals by root_session_id (includes children sessions)
    console.debug(
      "[Approval] Filtering approvals:",
      "currentSessionId=",
      currentSessionId,
      "chatId=",
      chatId,
      "window.currentSessionId=",
      window.currentSessionId,
      "approvals=",
      approvals.map((a) => ({
        tool: a.tool_name,
        session: a.session_id.slice(0, 8),
        root: a.root_session_id.slice(0, 8),
      })),
    );

    // If no session ID yet, check if we have approvals that could tell us the session
    // (e.g., first message sent, approval arrives before session ID is set in window)
    let effectiveSessionId = currentSessionId;
    if (!effectiveSessionId && approvals.length > 0) {
      // Use the root_session_id from the first approval as a hint
      // This handles the race condition where approval arrives before session ID is propagated
      effectiveSessionId = approvals[0].root_session_id;
      console.log(
        "[Approval] No session ID yet, using first approval's root_session_id:",
        effectiveSessionId,
      );
    }

    const sessionApprovals = effectiveSessionId
      ? approvals.filter(
          (approval) => approval.root_session_id === effectiveSessionId,
        )
      : approvals; // Show all if no session ID (fallback)

    console.debug(
      "[Approval] After filtering:",
      sessionApprovals.length,
      "approval(s)",
    );

    // Convert to map for display
    const newMap = new Map<string, ApprovalMessageData>();
    for (const approval of sessionApprovals) {
      newMap.set(approval.request_id, {
        requestId: approval.request_id,
        sessionId: approval.session_id,
        rootSessionId: approval.root_session_id,
        agentId: approval.agent_id,
        toolName: approval.tool_name,
        severity: approval.severity,
        findingsCount: approval.findings_count,
        findingsSummary: approval.findings_summary,
        toolParams: approval.tool_params,
        createdAt: approval.created_at,
        timeoutSeconds: approval.timeout_seconds,
      });
    }

    setApprovalRequests(newMap);
  }, [approvals, chatId]);

  const handleApprove = useCallback(
    async (requestId: string) => {
      console.log("[Approval] handleApprove called:", requestId);
      console.log(
        "[Approval] Current requests map size:",
        approvalRequests.size,
      );
      const request = approvalRequests.get(requestId);
      if (!request) {
        console.error("[Approval] Request not found:", requestId);
        return;
      }

      // Use currentSessionId (root session) instead of request.sessionId (sub-agent session)
      // Priority: chatId (UUID) > window.currentSessionId
      const rootSessionId = chatId || window.currentSessionId || "";
      console.log("[Approval] Sending approve command:", {
        requestId,
        rootSessionId,
        subAgentSessionId: request.sessionId,
      });

      try {
        // Add exit animation class
        const cardElement = document.querySelector(
          `[data-approval-id="${requestId}"]`,
        );
        if (cardElement) {
          cardElement.classList.add("approvalCardExit");
        }

        await commandsApi.sendApprovalCommand(
          "approve",
          requestId,
          rootSessionId,
        );
        console.log("[Approval] Approve command sent successfully");
        message.success(t("approval.approved"));

        // Delay removal to let animation complete
        // Backend will remove from pending list, next poll will update UI
        setTimeout(() => {
          setApprovalRequests((prev) => {
            const next = new Map(prev);
            next.delete(requestId);
            return next;
          });
        }, 300); // Match animation duration
      } catch (error) {
        message.error(t("approval.approveFailed"));
        console.error("[Approval] Failed to approve:", error);
      }
    },
    [approvalRequests, chatId, t, message],
  );

  const handleDeny = useCallback(
    async (requestId: string) => {
      const request = approvalRequests.get(requestId);
      if (!request) return;

      // Use currentSessionId (root session) instead of request.sessionId (sub-agent session)
      const rootSessionId = window.currentSessionId || chatId || "";

      try {
        // Add exit animation class
        const cardElement = document.querySelector(
          `[data-approval-id="${requestId}"]`,
        );
        if (cardElement) {
          cardElement.classList.add("approvalCardExit");
        }

        await commandsApi.sendApprovalCommand("deny", requestId, rootSessionId);
        message.success(t("approval.denied"));

        // Delay removal to let animation complete
        // Backend will remove from pending list, next poll will update UI
        setTimeout(() => {
          setApprovalRequests((prev) => {
            const next = new Map(prev);
            next.delete(requestId);
            return next;
          });
        }, 300); // Match animation duration
      } catch (error) {
        message.error(t("approval.denyFailed"));
        console.error("Failed to deny:", error);
      }
    },
    [approvalRequests, chatId, t, message],
  );

  // Use custom hooks for better separation of concerns
  const isComposingRef = useIMEComposition(isChatActive);
  const multimodalCaps = useMultimodalCapabilities(
    refreshKey,
    location.pathname,
    isChatActive,
    selectedAgent,
  );

  const lastSessionIdRef = useRef<string | null>(null);
  /** Tracks the stale auto-selected session ID that was skipped on init, so we can suppress its late-arriving onSessionSelected callback. */
  const staleAutoSelectedIdRef = useRef<string | null>(null);
  /** When true, skip the next onSessionSelected callback — set by ChatSessionInitializer to break the URL↔session sync loop. */
  const skipNextSessionSelectedRef = useRef(false);
  const chatIdRef = useRef(chatId);
  const navigateRef = useRef(navigate);
  const chatRef = useRef<IAgentScopeRuntimeWebUIRef>(null);
  const pendingClearHistoryRef = useRef(false);
  const requestSessionIdRef = useRef<string | null>(null);

  useMessageHistoryNavigation(chatRef, isChatActive, isComposingRef);
  chatIdRef.current = chatId;
  navigateRef.current = navigate;

  const scheduleHistoryClear = useCallback(() => {
    queueMicrotask(() => {
      if (!pendingClearHistoryRef.current) return;
      pendingClearHistoryRef.current = false;
      chatRef.current?.messages.removeAllMessages();
    });
  }, []);

  // Sync sessionApi internal state with the library's React context so that
  // components reading useChatAnywhereSessionsState() (e.g. ChatSessionHeader)
  // get updated session names after backend auto-rename.
  const { setSessions } = useChatAnywhereSessionsState();

  // Tell sessionApi which session to put first in getSessionList, so the library's
  // useMount auto-selects the correct session without an extra getSession round-trip.
  if (chatId && sessionApi.preferredChatId !== chatId) {
    sessionApi.preferredChatId = chatId;
  }

  // Register session API event callbacks for URL synchronization

  useEffect(() => {
    sessionApi.onSessionIdResolved = (realId) => {
      if (!isChatActiveRef.current) return;
      // Update URL when realId is resolved, regardless of current chatId
      // (chatId may be undefined if URL was cleared in onSessionCreated)
      lastSessionIdRef.current = realId;
      navigateRef.current(`/chat/${realId}`, { replace: true });
    };

    sessionApi.onSessionRemoved = (removedId) => {
      if (!isChatActiveRef.current) return;
      // Clear URL when current session is removed
      // Check if removed session matches current session (by realId or sessionId)
      const currentRealId = sessionApi.getRealIdForSession(
        chatIdRef.current || "",
      );
      if (chatIdRef.current === removedId || currentRealId === removedId) {
        lastSessionIdRef.current = null;
        navigateRef.current("/chat", { replace: true });
      }
    };

    sessionApi.onSessionSelected = (
      sessionId: string | null | undefined,
      realId: string | null,
    ) => {
      if (!isChatActiveRef.current) return;
      
      // Get target ID
      const targetId = realId || sessionId;
      
      // Clear previous session's SSE filtering state
      if (targetId && targetId !== requestSessionIdRef.current) {
        console.log("[Chat] Session changed, clearing SSE filter state");
        requestSessionIdRef.current = null;
      }

      // Skip when ChatSessionInitializer set currentSessionId — breaks the URL↔session loop.
      if (skipNextSessionSelectedRef.current) {
        skipNextSessionSelectedRef.current = false;
        return;
      }

      // Update URL when session is selected and different from current
      if (!targetId) return;

      // If a preferred chatId from the URL exists and no navigation has happened yet,
      // skip the library's initial auto-selection (always first session).
      // ChatSessionInitializer will apply the correct selection afterward.
      if (
        chatIdRef.current &&
        lastSessionIdRef.current === null &&
        targetId !== chatIdRef.current
      ) {
        lastSessionIdRef.current = targetId;
        // Record the stale ID so its delayed getSession callback is also suppressed.
        staleAutoSelectedIdRef.current = targetId;
        return;
      }

      // Suppress the stale getSession callback that arrives after the correct session loads.
      if (
        staleAutoSelectedIdRef.current &&
        staleAutoSelectedIdRef.current === targetId
      ) {
        staleAutoSelectedIdRef.current = null;
        return;
      }

      if (targetId !== lastSessionIdRef.current) {
        lastSessionIdRef.current = targetId;
        navigateRef.current(`/chat/${targetId}`, { replace: true });
      }
    };

    sessionApi.onSessionCreated = (localId: string) => {
      if (!isChatActiveRef.current) return;
      // createSession() already calls api.createChat() and sets realId.
      // Navigate to the real backend UUID immediately so page refresh survives.
      const realId = sessionApi.getRealIdForSession(localId);
      const targetId = realId || localId;
      lastSessionIdRef.current = targetId;
      navigateRef.current(`/chat/${targetId}`, { replace: true });
    };

    // Sync sessionApi's internal session list with the library's React state,
    // so ChatSessionHeader re-renders with updated session names (auto-rename).
    sessionApi.onSessionListUpdated = (sessions) => {
      setSessions(sessions);
    };

    // When a new session's realId (backend UUID) is resolved during createSession,
    // update chatIdRef so the first message is sent with the correct chat_id.
    // Without this, the first message would have chat_id=undefined and the
    // backend might not associate it with the correct chat.
    sessionApi.onSessionRealIdResolved = (_localId: string, realId: string) => {
      chatIdRef.current = realId;
    };

    return () => {
      sessionApi.onSessionIdResolved = null;
      sessionApi.onSessionRemoved = null;
      sessionApi.onSessionSelected = null;
      sessionApi.onSessionCreated = null;
      sessionApi.onSessionListUpdated = null;
      sessionApi.onSessionRealIdResolved = null;
    };
  }, []);

  // Setup multimodal capabilities tracking via custom hook

  // Refresh chat when selectedAgent changes, preserving last active chat per agent
  const { setLastChatId, getLastChatId } = useAgentStore();
  const prevSelectedAgentRef = useRef(selectedAgent);
  useEffect(() => {
    const prevAgent = prevSelectedAgentRef.current;
    if (prevAgent !== selectedAgent && prevAgent !== undefined) {
      // Save current chat ID for the agent we're leaving
      // Priority: URL chatId > lastSessionIdRef > currentSession.id
      const currentSession = sessionApi.currentSession;
      const currentChatId =
        chatIdRef.current ||
        lastSessionIdRef.current ||
        (currentSession?.id !== currentSession?.realId ? currentSession?.realId : currentSession?.id) ||
        undefined;
      if (currentChatId && prevAgent) {
        console.log(`[Agent Switch] Saving chat ${currentChatId} for agent ${prevAgent}`);
        setLastChatId(prevAgent, currentChatId);
      } else {
        console.log(`[Agent Switch] No chat to save for agent ${prevAgent} (chatId=${chatIdRef.current}, lastSessionId=${lastSessionIdRef.current})`);
      }

      // Clear cached session list so it re-fetches for the new agent
      sessionApi.invalidateSessionList();

      // Restore last chat ID for the agent we're switching to
      const restored = getLastChatId(selectedAgent);
      if (restored) {
        console.log(`[Agent Switch] Restoring chat ${restored} for agent ${selectedAgent}`);
        // Validate that this chat belongs to the current user AND agent before restoring
        // This prevents cross-user and cross-agent data leakage from stale localStorage data
        (async () => {
          try {
            const chatSpec = await chatApi.getChat(restored, { agent_id: selectedAgent });
            // Import getCurrentUsername dynamically to avoid circular deps
            const { getCurrentUsername } = await import("../../api/config");
            const currentUser = getCurrentUsername();
            const chatAgentId = chatSpec.agent_id || "";
            
            // Validate both user_id and agent_id
            if (chatSpec.user_id !== currentUser || chatAgentId !== selectedAgent) {
              console.warn(
                `Chat ${restored} belongs to user=${chatSpec.user_id}/agent=${chatAgentId}, ` +
                `not user=${currentUser}/agent=${selectedAgent}, clearing`
              );
              setLastChatId(selectedAgent, "");
              navigateRef.current("/chat", { replace: true });
            } else {
              // Valid chat, proceed with restore
              console.log(`[Agent Switch] Restored chat ${restored} successfully`);
              navigateRef.current(`/chat/${restored}`, { replace: true });
              sessionApi.preferredChatId = restored;
            }
          } catch (error) {
            // Chat not found or access denied, clear stale data
            console.warn(`Failed to verify chat ${restored}, clearing:`, error);
            setLastChatId(selectedAgent, "");
            navigateRef.current("/chat", { replace: true });
          }
        })();
      } else {
        console.log(`[Agent Switch] No saved chat for agent ${selectedAgent}, starting fresh`);
        navigateRef.current("/chat", { replace: true });
      }
      // Don't clear lastSessionIdRef - let the new session initialize naturally
      
      setRefreshKey((prev) => prev + 1);
    }
    prevSelectedAgentRef.current = selectedAgent;
  }, [selectedAgent, setLastChatId, getLastChatId]);

  const copyResponse = useCallback(
    async (response: CopyableResponse) => {
      try {
        await copyText(extractCopyableText(response));
        message.success(t("common.copied"));
      } catch {
        message.error(t("common.copyFailed"));
      }
    },
    [t],
  );

  const customFetch = useCallback(
    async (data: {
      input?: Array<Record<string, unknown>>;
      biz_params?: Record<string, unknown>;
      signal?: AbortSignal;
    }): Promise<Response> => {
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
        ...buildAuthHeaders(),
      };

      try {
        const activeModels = await getActiveModelCached(selectedAgent);
        if (
          !activeModels?.active_llm?.provider_id ||
          !activeModels?.active_llm?.model
        ) {
          setShowModelPrompt(true);
          return buildModelError();
        }
      } catch {
        setShowModelPrompt(true);
        return buildModelError();
      }

      const { input = [], biz_params } = data;
      const session: SessionInfo = input[input.length - 1]?.session || {};
      const lastInput = input.slice(-1);
      const lastMsg = lastInput[0];
      
      // 构建基础 content
      let rewrittenContent: any[] = [];
      if (Array.isArray(lastMsg?.content)) {
        rewrittenContent = lastMsg.content.map(normalizeContentUrls);
      } else if (lastMsg?.content) {
        rewrittenContent = [{ type: "text", text: String(lastMsg.content) }];
      }
      
      // 添加文件引用（供后端处理）
      // 注意：文件提示信息通过 biz_params 传递，不直接添加到 content 中
      // 这样可以保持用户消息的原始内容，避免污染聊天历史
      if (selectedFiles.length > 0) {
        // 添加文件引用（file:// URL）供后端工具处理
        // 后端返回的 path 已经是相对于 workspace/files/ 的路径
        selectedFiles.forEach(file => {
          // 移除开头的 /，直接传递相对路径
          const filePath = file.path.startsWith('/') 
            ? file.path.slice(1) 
            : file.path;
          
          rewrittenContent.push({
            type: "file",
            source: {
              url: `file://${filePath}`,
            },
            filename: file.name,
          });
        });
      }
      
      // 添加知识库引用（在 biz_params 中传递）
      const knowledgeRefs = selectedKnowledge.length > 0 
        ? selectedKnowledge.map(kb => ({ id: kb.id, name: kb.name }))
        : undefined;
      
      // 文件引用信息（通过 biz_params 传递，后端动态注入到 AI 上下文）
      const fileRefs = selectedFiles.length > 0 
        ? selectedFiles.map(f => ({ 
            name: f.name, 
            path: f.path,
            type: f.type 
          }))
        : undefined;
      
      const rewrittenInput = lastMsg
        ? [
            {
              role: lastMsg.role,
              type: lastMsg.type,
              content: rewrittenContent,
              session: lastMsg.session,
              // 注意：不复制 cards 等只读属性
            },
          ]
        : lastInput;

      const requestBody = {
        input: rewrittenInput,
        session_id: window.currentSessionId || session?.session_id || "",
        user_id: window.currentUserId || session?.user_id || DEFAULT_USER_ID,
        channel: window.currentChannel || session?.channel || DEFAULT_CHANNEL,
        stream: true,
        biz_params: {
          agent_id: selectedAgent,
          ...biz_params,
          // 添加知识库引用
          ...(knowledgeRefs && { knowledge_bases: knowledgeRefs }),
          // 添加文件引用（用于后端动态注入提示，避免污染用户消息）
          ...(fileRefs && { selected_files: fileRefs }),
        },
        // Pass chat_id (UUID) so backend can persist messages to the correct chat
        // instead of matching by session_id (which is shared across all console chats).
        chat_id: chatIdRef.current || undefined,
      };

      // Record current session_id for SSE filtering
      const currentSessionId = requestBody.session_id || requestBody.chat_id || null;
      requestSessionIdRef.current = currentSessionId;
      console.log("[Chat] Request session_id:", currentSessionId);

      const response = await fetch(getApiUrl("/console/chat"), {
        method: "POST",
        headers,
        body: JSON.stringify(requestBody),
        signal: data.signal,
      });

      // Schedule a delayed session list refresh after the SSE stream completes.
      // The backend auto-renames chats from the first user message in the
      // finally block (after the stream ends), so we need to refresh the
      // session list to pick up the new name.
      sessionApi.scheduleSessionListRefresh(2000);

      return response;
    },
    [selectedAgent, selectedFiles, selectedKnowledge],
  );

  const handleFileUpload = useCallback(
    async (options: {
      file: File;
      onSuccess: (body: { url?: string; thumbUrl?: string }) => void;
      onError?: (e: Error) => void;
      onProgress?: (e: { percent?: number }) => void;
    }) => {
      const { file, onSuccess, onError, onProgress } = options;
      try {
        // Check multimodal support only for image/video files
        const isImage = file.type.startsWith("image/");
        const isVideo = file.type.startsWith("video/");
        
        if (isImage || isVideo) {
          // Warn when model has no multimodal support for image/video
          if (!multimodalCaps.supportsMultimodal) {
            message.warning(t("chat.attachments.multimodalWarning"));
          } else if (
            isVideo &&
            multimodalCaps.supportsImage &&
            !multimodalCaps.supportsVideo
          ) {
            // Warn when uploading video but model only supports image
            message.warning(t("chat.attachments.imageOnlyWarning"));
          }
        }
        
        const sizeMb = file.size / 1024 / 1024;
        const isWithinLimit = sizeMb < CHAT_ATTACHMENT_MAX_MB;

        if (!isWithinLimit) {
          message.error(
            t("chat.attachments.fileSizeExceeded", {
              limit: CHAT_ATTACHMENT_MAX_MB,
              size: sizeMb.toFixed(2),
            }),
          );
          onError?.(new Error(`File size exceeds ${CHAT_ATTACHMENT_MAX_MB}MB`));
          return;
        }

        const res = await chatApi.uploadFile(file);
        onProgress?.({ percent: 100 });
        // 直接传文件相对路径给 Agent（如 /media/{filename}），
        // 由后端 _resolve_media_url 解析为实际工作区路径。
        // 不再包装为 preview URL，避免 Agent 读错文件。
        onSuccess({ url: res.url });
      } catch (e) {
        // 处理文件已存在的情况（409 Conflict）
        if (e instanceof Error && e.message.includes("409")) {
          message.warning(t("chat.attachments.fileExists", "文件已存在，请重命名后重试"));
          onError?.(new Error("File already exists"));
        } else {
          onError?.(e instanceof Error ? e : new Error(String(e)));
        }
      }
    },
    [multimodalCaps, t],
  );

  const options = useMemo(() => {
    const i18nConfig = getDefaultConfig(t);
    const commandSuggestions: CommandSuggestion[] = [
      {
        command: "/clear",
        value: "clear",
        description: t("chat.commands.clear.description"),
      },
      {
        command: "/compact",
        value: "compact",
        description: t("chat.commands.compact.description"),
      },
      {
        command: "/mission",
        value: "mission",
        description: t("chat.commands.mission.description"),
      },
    ];

    // /skills: all users (read-only listing)
    commandSuggestions.push({
      command: "/skills",
      value: "skills",
      description: t("chat.commands.skills.description"),
    });

    // /model: only advanced+ (switch needs write access)
    const role = user?.role || "user";
    const isAdvanced = ["admin", "superadmin"].includes(role);
    if (isAdvanced) {
      commandSuggestions.push({
        command: "/model",
        value: "model ",
        description: t("chat.commands.model.description", "Switch AI model"),
      });
    }

    if (planEnabled) {
      commandSuggestions.push({
        command: "/plan",
        value: "plan ",
        description: t("chat.commands.plan.description"),
      });
    }

    const handleBeforeSubmit = async () => {
      if (isComposingRef.current) return false;
      // COAPIS FIX: ensure a session exists before the library's handleSubmit
      // runs. For new agents we now create the session up-front in
      // ChatSessionInitializer; this guard is a safety net for very fast submits.
      if (sessionApi.createSessionIfNeeded) {
        await sessionApi.createSessionIfNeeded();
      }
      return true;
    };

    return {
      ...i18nConfig,
      theme: {
        ...defaultConfig.theme,
        darkMode: isDark,
        leftHeader: {
          logo: "",
          title: "",
        },
        rightHeader: (
          <>
            <ChatSessionInitializer skipNextSessionSelectedRef={skipNextSessionSelectedRef} />
            <RuntimeLoadingBridge bridgeRef={runtimeLoadingBridgeRef} />
          </>
        ),
      },
      welcome: {
        ...i18nConfig.welcome,
        nick: sceneName || "CoApis",
        avatar: "/bee_icon.png",
        greeting: sceneWelcomeMessage || i18nConfig.welcome.greeting,
        // Use dynamic recommendations if available, fallback to static prompts
        prompts: dynamicRecommendations.length > 0
          ? dynamicRecommendations.map((rec) => ({
              value: rec.prompt,  // Use the actual prompt text
              label: `${rec.icon} ${rec.title}`,
            }))
          : i18nConfig.welcome.prompts,
      },
      sender: {
        ...(i18nConfig as any)?.sender,
        disclaimer: undefined,  // 禁用默认的 disclaimer，使用 footer 替代
        beforeSubmit: handleBeforeSubmit,
        allowSpeech: true,
        attachments: {
          trigger: function (props: any) {
            const tooltipKey = multimodalCaps.supportsMultimodal
              ? multimodalCaps.supportsImage && !multimodalCaps.supportsVideo
                ? "chat.attachments.tooltipImageOnly"
                : "chat.attachments.tooltip"
              : "chat.attachments.tooltipNoMultimodal";
            return (
              <Tooltip title={t(tooltipKey, { limit: CHAT_ATTACHMENT_MAX_MB })}>
                <IconButton
                  disabled={props?.disabled}
                  icon={<SparkAttachmentLine />}
                  bordered={false}
                />
              </Tooltip>
            );
          },
          customRequest: handleFileUpload,
        },
        placeholder: t("chat.inputPlaceholder"),
        suggestions: commandSuggestions.map((item) => ({
          label: renderSuggestionLabel(item.command, item.description),
          value: item.value,
        })),
        // 输入框下方 - 显示引用条（始终占位）
        afterUI: (
          <ChatInputFooter
            files={selectedFiles}
            knowledge={selectedKnowledge}
            onRemoveFile={(id) => {
              setSelectedFiles(prev => prev.filter(f => f.id !== id));
            }}
            onRemoveKnowledge={(id) => {
              setSelectedKnowledge(prev => prev.filter(k => k.id !== id));
            }}
          />
        ),
        // 右下角操作区 - 显示模型能力
        actionAffix: <ModelCapabilityTag caps={multimodalCaps} />,
      },
      session: {
        multiple: true,
        hideBuiltInSessionList: true,
        api: sessionApi,
      },
      api: {
        ...defaultConfig.api,
        fetch: customFetch,
        responseParser: (chunk: string) => {
          const payload = JSON.parse(chunk) as Record<string, unknown>;
          
          // Filter out SSE events from other chats
          // Backend adds chat_id to metadata for session isolation
          const payloadChatId = (payload.metadata as Record<string, unknown>)?.chat_id as string | undefined;
          const currentChatId = requestSessionIdRef.current;
          
          if (payloadChatId && currentChatId && payloadChatId !== currentChatId) {
            console.log("[SSE] Ignoring payload from other chat:", payloadChatId, "current:", currentChatId);
            // Return a minimal heartbeat event to prevent errors
            return { object: "heartbeat", status: "completed" };
          }
          
          const completed = payloadCompletesResponse(payload);

          // Debug: log key events
          if (payload.object === "message" || payload.object === "response") {
            console.log(`[rp] ${payload.object} type=${(payload as any).type || ""} status=${(payload as any).status || ""} id=${(payload as any).id || (payload as any).msg_id || ""}`);
          }
          if (payload.object === "content") {
            console.log(`[rp] content msg_id=${(payload as any).msg_id} type=${(payload as any).type} delta=${(payload as any).delta} text=${String((payload as any).text || "").substring(0, 60)}`);
          }

          if (payloadRequestsHistoryClear(payload)) {
            pendingClearHistoryRef.current = true;
            if (completed) {
              scheduleHistoryClear();
            }
          }

          // Track plugin_call message types so we can identify their content deltas
          if (payload.object === "message" && payload.type) {
            const msgId = (payload.id || payload.msg_id) as string;
            if (msgId && typeof payload.type === "string") {
              _pluginCallMsgTypes.set(msgId, payload.type);
            }
          }
          // Adapt content delta for plugin_call messages
          if (payload.object === "content" && payload.delta) {
            const msgId = payload.msg_id as string;
            const msgType = msgId ? _pluginCallMsgTypes.get(msgId) : undefined;
            if (msgType === "plugin_call" && payload.type === "text") {
              const pText = String((payload as any).text || "");
              const toolNameMatch = pText.match(
                /^(?:🔧\s*|\\uf013\s*)?(\S+?)\s*[\(（]/
              );
              const toolName = toolNameMatch ? toolNameMatch[1] : "tool";
              const callId = `call_${msgId}_0`;
              (payload as any).data = {
                call_id: callId,
                name: toolName,
                arguments: pText,
              };
            }
          }

          // On completion: inject Builder's accumulated output to prevent
          // handleResponse() from wiping all messages via Object.assign(draft, data).
          if (completed) {
            // Clean up plugin call type tracking
            _pluginCallMsgTypes.clear();
            const builderOutput = (chatRef.current?.messages?.getMessages?.() as any[]) || [];
            console.log(`[rp] ★ COMPLETED(${payload.status}): ${builderOutput.length} msgs, chatRef=${!!chatRef.current}`);
            // Diagnostic: store last completion data on window for debugging
            (window as any).__lastCompletion = {
              status: payload.status,
              builderOutputLen: builderOutput.length,
              chatRefExists: !!chatRef.current,
              messagesMethod: typeof chatRef.current?.messages?.getMessages,
              timestamp: Date.now(),
            };

            // Refresh session list so auto-renamed titles are picked up
            sessionApi.invalidateSessionList();
            setTimeout(() => sessionApi.getSessionList(), 500);

            // Reset loading state on completion
            // Multi-layer fallback: bridge ref → window global → delayed retry
            const resetLoading = () => {
              const bridge = runtimeLoadingBridgeRef.current;
              if (bridge?.setLoading) {
                bridge.setLoading(false);
                console.log("[rp] setLoading(false) via bridge ✓");
                return true;
              }
              // Fallback: RuntimeLoadingBridge exposes setLoading on window
              const fn = (window as any).__chatSetLoading as ((v: boolean) => void) | undefined;
              if (fn) {
                fn(false);
                console.log("[rp] setLoading(false) via window fallback ✓");
                return true;
              }
              return false;
            };
            if (!resetLoading()) {
              console.warn("[rp] setLoading unavailable at completion, scheduling retry");
              setTimeout(() => { resetLoading(); }, 100);
              setTimeout(() => { resetLoading(); }, 500);
            }

            return {
              object: "response",
              status: payload.status || "completed",
              output: builderOutput,
            } as any;
          }

          return payload as any;
        },
        replaceMediaURL: (url: string) => {
          return toDisplayUrl(url);
        },
        cancel(data: { session_id: string }) {
          console.log(
            "[Cancel] Cancel button clicked, session_id:",
            data.session_id,
          );
          const chatId =
            sessionApi.getRealIdForSession(data.session_id) ?? data.session_id;
          console.log("[Cancel] Resolved chat_id:", chatId);
          if (chatId) {
            console.log("[Cancel] Calling stopChat API...");
            chatApi
              .stopChat(chatId)
              .then(() => {
                console.log("[Cancel] stopChat API succeeded");
              })
              .catch((err) => {
                console.error("[Cancel] Failed to stop chat:", err);
              });
          } else {
            console.warn("[Cancel] No chat_id found, cannot stop");
          }
        },
        async reconnect(data: { session_id: string; signal?: AbortSignal }) {
          const headers: Record<string, string> = {
            "Content-Type": "application/json",
            ...buildAuthHeaders(),
          };

          return fetch(getApiUrl("/console/chat"), {
            method: "POST",
            headers,
            body: JSON.stringify({
              reconnect: true,
              session_id: window.currentSessionId || data.session_id,
              user_id: window.currentUserId || DEFAULT_USER_ID,
              channel: window.currentChannel || DEFAULT_CHANNEL,
            }),
            signal: data.signal,
          });
        },
      },
      cards: {
        DeepThinking: CoApisDeepThinking,
      },
      customToolRenderConfig: {
        ..._enhancedToolRenderConfig,
        ...toolRenderConfig,  // plugin overrides take priority
      },
      actions: {
        list: [
          {
            icon: (
              <span title={t("common.copy")}>
                <SparkCopyLine />
              </span>
            ),
            onClick: ({ data }: { data: CopyableResponse }) => {
              void copyResponse(data);
            },
          },
        ],
        replace: true,
      },
    } as unknown as IAgentScopeRuntimeWebUIOptions;
  }, [
    customFetch,
    copyResponse,
    handleFileUpload,
    t,
    isDark,
    multimodalCaps,
    toolRenderConfig,
    scheduleHistoryClear,
    planEnabled,
    displayConfig,
    sessionApi,
    selectedFiles,
    selectedKnowledge,
  ]);

  return (
    <ChatDisplayConfigContext.Provider value={displayConfig}>
      <div
        style={{
          height: "100%",
          width: "100%",
          display: "flex",
          flexDirection: "column",
        }}
      >
        {/* Chat session header: title + actions */}
        <ChatSessionHeader 
          onShowDisplaySettings={() => setShowDisplaySettings(true)}
          onToolbarToggle={toggleToolbar}
        />
        
        {/* 主内容区域：工具栏 + 聊天区 */}
        <div className={styles.chatContentArea}>
          {/* PC端：工具栏在主内容区域内 */}
          {!isMobile && toolbarOpen && (
            <div className={styles.toolbarSidebar}>
              <ChatToolbarSidebar
                selectedFiles={selectedFiles}
                selectedKnowledge={selectedKnowledge}
                onFileSelect={setSelectedFiles}
                onKnowledgeSelect={setSelectedKnowledge}
                onSettingsClick={handleSettingsClick}
              />
            </div>
          )}
          
          {/* 聊天区域 */}
          <div
            className={styles.chatMessagesArea}
            onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); }}
            onDrop={(e) => {
              e.preventDefault();
              e.stopPropagation();
              const files = Array.from(e.dataTransfer.files);
              if (files.length > 0) {
                // Trigger file upload through the @agentscope-ai/chat attachment system
                const input = document.querySelector('input[type="file"]') as HTMLInputElement | null;
                if (input) {
                  const dt = new DataTransfer();
                  files.forEach(f => dt.items.add(f));
                  input.files = dt.files;
                  input.dispatchEvent(new Event('change', { bubbles: true }));
                } else {
                  message.info(t("chat.inputPlaceholder"));
                }
              }
            }}
          >
            <ChatErrorBoundary>
              <AgentScopeRuntimeWebUI
                ref={chatRef}
                key={refreshKey}
                options={options}
              />
            </ChatErrorBoundary>
          </div>
        </div>

        {/* Chat display settings modal */}
        <ChatDisplaySettings
          visible={showDisplaySettings}
          config={displayConfig}
          onConfigChange={setDisplayConfig}
          onClose={() => setShowDisplaySettings(false)}
        />

        {/* Render approval cards as overlays */}
      {Array.from(approvalRequests.values()).map((request) => (
        <div
          key={request.requestId}
          data-approval-id={request.requestId}
          style={{
            position: isEmbeddedMode ? "absolute" : "fixed",
            bottom: 80,
            right: isEmbeddedMode ? 0 : (isMobile ? 8 : 24),
            zIndex: 1000,
            maxWidth: 480,
            width: isMobile ? "calc(100vw - 16px)" : "calc(100vw - 48px)",
          }}
        >
          <ApprovalCard
            requestId={request.requestId}
            toolName={request.toolName}
            severity={request.severity}
            findingsCount={request.findingsCount}
            findingsSummary={request.findingsSummary}
            toolParams={request.toolParams}
            createdAt={request.createdAt}
            timeoutSeconds={request.timeoutSeconds}
            sessionId={request.sessionId}
            rootSessionId={request.rootSessionId}
            onApprove={handleApprove}
            onDeny={handleDeny}
            onTimeout={(requestId) => {
              console.log("[Chat] Approval timed out, removing:", requestId);
              setApprovalRequests((prev) => {
                const next = new Map(prev);
                next.delete(requestId);
                return next;
              });
            }}
            onCancel={() => {
              console.log("[Chat] onCancel called for approval card");
              const sessionId = window.currentSessionId || "";

              // Use the same fallback chain as customFetch:
              // 1. sessionApi.getRealIdForSession (UUID from backend)
              // 2. chatIdRef.current (URL param)
              // 3. sessionId (timestamp fallback)
              const resolvedChatId =
                sessionApi.getRealIdForSession(sessionId) ??
                chatIdRef.current ??
                sessionId;

              console.log(
                "[Chat] Resolved chat_id for stop:",
                resolvedChatId,
                "from session_id:",
                sessionId,
                "chatIdRef:",
                chatIdRef.current,
              );

              if (resolvedChatId) {
                console.log("[Chat] Calling stopChat with:", resolvedChatId);
                chatApi
                  .stopChat(resolvedChatId)
                  .then(() => {
                    console.log("[Chat] stopChat succeeded");
                  })
                  .catch((err) => {
                    console.error("[Chat] stopChat failed:", err);
                  });
              } else {
                console.warn("[Chat] No chat_id resolved, cannot cancel task");
              }
            }}
          />
        </div>
      ))}

      <Modal
        open={showModelPrompt}
        closable={false}
        footer={null}
        width={480}
        styles={{
          content: isDark
            ? { background: "#1f1f1f", boxShadow: "0 8px 32px rgba(0,0,0,0.5)" }
            : undefined,
        }}
      >
        <Result
          icon={<ExclamationCircleOutlined style={{ color: "#faad14" }} />}
          title={
            <span
              style={{ color: isDark ? "rgba(255,255,255,0.88)" : undefined }}
            >
              {t("modelConfig.promptTitle")}
            </span>
          }
          subTitle={
            <span
              style={{ color: isDark ? "rgba(255,255,255,0.55)" : undefined }}
            >
              {t("modelConfig.promptMessage")}
            </span>
          }
          extra={[
            <Button key="skip" onClick={() => setShowModelPrompt(false)}>
              {t("modelConfig.skipButton")}
            </Button>,
            <Button
              key="configure"
              type="primary"
              icon={<SettingOutlined />}
              onClick={() => {
                setShowModelPrompt(false);
                navigate("/models");
              }}
            >
              {t("modelConfig.configureButton")}
            </Button>,
          ]}
        />
      </Modal>

      {/* Onboarding Modal for first-time users */}
      <OnboardingModal
        open={showOnboarding}
        onComplete={(_data) => {
          setShowOnboarding(false);
          // Optionally show a success message
          message.success("设置完成！开始与你的 AI 助手对话吧！");
        }}
        onCancel={() => setShowOnboarding(false)}
      />
    </div>

    {/* 工具栏Drawer */}
    {sceneShowToolbar && (
      <Drawer
        title="工具栏"
        placement={isEmbeddedMode ? "left" : "bottom"}
        width={isEmbeddedMode ? "80%" : undefined}
        height={isMobile && !isEmbeddedMode ? "80%" : undefined}
        open={toolbarOpen}
        onClose={closeToolbar}
        styles={{ body: { padding: 0 } }}
      >
        <ChatToolbarSidebar
          selectedFiles={selectedFiles}
          selectedKnowledge={selectedKnowledge}
          onFileSelect={setSelectedFiles}
          onKnowledgeSelect={setSelectedKnowledge}
          onSettingsClick={handleSettingsClick}
          showPinButton={false}
        />
      </Drawer>
    )}
    </ChatDisplayConfigContext.Provider>
  );
}
