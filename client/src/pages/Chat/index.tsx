import {
  AgentScopeRuntimeWebUI,
  IAgentScopeRuntimeWebUIOptions,
  type IAgentScopeRuntimeWebUIRef,
} from "@agentscope-ai/chat";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button, Modal, Result, Tooltip, notification } from "antd";
import { useAppMessage } from "../../hooks/useAppMessage";
import {
  ExclamationCircleOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import { SparkCopyLine } from "@agentscope-ai/icons";
import { usePlugins } from "../../plugins/PluginContext";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import sessionApi from "./sessionApi";
import defaultConfig, { getDefaultConfig } from "./OptionsPanel/defaultConfig";
import { chatApi } from "../../api/modules/chat";
import api from "@/api";
import { getApiUrl } from "../../api/config";
import { buildAuthHeaders } from "../../api/authHeaders";
import { providerApi } from "../../api/modules/provider";
import type { ProviderInfo, ModelInfo } from "../../api/types";
import { useTheme } from "../../contexts/ThemeContext";
import useIsMobile from "../../hooks/useIsMobile";
import { useUser } from "../../contexts/UserContext";
import { useAgentStore } from "../../stores/agentStore";
import { getChatGlobals } from "../../lib/chatGlobals";
import { useChatAnywhereInput, useChatAnywhereSessionsState } from "@agentscope-ai/chat";
// 深路径导入：SDK 的 index 没导出 messages 上下文（只导出了 input/sessions），
// 而补用户气泡媒体块必须用它。包内无 "exports" 字段，深路径可用（已核实）。
// 权威：node_modules/@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/Context/ChatAnywhereMessagesContext.d.ts
import { useChatAnywhereMessages } from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/Context/ChatAnywhereMessagesContext";
import styles from "./index.module.less";
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
import C2AToolCard, { setUrlNavigate } from "@coapis-c2a/renderer/C2AToolCard";
import { openExternalUrl } from "@/utils/externalNav";
import CoApisDeepThinking from "./components/CoApisDeepThinking";
import CoApisKbCitations from "./components/CoApisKbCitations";
import CoApisChatResources, {
  type LiveResource,
} from "./components/CoApisChatResources";
import CoApisChatResourceBar from "./components/CoApisChatResourceBar";
import CoApisResourceDrawer from "./components/CoApisResourceDrawer";
import {
  useChatResourceLedger,
  ledgerKey,
} from "./components/useChatResourceLedger";
import type { ChatResourceItem } from "../../api/modules/chat";
import ChatSessionSidebar from "./components/ChatSessionSidebar";
import CoApisPreviewDrawer, {
  type PreviewTarget,
} from "./components/CoApisPreviewDrawer";
import {
  isPreviewablePath,
  linkifyMessageOutput,
  toMyfilesParams,
  toWorkspaceRel,
} from "./workspaceLinks";
import OnboardingModal from "../../components/OnboardingModal";
import { useRecommendations } from "../../components/Recommendation";
import {
  useToolbarState,
  ChatInputFooter,
  ModelCapabilityTag,
  ModelChips,
  ResourcePlusMenu,
  CascadePickerModal,
  ScenePickerModal,
  type SessionFile,
} from "../../components/Chat";
import type { CascadeNode } from "../../components/CascadeMenu/CascadeMenu";
import { invalidateCascade } from "../../components/Chat/resource/cascadeAdapters";
import { useChatWindow } from "../../contexts/ChatWindowContext";
import type { SceneConfig } from "../Workbench/types";

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
  /** Server-authoritative countdown; preferred over createdAt math. */
  remainingSeconds?: number;
}

/** A dead approval kept on screen so the user learns why nothing ran. */
interface TerminalApproval {
  requestId: string;
  toolName: string;
  title: string;
  message: string;
}

import {
  toDisplayUrl,
  copyText,
  extractCopyableText,
  buildModelError,
  normalizeContentUrls,
  extractTextFromMessage,
  setTextareaValue,
  loadSceneNames,
  parseSceneId,
  mediaTypeFromFilename,
  type ChatMediaType,
  type CopyableResponse,
  type RuntimeLoadingBridgeApi,
  type ChatMessagesBridgeApi,
  appendMediaToUserBubble,
  mySpaceDisplayUrl,
} from "./utils";

/** 左栏折叠态持久化键（批次 D1：折叠是用户选择，刷新要保住） */
const SIDEBAR_COLLAPSE_KEY = "coapis_chat_sidebar_collapsed";

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
// Helper: format multiline text with <br/> for line breaks
// ---------------------------------------------------------------------------
function formatMultilineText(text: string): React.ReactNode {
  if (!text) return text;
  const lines = text.split('\n');
  return lines.map((line, index) => (
    <React.Fragment key={index}>
      {line}
      {index < lines.length - 1 && <br />}
    </React.Fragment>
  ));
}
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
// C2A 卡片：c2a_render_card 工具返回的 c2a_message 由 @coapis-c2a/renderer 渲染
// 外部 URL 拦截（宿主职责）：行链接/按钮点击外部地址时先换带身份断言的签名 URL 再打开
setUrlNavigate(openExternalUrl);
_enhancedToolRenderConfig["c2a_render_card"] = C2AToolCard;

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

  // 1) 标准 response 完成标志
  if (record.object === "response") {
    const status = record.status as string;
    if (status === "completed" || status === "failed" || status === "canceled") {
      return true;
    }
  }

  // 2) ~~兜底：message completed 也视为流结束~~
  // 注释掉：对齐 QwenPaw 做法，只检查 response 完成
  // 原 CoApis 做法会导致 SDK 内部 loading 状态不同步
  // if (record.object === "message") {
  //   const status = record.status as string;
  //   if (status === "completed" || status === "failed" || status === "canceled") {
  //     return true;
  //   }
  // }

  // 3) 兼容：某些实现用 event: done 或 data: [DONE]
  if (record.object === "event" && (record as any).event === "done") {
    return true;
  }
  if (record.object === "content" && (record as any).text === "[DONE]") {
    return true;
  }

  return false;
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

/**
 * 把 SDK 的 messages 上下文（getMessages/updateMessage）递到页面层。
 *
 * 为什么要走桥：`useChatAnywhereMessages` 是 context selector，必须在
 * ChatAnywhere 的 Provider 树**内部**才拿得到值。页面层的 customFetch 在树外，
 * 直接调会拿到默认空实现。所以照 RuntimeLoadingBridge 的现成套路：在树内
 * （rightHeader）渲染一个返回 null 的组件，把 API 挂到 ref 上给外面用。
 */
function ChatMessagesBridge({
  bridgeRef,
}: {
  bridgeRef: { current: ChatMessagesBridgeApi | null };
}) {
  const { getMessages, updateMessage } = useChatAnywhereMessages();

  useEffect(() => {
    if (!getMessages || !updateMessage) {
      bridgeRef.current = null;
      return;
    }
    bridgeRef.current = { getMessages, updateMessage };
    return () => {
      if (bridgeRef.current?.updateMessage === updateMessage) {
        bridgeRef.current = null;
      }
    };
  }, [getMessages, updateMessage, bridgeRef]);

  return null;
}

export default function ChatPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const { isDark } = useTheme();
  const isMobile = useIsMobile();
  const { user } = useUser();
  
  // 读取场景参数（嵌入式模式通过 lib/chatGlobals 命名空间注入，M3/T3.2）
  const chatMode = useMemo(() => {
    return getChatGlobals().mode || 'full';
  }, []);
  
  const isEmbeddedMode = chatMode === 'embedded';
  
  const sceneSessionId = useMemo(() => {
    return getChatGlobals().sessionId;
  }, []);
  
  const sceneId = useMemo(() => {
    return getChatGlobals().sceneId;
  }, []);
  
  // 场景ID用于后续场景智能体相关逻辑
  useEffect(() => {
    if (sceneId && isEmbeddedMode) {
      console.log('[Chat] Scene mode activated:', sceneId);
    }
  }, [sceneId, isEmbeddedMode]);
  
  // 使用状态管理window参数，确保在参数注入后能正确读取
  const [sceneName, setSceneName] = useState<string>('');
  const [sceneWelcomeMessage, setSceneWelcomeMessage] = useState<string>('');
  // 场景 id→名称映射（/scenes 一次加载并缓存），用于非嵌入模式解析当前会话所属场景
  const [sceneNames, setSceneNames] = useState<Record<string, string>>({});
  // 会话列表变更计数：ChatSessionHeader 在库的 SessionsContext.Provider 之外，
  // 读不到 useChatAnywhereSessionsState()，只能靠 sessionApi（数据源头）驱动重渲染
  const [sessionTick, setSessionTick] = useState(0);
  // sceneShowToolbar 预留给 ChatWrapper 控制，暂未使用
  // const [sceneShowToolbar, setSceneShowToolbar] = useState<boolean>(true);
  
  // 监听window参数变化（ChatWrapper使用useLayoutEffect设置参数）
  useEffect(() => {
    if (isEmbeddedMode) {
      const g = getChatGlobals();
      setSceneName(g.sceneName || '');
      setSceneWelcomeMessage(g.welcomeMessage || '');
    }
  }, [isEmbeddedMode]);

  // 加载场景 id→名称映射（模块级缓存，仅首次请求 /scenes）
  useEffect(() => {
    loadSceneNames().then(setSceneNames);
  }, []);
  
  // 嵌入式模式的回调函数
  const embeddedOnClose = useMemo(() => {
    return getChatGlobals().onClose;
  }, [isEmbeddedMode]);
  
  const chatId = useMemo(() => {
    // 嵌入式模式：使用场景会话ID
    if (isEmbeddedMode && sceneSessionId) {
      return sceneSessionId;
    }
    // 完整模式：从路由获取
    const match = location.pathname.match(/^\/chat\/(.+)$/);
    return match?.[1];
  }, [isEmbeddedMode, sceneSessionId, location.pathname]);
  // 会话资源（B3/B4）：资源条刷新信号（completed 事件后自增）+ 预览抽屉目标。
  // 抽屉是页面级单例，气泡里的产出卡与资源条共用它。
  const [resourceRefresh, setResourceRefresh] = useState(0);
  const [previewTarget, setPreviewTarget] = useState<PreviewTarget | null>(null);
  const [showModelPrompt, setShowModelPrompt] = useState(false);
  const { selectedAgent } = useAgentStore();
  const { toolRenderConfig } = usePlugins();
  const [refreshKey, setRefreshKey] = useState(0);
  const runtimeLoadingBridgeRef = useRef<RuntimeLoadingBridgeApi | null>(null);
  // 「+ 菜单」通道补缩略图用（见 ChatMessagesBridge / appendMediaToUserBubble）
  const chatMessagesBridgeRef = useRef<ChatMessagesBridgeApi | null>(null);
  const { message } = useAppMessage();

  // ─── M4 资源整合：+ 菜单与资源浮层 ─────────────────────────────
  // MCP / 技能入口已按 D6 删除（菜单、弹窗、i18n 键一并移除）。
  // 菜单层用通用 CascadeMenu 直接勾选（D4：点一下即生效，无确认按钮）；
  // 浮层只承担跨目录检索与知识库选择（D3：检索需要搜索框，菜单层做不好）。
  type PickerMode = "files" | "knowledge";
  const [pickerMode, setPickerMode] = useState<PickerMode | null>(null);
  // 浮层展开根（D-8/4d）：null=我的空间根；「本会话目录」入口传后端给的会话目录
  const [pickerRoot, setPickerRoot] = useState<string | null>(null);
  // 本会话文件：按 chat_id 过滤的台账行（D1）。旧数据 chat_id=NULL，
  // 所以「本会话」只覆盖新产生的文件（D2，接受的现状）。
  const [sessionFiles, setSessionFiles] = useState<SessionFile[]>([]);
  const [scenePickerOpen, setScenePickerOpen] = useState(false);
  // 固定左栏（批次 D1）：会话列表常驻聊天区左侧；折叠态持久化，
  // 窄屏/嵌入模式默认折叠（批次 D5），不挤占聊天区。
  const mainAreaRef = useRef<HTMLDivElement>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(() => {
    const saved = localStorage.getItem(SIDEBAR_COLLAPSE_KEY);
    if (saved === "1") return true;
    if (saved === "0") return false;
    return isMobile || isEmbeddedMode;
  });
  const toggleSidebarCollapsed = useCallback((next: boolean) => {
    setSidebarCollapsed(next);
    localStorage.setItem(SIDEBAR_COLLAPSE_KEY, next ? "1" : "0");
  }, []);
  // 本轮实时增量（答案气泡那份）→ 与左栏「会话资源」的台账清单合并

  // ---------------------------------------------------------------------
  // 正文文件链接接管（B4/B5）
  //
  // 回答里的 `<a>` 指向工作区文件时，浏览器自己拼出来的 URL 必挂：相对路径
  // 落到站点根（404），绝对路径落到 `/api/files/preview/<绝对路径>`（B0 闸门
  // 403），而且 `<a>` 带不上 Authorization 头。所以正文里的本地路径链接统一
  // 由这里接管：可预览的进右侧抽屉（带 token 的 myfiles 端点），其余走带
  // token 的下载。http(s)/mailto/锚点不接管，保持浏览器默认行为。
  // ---------------------------------------------------------------------
  useEffect(() => {
    const root = mainAreaRef.current;
    if (!root) return;
    const onClick = (e: MouseEvent) => {
      if (e.defaultPrevented || e.button !== 0) return;
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return; // 显式新标签
      const el = (e.target as HTMLElement | null)?.closest?.("a");
      if (!el) return;
      const raw = el.getAttribute("href");
      if (!raw) return;
      if (/^(https?:|mailto:|tel:|data:|javascript:|#|blob:)/i.test(raw.trim())) return;
      const rel = toWorkspaceRel(raw);
      if (!rel) return;
      e.preventDefault();
      e.stopPropagation();
      const name = rel.split("/").pop() || rel;
      if (isPreviewablePath(rel)) {
        setPreviewTarget({ path: rel, title: name });
      } else {
        const { category, path: myRel } = toMyfilesParams(rel);
        window.open(
          mySpaceDisplayUrl(myRel, category),
          "_blank",
          "noopener,noreferrer",
        );
      }
    };
    root.addEventListener("click", onClick, true);
    return () => root.removeEventListener("click", onClick, true);
  }, []);

  const { openChat } = useChatWindow();

  // 切换场景：浮窗模式下更新全局场景（FloatingChatWindow 自动重新进入）；
  // 全屏聊天页下进入场景会话并跳转到对应 /chat/:id
  const handleScenePick = useCallback(
    async (scene: { id: string; name: string }) => {
      try {
        const res = await api.post<{ chat_id?: string }>(
          `/scenes/${scene.id}/enter`,
        );
        if (isEmbeddedMode) {
          openChat(scene as unknown as SceneConfig);
        } else if (res?.chat_id) {
          navigate(`/chat/${res.chat_id}`);
        }
      } catch (err) {
        console.error("[Scene] 进入场景失败:", err);
        message.error("进入场景失败");
      }
    },
    [isEmbeddedMode, openChat, navigate, message],
  );

  // 顶部「新聊天」按钮：创建空会话（sessionApi 自动注册监听并导航）
  const handleNewChat = useCallback(async () => {
    try {
      await sessionApi.createSession({ name: "" });
    } catch (err) {
      console.error("[Chat] 新建聊天失败:", err);
    }
  }, []);

  const openPicker = useCallback((mode: PickerMode, rootPath?: string) => {
    setPickerRoot(rootPath ?? null);
    setPickerMode(mode);
  }, []);

  // 本会话目录直达（D-8/4d）：目录由系统按会话绑定，没产出过文件就没有目录
  // —— 给提示，而不是跳进一个空目录。
  const openSessionDir = useCallback(async () => {
    if (!chatId) {
      message.info(t("resourcePicker.sessionDirEmpty", "本会话还没有产出目录"));
      return;
    }
    try {
      const resp = (await api.get(
        `/myfiles/session-dir?chat_id=${encodeURIComponent(chatId)}`,
      )) as { path?: string | null; exists?: boolean };
      if (!resp?.exists || !resp.path) {
        message.info(t("resourcePicker.sessionDirEmpty", "本会话还没有产出目录"));
        return;
      }
      setPickerRoot(resp.path);
      setPickerMode("files");
    } catch (err) {
      console.error("[Chat] 会话目录查询失败:", err);
      message.error(t("resourcePicker.sessionDirFailed", "会话目录查询失败"));
    }
  }, [chatId, message, t]);

  // 本会话文件：按 chat_id 拉台账（D1）。菜单打开时刷新，保证新上传/新生成的文件即时出现。
  const refreshSessionFiles = useCallback(async () => {
    if (!chatId) {
      setSessionFiles([]);
      return;
    }
    try {
      const resp = (await api.get(
        `/myfiles/records?limit=100&chat_id=${encodeURIComponent(chatId)}`,
      )) as { items?: Array<Record<string, unknown>> } | Array<Record<string, unknown>>;
      const rows = Array.isArray(resp) ? resp : (resp?.items ?? []);
      setSessionFiles(
        rows.map((r) => {
          const p = String(r.file_path ?? "");
          return {
            path: p,
            name: p.includes("/") ? p.slice(p.lastIndexOf("/") + 1) : p,
            size: Number(r.size_bytes ?? 0),
            source: String(r.source ?? "other"),
            mime_type: r.mime_type ? String(r.mime_type) : undefined,
          };
        }),
      );
    } catch {
      setSessionFiles([]);
    }
  }, [chatId]);

  const { approvals } = useApprovalContext();
  const [approvalRequests, setApprovalRequests] = useState<
    Map<string, ApprovalMessageData>
  >(new Map());
  // Dead approvals (expired / refused by the backend). Kept rendered until
  // the user dismisses them: a card that silently disappears teaches the
  // user nothing about why the tool never ran.
  const [terminalApprovals, setTerminalApprovals] = useState<
    TerminalApproval[]
  >([]);
  // Mirror of approvalRequests for change detection inside the poll effect
  // (reading state in a callback would capture a stale map).
  const approvalRequestsRef = useRef<Map<string, ApprovalMessageData>>(
    new Map(),
  );
  const [planEnabled, setPlanEnabled] = useState(false);

  // Onboarding state
  const [showOnboarding, setShowOnboarding] = useState(false);

  // Chat display configuration — synced with UserContext (backend preferences)
  const {
    displayConfig,
    setDisplayConfig,
  } = useChatDisplayFromUser();
  const [showDisplaySettings, setShowDisplaySettings] = useState(false);

  // 资源选择状态（旧工具栏已按设计 §2.4 移除，入口迁至 + 菜单 / 头像下拉 / 顶栏）
  const {
    selectedFiles,
    selectedKnowledge,
    setSelectedFiles,
    setSelectedKnowledge,
  } = useToolbarState();

  // D4：勾选即生效 —— 点一下加入会话引用，再点一下移出。
  // 勾选集合：文件用后端全路径，知识库用 `kb:<id>`（与 CascadeMenu 的 key 命名一致）
  const checkedKeys = useMemo(
    () =>
      new Set([
        ...selectedFiles.map((f) => f.path),
        ...selectedKnowledge.map((k) => `kb:${k.id}`),
      ]),
    [selectedFiles, selectedKnowledge],
  );

  // D4：勾选即生效 —— 点一下加入会话引用，再点一下移出。
  const toggleCascadeNode = useCallback(
    (node: CascadeNode) => {
      // 导航容器不是可引用对象：知识库/会话文件/我的空间/搜索结果的根节点
      // key 是 "kb"/"session"/"files:/"/"search:x"，既不带 kb: 前缀也不以 / 开头，
      // 落到下面的分支会被当成一个 id="kb" 的「文件」发给后端 —— 用户看到
      // 「已选 1 项 知识库」，实际知识库引用为空，检索退化成全库聚合。
      // 注意顺序：具体知识库节点 kind 也是 group（key = kb:<uuid>），
      // 必须先放行 kb: 前缀，再拦截其余导航容器。
      if (node.key.startsWith("kb:")) {
        const id = node.key.slice(3);
        setSelectedKnowledge((prev) =>
          prev.some((k) => k.id === id)
            ? prev.filter((k) => k.id !== id)
            : [...prev, { id, name: node.name }],
        );
        return;
      }
      // 其余 group 都是导航容器（会话文件/我的空间/搜索结果根节点），
      // 勾选它们没有可引用对象；真正的目录引用 key 一定以 / 开头。
      if (node.kind === "group" && !node.key.startsWith("/")) return;
      const payload = node.payload as
        | { path?: string; size?: number }
        | undefined;
      // 目录行（我的空间里的 group）= 目录引用：只记一条目录，由后端提示词
      // 让智能体自己列目录内容（D2 + 「目录勾选只显示目录引用」）
      const isDir = node.kind === "group" && node.key.startsWith("/");
      const path = payload?.path ?? node.key;
      setSelectedFiles((prev) =>
        prev.some((x) => x.path === path)
          ? prev.filter((x) => x.path !== path)
          : [
              ...prev,
              {
                id: path,
                name: node.name,
                path,
                // 媒体按扩展名给出真实类型：发送时它决定内容块类型，
                // 图片写成 "file" 会让模型只收到一句文本占位符（看不到图）。
                type: isDir ? "folder" : mediaTypeFromFilename(node.name || path),
                size: payload?.size,
              },
            ],
      );
    },
    [setSelectedFiles, setSelectedKnowledge],
  );

  // 切换聊天时预取一次，保证菜单打开即有数据（不必等点击）
  useEffect(() => {
    invalidateCascade();
    refreshSessionFiles();
  }, [refreshSessionFiles]);

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
        remainingSeconds: approval.remaining_seconds,
      });
    }

    // Visible arrival hint: a new approval id in *this* session gets a toast
    // naming the tool. The floating card alone is easy to miss (it renders
    // bottom-right and can be covered), which is how "提示要审批但没有审批
    // 窗口" reads from the user's side.
    const freshIds: string[] = [];
    for (const id of newMap.keys()) {
      if (!approvalRequestsRef.current.has(id)) freshIds.push(id);
    }
    approvalRequestsRef.current = newMap;
    if (freshIds.length > 0) {
      const newest = newMap.get(freshIds[0])!;
      notification.info({
        key: "approval-request",
        message: t(
          "approval.requested",
          `工具 ${newest.toolName} 需要审批（${newMap.size} 条）`,
          { tool: newest.toolName, count: newMap.size },
        ),
        description: t(
          "approval.arrivedHint",
          "请在右下角审批卡中批准或拒绝，超时后审批将失效。",
        ),
        duration: 6,
      });
    }

    setApprovalRequests(newMap);
  }, [approvals, chatId, t]);

  const moveApprovalToTerminal = useCallback(
    (requestId: string, toolName: string, title: string, detail: string) => {
      setApprovalRequests((prev) => {
        if (!prev.has(requestId)) return prev;
        const next = new Map(prev);
        next.delete(requestId);
        return next;
      });
      setTerminalApprovals((prev) => {
        if (prev.some((item) => item.requestId === requestId)) return prev;
        return [...prev, { requestId, toolName, title, message: detail }];
      });
    },
    [],
  );

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
      // ⭐ R1: 审批卡本身已按当前会话过滤，chatId 是权威；再退到该审批自带的
      // rootSessionId（每审批身份）；全局 window 只作最后兜底。
      const rootSessionId =
        chatId || request.rootSessionId || window.currentSessionId || "";
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
        console.error("[Approval] Failed to approve:", error);
        // 410 = the waiting agent already gave up: approving cannot make the
        // tool run. Show a terminal card with the server's reason instead of
        // a generic "批准失败" toast that leaves a live-looking card behind.
        const detail =
          (error as { response?: { data?: { detail?: string } } })?.response
            ?.data?.detail ||
          (error as Error)?.message ||
          "";
        moveApprovalToTerminal(
          requestId,
          request.toolName,
          t("approval.expiredTitle", "Approval expired"),
          detail || t("approval.approveFailed"),
        );
      }
    },
    [approvalRequests, chatId, t, message, moveApprovalToTerminal],
  );

  const handleDeny = useCallback(
    async (requestId: string) => {
      const request = approvalRequests.get(requestId);
      if (!request) return;

      // Use currentSessionId (root session) instead of request.sessionId (sub-agent session)
      // ⭐ R1: 与 approve 分支统一（原先这里是 window 优先、chatId 兜底，两处相反）。
      const rootSessionId =
        chatId || request.rootSessionId || window.currentSessionId || "";

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
        console.error("Failed to deny:", error);
        const detail =
          (error as { response?: { data?: { detail?: string } } })?.response
            ?.data?.detail ||
          (error as Error)?.message ||
          "";
        moveApprovalToTerminal(
          requestId,
          request.toolName,
          t("approval.expiredTitle", "Approval expired"),
          detail || t("approval.denyFailed"),
        );
      }
    },
    [approvalRequests, chatId, t, message, moveApprovalToTerminal],
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
  /** ⚠️ COAPIS FIX (F5): signature of the last session list pushed into React. */
  const lastListSignatureRef = useRef<string>("");
  /** Tracks the stale auto-selected session ID that was skipped on init, so we can suppress its late-arriving onSessionSelected callback. */
  const staleAutoSelectedIdRef = useRef<string | null>(null);
  /** When true, skip the next onSessionSelected callback — set by ChatSessionInitializer to break the URL↔session sync loop. */
  const skipNextSessionSelectedRef = useRef(false);
  const chatIdRef = useRef(chatId);
  const navigateRef = useRef(navigate);
  const chatRef = useRef<IAgentScopeRuntimeWebUIRef>(null);
  // v2.2 修正：历史抽屉锚定聊天主窗口（不再盖满整个浏览器视口）
  const chatWindowRef = useRef<HTMLDivElement>(null);
  const pendingClearHistoryRef = useRef(false);
  const requestSessionIdRef = useRef<string | null>(null);
  // ⭐ 方案2：请求级 ID + 取消上下文，避免旧请求流污染新会话
  const requestIdRef = useRef(0);
  const activeRequestIdRef = useRef<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

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

  /**
   * 当前会话（标题与场景标识的数据源）。
   * 必须取自 sessionApi：ChatSessionHeader 位于库的 SessionsContext.Provider
   * 之外，useChatAnywhereSessionsState() 在这里只能拿到默认空值。
   * sessionTick 在会话列表/会话名更新时自增，触发重新取值。
   */
  const currentSessionData = useMemo(
    () => sessionApi.currentSession,
    [sessionTick, chatId],
  );
  const chatName = currentSessionData?.name?.trim() ?? "";

  /**
   * 当前会话所属场景名：
   * - 嵌入模式：沿用 chatGlobals 注入的场景名
   * - 非嵌入模式：从会话 sessionId（`scene:<scene_id>:<agent>`）解析，
   *   这样「切换场景」进入的会话也能显示场景标识
   */
  const activeSceneName = useMemo(() => {
    if (isEmbeddedMode) return sceneName;
    const sid = parseSceneId(currentSessionData?.sessionId);
    return sid ? (sceneNames[sid] ?? "") : "";
  }, [isEmbeddedMode, sceneName, currentSessionData, sceneNames]);

  // Tell sessionApi which session to put first in getSessionList, so the library's
  // useMount auto-selects the correct session without an extra getSession round-trip.
  // CRITICAL: This must be set BEFORE AgentScopeRuntimeWebUI renders
  // In embedded mode, chatId is already set from window.__CHAT_SESSION_ID__
  // ⚠️ COAPIS FIX (F1): keep ONLY the idempotent marker assignment in this
  // render-phase block. The invalidateSessionList()+getSessionList() pair that used
  // to sit here was the entry point of an infinite render→fetch→setState→render
  // loop: every list refresh cleared preferredChatId (in sessionApi), which
  // re-opened the `!== chatId` guard above, so each Chat re-render issued a new
  // GET /api/chats, whose completion notified React (onSessionListUpdated) and
  // re-rendered Chat again — measured at ~30 requests/second while the user is
  // simply sitting on the chat page. List refreshes are now driven by *events*
  // only (SSE completion, dropdown open, agent switch, new chat).
  if (chatId && sessionApi.preferredChatId !== chatId) {
    sessionApi.preferredChatId = chatId;
  }

  // Register session API event callbacks for URL synchronization

  useEffect(() => {
    sessionApi.onSessionIdResolved = (realId) => {
      if (!isChatActiveRef.current) return;
      // ⭐ 嵌入式模式：不跳转URL
      if (isEmbeddedMode) return;
      // Update URL when realId is resolved, regardless of current chatId
      // (chatId may be undefined if URL was cleared in onSessionCreated)
      lastSessionIdRef.current = realId;
      navigateRef.current(`/chat/${realId}`, { replace: true });
    };

    sessionApi.onSessionRemoved = (removedId) => {
      if (!isChatActiveRef.current) return;
      // ⭐ 嵌入式模式：不跳转URL
      if (isEmbeddedMode) return;
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
      // ⭐ 嵌入式模式：不跳转URL
      if (isEmbeddedMode) return;
      
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
      // ⭐ 嵌入式模式：不跳转URL
      if (isEmbeddedMode) return;
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
      // ⚠️ COAPIS FIX (F5): notify React only when the list content actually
      // changed (ids / names / generating flags). Previously every list refresh
      // bumped sessionTick, forcing a full Chat re-render — the amplifier that
      // turned the render-phase fetch into a self-sustaining loop.
      const signature = sessions
        .map(
          (s) =>
            `${(s as any).realId || s.id}|${s.name}|${(s as any).generating ? 1 : 0}`,
        )
        .join(",");
      if (signature === lastListSignatureRef.current) return;
      lastListSignatureRef.current = signature;
      setSessions(sessions);
      // 驱动 ChatSessionHeader 重渲染（标题/场景标识取自 sessionApi）
      setSessionTick((t) => t + 1);
    };

    // When a new session's realId (backend UUID) is resolved during createSession,
    // update chatIdRef so the first message is sent with the correct chat_id.
    // Without this, the first message would have chat_id=undefined and the
    // backend might not associate it with the correct chat.
    sessionApi.onSessionRealIdResolved = (_localId: string, realId: string) => {
      chatIdRef.current = realId;
      // 新会话建号前上传的文件 chat_id 为空，此刻补写，让「本会话文件」能看到
      if (_localId && realId) {
        chatApi
          .attachChatFiles(_localId, realId)
          .then((r) => {
            if (r.updated > 0) refreshSessionFiles();
          })
          .catch((e) => console.warn("[ledger] attach-chat failed:", e));
      }
    };

    return () => {
      // ⭐ 方案2：组件卸载时取消进行中的请求
      if (abortControllerRef.current) {
        console.log("[Request] Aborting request on unmount:", activeRequestIdRef.current);
        abortControllerRef.current.abort();
        abortControllerRef.current = null;
        activeRequestIdRef.current = null;
      }
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
      // ⭐ 方案2：切换 agent 时取消进行中的旧请求，防止旧 SSE 流污染新会话
      if (abortControllerRef.current) {
        console.log("[Request] Aborting previous request on agent switch:", activeRequestIdRef.current);
        abortControllerRef.current.abort();
        abortControllerRef.current = null;
        activeRequestIdRef.current = null;
      }
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
      // ⭐ 场景聊天的chat_id以"scene-"开头，不应该从localStorage恢复
      // 场景聊天的chat_id是固定的：scene-{scene_id}-{user_id}，由enter_scene API管理
      if (restored && !restored.startsWith("scene-")) {
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
              // ⭐ 嵌入式模式：不跳转URL
              if (!isEmbeddedMode) {
                navigateRef.current("/chat", { replace: true });
              }
            } else {
              // Valid chat, proceed with restore
              console.log(`[Agent Switch] Restored chat ${restored} successfully`);
              // ⭐ 嵌入式模式：不跳转URL
              if (!isEmbeddedMode) {
                navigateRef.current(`/chat/${restored}`, { replace: true });
              }
              sessionApi.preferredChatId = restored;
            }
          } catch (error) {
            // Chat not found or access denied, clear stale data
            console.warn(`Failed to verify chat ${restored}, clearing:`, error);
            setLastChatId(selectedAgent, "");
            // ⭐ 嵌入式模式：不跳转URL
            if (!isEmbeddedMode) {
              navigateRef.current("/chat", { replace: true });
            }
          }
        })();
      } else {
        console.log(`[Agent Switch] No saved chat for agent ${selectedAgent}, starting fresh`);
        // ⭐ 嵌入式模式：不跳转URL
        if (!isEmbeddedMode) {
          navigateRef.current("/chat", { replace: true });
        }
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
      // 气泡展示用的媒体块（预览 URL 形态）—— 见 appendMediaToUserBubble
      const bubbleMediaBlocks: any[] = [];
      if (selectedFiles.length > 0) {
        // 添加文件/媒体引用供后端处理。
        //
        // ⭐ 关键：块类型必须与原生上传通道（@agentscope-ai/chat Request/
        // Builder.js）同构。后端只对 image/video/audio 块送真正的媒体数据；
        // type:"file" 会被 formatter 压成一句
        // "File 'x.png' is available at: /path" 纯文本 —— 模型收不到像素，
        // 只能自己去调 view_image，于是出现「提示说 Image loaded 但看不到图」。
        // 前端气泡同理：Images 卡片只认 type:"image" + image_url，写成
        // file 就只剩一个文件名 chip，没有缩略图。
        //
        // URL 形态：先发浏览器可取的预览 URL（缩略图/下载链接直接用它），
        // 再经 normalizeContentUrls 折回后端认的 "/media/x" 形态。顺序不能反，
        // 卡片渲染读的就是发出去的这份 content。
        selectedFiles.forEach(file => {
          // 目录引用只走 biz_params.file_refs（后端注入目录提示词），
          // 不能当成 file:// 附件传给模型——目录不是文件
          if (file.type === "folder") return;
          // 移除开头的 /，直接传递相对路径
          const filePath = file.path.startsWith('/') 
            ? file.path.slice(1) 
            : file.path;
          const previewUrl = chatApi.filePreviewUrl(`/${filePath}`);
          // 发给后端的块用 previewUrl 形态：经 normalizeContentUrls 折回
          // "/x.png"，后端 _resolve_media_url 按工作区解析（链路已验证）。
          // 气泡用的展示形态不在这里定，统一在循环后从 rewrittenContent
          // 派生（见下面的 ⭐ 段）—— 两条通道走同一个换算口径。
          const kind: ChatMediaType =
            file.type === "image" ||
            file.type === "video" ||
            file.type === "audio"
              ? file.type
              : mediaTypeFromFilename(file.name || filePath);

          // 同一份块，两种 URL：urlFor 决定塞哪个
          const buildBlock = (url: string): any => {
            if (kind === "image") {
              return { type: "image", image_url: url };
            }
            if (kind === "video") {
              return { type: "video", video_url: url };
            }
            if (kind === "audio") {
              // 后端 _extract_source_and_filename 里 audio 的 `data` 字段是
              // **base64**（钉钉语音通道），塞 URL 会被当 base64 解码成乱码。
              // 所以这里给 source.url（走 _resolve_media_url），audio_url
              // 只供前端播放器读（Audios 卡片取 audio_url || data）。
              return {
                type: "audio",
                audio_url: url,
                source: { type: "url", url: `/${filePath}` },
              };
            }
            return {
              type: "file",
              // 与上传附件同构：后端 _resolve_media_url 认 "/media/x" 与 "/x"
              // 两种形态并解析成磁盘绝对路径。旧写法 `file://{name}` 把文件名
              // 放在 netloc 位，url2pathname 解析为空，整条文件链路直接崩成
              // "[Error: Unknown file source type or empty data]"。
              file_url: url,
              file_name: file.name,
              file_size: file.size,
            };
          };

          const block = buildBlock(previewUrl);
          rewrittenContent.push(normalizeContentUrls(block));
        });
      }

      // ⭐ 气泡缩略图统一在这里派生（两条通道一起覆盖）：
      //  - 「+ 资源菜单」通道：selectedFiles → 上面的 block
      //  - 原生上传通道：SDK 用 fileList 自己建的块（已在 rewrittenContent 里，
      //    image_url 是后端 /api/myfiles/upload 返回的 `/x.png`）
      // 两条通道的 image_url 都是**后端路径形态**，浏览器直接取必 404，
      // 所以统一过 toDisplayUrl 换成可直读形态再进气泡。
      bubbleMediaBlocks.push(
        ...rewrittenContent
          .filter(
            (b: any) =>
              b && (b.type === "image" || b.type === "video" || b.type === "audio"),
          )
          .map((b: any) => {
            const key =
              b.type === "image"
                ? "image_url"
                : b.type === "video"
                ? "video_url"
                : "audio_url";
            const display = toDisplayUrl(b[key] || b.source?.url);
            return { ...b, [key]: display };
          }),
      );
      
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

      // ⭐ 构建消息对象：只保留必要字段，避免传递只读属性（如 cards）
      // AgentScope 运行时会尝试修改消息对象的 cards 属性
      // 如果传递了包含 cards 的冻结对象，会报 TypeError
      const rewrittenInput = lastMsg
        ? [
            {
              role: lastMsg.role,
              type: lastMsg.type,
              content: rewrittenContent,
              // ⭐ session 也可能是 frozen 对象，创建新对象避免引用
              ...(lastMsg.session ? { session: { ...lastMsg.session } } : {}),
            },
          ]
        : lastInput;

      const requestBody = {
        input: rewrittenInput,
        // ⭐ R1: 优先级反转。`session` 来自运行时传入的本条消息所属会话
        // （input[last].session），是**每会话**身份；window.currentSessionId 是**全局单值**，
        // 多会话并发时它指向最后打开的那个会话，旧写法优先取它 → 消息发进别人的会话。
        session_id:
          session?.session_id ||
          chatIdRef.current ||
          window.currentSessionId ||
          "",
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
          // ⭐ 嵌入式模式：场景ID传递到 biz_params 中（后端从 biz_params.scene_id 读取）
          ...(isEmbeddedMode && sceneId && { scene_id: sceneId }),
        },
        // Pass chat_id (UUID) so backend can persist messages to the correct chat
        // instead of matching by session_id (which is shared across all console chats).
        chat_id: chatIdRef.current || undefined,
      };

      // 🔍 调试：打印场景代入信息
      if (isEmbeddedMode && sceneId) {
        console.log('[Chat] Scene mode - sceneId:', sceneId, 'isEmbeddedMode:', isEmbeddedMode);
        console.log('[Chat] Request biz_params:', requestBody.biz_params);
      }

      // Record current session_id for SSE filtering
      const currentSessionId = requestBody.session_id || requestBody.chat_id || null;
      requestSessionIdRef.current = currentSessionId;

      // ⭐ 方案2：创建新的 AbortController + 请求级 ID，用于取消旧请求和过滤 SSE 事件
      const controller = new AbortController();
      abortControllerRef.current = controller;
      const requestId = `req_${++requestIdRef.current}_${Date.now()}`;
      activeRequestIdRef.current = requestId;
      console.log("[Request] Starting:", requestId, "session:", currentSessionId);

      // ⭐ 补缩略图：SDK 的用户气泡只读 {query, fileList}（Request/Builder.js），
      // 「+ 菜单」选的文件走的是组件 state，从不进 fileList → 气泡只有文件名
      // chip，没有图。此刻 SDK 已 flushSync 建好这条用户消息
      // （useChatController: createRequestMessage → sleep(100) → request），
      // 把同样的媒体块补进气泡卡片读的 data.input[0].content 就有图。
      // 只影响本地气泡显示，不动 requestBody，发给后端的东西一字未改。
      if (bubbleMediaBlocks.length > 0) {
        appendMediaToUserBubble(chatMessagesBridgeRef.current, bubbleMediaBlocks);
      }

      const response = await fetch(getApiUrl("/console/chat"), {
        method: "POST",
        headers,
        body: JSON.stringify(requestBody),
        // 优先使用新 controller 的 signal，退回到外部传入的 signal
        signal: controller.signal,
      });

      // Schedule a delayed session list refresh after the SSE stream completes.
      // The backend auto-renames chats from the first user message in the
      // finally block (after the stream ends), so we need to refresh the
      // session list to pick up the new name.
      sessionApi.scheduleSessionListRefresh(2000);

      // ⭐ 清理：如果这不是当前活跃请求，说明已被取消/覆盖
      if (activeRequestIdRef.current !== requestId) {
        console.log("[Request] Discarding stale response:", requestId);
        return buildModelError();
      }

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

        // ⭐ R1: 只有「新会话尚未建号」时才需要带本地会话 id 供台账事后补写，
        // 此时 window.currentSessionId 正是本会话的本地 id（createEmptySession 刚写入）。
        // 已有 chatId 时不再传全局值——多会话并发下它指向最后打开的那个会话，
        // 会把文件挂到别的会话台账上。
        const localSessionId = chatId ? undefined : window.currentSessionId;
        const res = await chatApi.uploadFile(file, chatId, localSessionId);
        onProgress?.({ percent: 100 });
        // 直接传文件相对路径给 Agent（如 /media/{filename}），
        // 由后端 _resolve_media_url 解析为实际工作区路径。
        // 不再包装为 preview URL，避免 Agent 读错文件。
        onSuccess({ url: res.url });
        // 上传已带 chat_id，刷新台账让「本会话文件」立刻能看到它
        refreshSessionFiles();
        // 目录/台账缓存随之失效，菜单下次打开读到新文件
        invalidateCascade();
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
    [multimodalCaps, t, chatId, refreshSessionFiles],
  );

  // ── 稳定的「+ 资源菜单」trigger 身份 ────────────────────────────────
  // Sender 的 attachments.trigger 由 React.createElement(trigger, {disabled}) 渲染。
  // 若每次渲染都新建这个函数，React 会把它当成「新的组件类型」，把整棵子树
  // （含 Popover）卸载重挂载 —— 现象就是「勾选一个文件后 + 菜单自动关闭」。
  // 用 ref 桥接最新 props：函数身份恒定，子树只做普通 re-render，菜单保持打开。
  const resourceTriggerRender = useRef<(p: any) => React.ReactElement>(
    () => <React.Fragment />,
  );
  resourceTriggerRender.current = (props: any) => {
    const tooltipKey = multimodalCaps.supportsMultimodal
      ? multimodalCaps.supportsImage && !multimodalCaps.supportsVideo
        ? "chat.attachments.tooltipImageOnly"
        : "chat.attachments.tooltip"
      : "chat.attachments.tooltipNoMultimodal";
    return (
      <Tooltip title={t(tooltipKey, { limit: CHAT_ATTACHMENT_MAX_MB })}>
        <ResourcePlusMenu
          disabled={!!props?.disabled}
          onUploadClick={() => {
            // 故意不 stopPropagation：让点击冒泡到外层 antd Upload，
            // 打开原生文件选择（保留 Sender 原生上传流程）
          }}
          onOpenModal={openPicker}
          onOpenSessionDir={openSessionDir}
          checked={checkedKeys}
          onToggle={toggleCascadeNode}
          chatId={chatId}
          sessionCount={sessionFiles.length}
        />
      </Tooltip>
    );
  };
  const resourceTrigger = useMemo(
    () => (props: any) => resourceTriggerRender.current(props),
    [],
  );

  // ---- 会话资源：台账单一数据源 + L3 抽屉（方案 §12.4）----
  // 必须留在组件顶层：ledger / roundItems 是 hook。此前它们被插进 options 的
  // 对象字面量内部（response: { const ledger = ... }），既不是合法语法，也让
  // hook 落进了 useMemo 回调——deps 未变时 React 会跳过回调，两次渲染的 hook
  // 数量不一致，直接触发 "Rendered fewer hooks than expected"。
  const ledger = useChatResourceLedger(chatId, resourceRefresh);
  const [resourcesOpen, setResourcesOpen] = useState(false);
  const ledgerMetaOf = ledger.metaOf;

  /** 本轮资源（消息 metadata）+ 台账 meta（大小/时间/版本/状态）合并 */
  /**
   * L2「定位到消息」：滚到产出这条资源的那一轮并闪一下（方案 §3.2 产出动作）。
   *
   * 聊天区由 @agentscope-ai/chat 渲染，它不给消息挂 DOM 锚点，所以锚点自己打：
   * 资源条根节点带 data-coapis-resource-msg，往上找库的
   * `*-bubble-content-wrapper-card` 就是那一轮的卡片。
   */
  const handleLocateResource = useCallback((messageId: string) => {
    if (!messageId) return;
    const anchor = document.querySelector(
      `[data-coapis-resource-msg=${JSON.stringify(messageId)}]`,
    ) as HTMLElement | null;
    const card =
      (anchor?.closest('[class*="bubble-content-wrapper-card"]') as HTMLElement | null) ??
      anchor;
    if (!card) return;
    card.scrollIntoView({ behavior: "smooth", block: "center" });
    card.classList.add("coapis-locate-flash");
    window.setTimeout(() => card.classList.remove("coapis-locate-flash"), 1600);
  }, []);

  const roundItems = useCallback(
    (raw?: LiveResource[], messageId?: string): ChatResourceItem[] => {
      if (!raw?.length) return [];
      const out: ChatResourceItem[] = [];
      const seen = new Set<string>();
      for (const r of raw) {
        // 两套字段词汇都要吃：实时 completed 事件用 {url|source, type, name}，
        // 台账/持久化用 {path, kind, title}。只认前者会让回放通道的资源整块丢掉。
        const path = String(r.path || r.url || r.source || "");
        if (!path) continue;
        const key = ledgerKey(path);
        if (seen.has(key)) continue;
        seen.add(key);
        const meta = ledgerMetaOf(path);
        out.push({
          kind: ((r.kind === "url" ? "web" : r.kind) || r.type || "file") as ChatResourceItem["kind"],
          path,
          title: r.title || r.name || path.split("/").pop() || path,
          messageId,
          role: meta?.role || "producer",
          ref_count: meta?.ref_count,
          status: meta?.status,
          updated_at: meta?.updated_at,
          last_seen_at: meta?.last_seen_at,
          size: meta?.size,
          exists: meta?.exists,
          version: meta?.version,
          deleted: meta?.deleted,
        });
      }
      return out;
    },
    [ledgerMetaOf],
  );

  /** 响应气泡末尾插槽（方案 §3.2 L2 / §12.3）：产出卡 + 本轮资源条 */
  const chatAppendSlots = useMemo(
    () => [
      {
        id: "kb-citations",
        order: 10,
        render: ({ data }: { data: any }) => (
          <CoApisKbCitations
            data={{
              citations:
                data?.citations ?? data?.metadata?.metadata?.kb_citations,
            }}
          />
        ),
      },
      {
        // 本轮产出卡 + 引用资源。双数据源（方案 §12.3）：
        // 实时 = completed 事件顶层 resources；刷新回放 = assistant 消息
        // metadata.metadata.resources（后端 _persist_chat_messages 写入）。
        // 此前只读实时通道 → 刷新后产出卡整块消失。
        id: "chat-resources",
        order: 11,
        render: ({ data }: { data: any }) => (
          <CoApisChatResources
            resources={
              data?.resources ?? data?.metadata?.metadata?.resources
            }
            onPreview={(target) =>
              setPreviewTarget({ path: target.path, title: target.name })
            }
            metaOf={ledgerMetaOf}
            onShowAll={() => setResourcesOpen(true)}
          />
        ),
      },
      {
        // 本轮资源条（方案 §3.2 L2）：答案气泡末尾，引用/产出分组，
        // 每组 8 行 +「展开其余 N 项」，尾部「查看全部」开 L3 抽屉。
        id: "coapis-chat-resource-bar",
        order: 14,
        render: ({ data }: { data: any }) => (
          <CoApisChatResourceBar
            items={roundItems(
              data?.resources ?? data?.metadata?.metadata?.resources,
              data?.id,
            )}
            onPreview={(target) => setPreviewTarget(target)}
            onShowAll={() => setResourcesOpen(true)}
            onLocate={handleLocateResource}
          />
        ),
      },
    ],
    [roundItems, ledgerMetaOf, handleLocateResource],
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

    // 审批类快捷指令此前只注册在后端，前端下拉里一条都没有，用户只能手输 ——
    // 这正是「/approve 在输入下拉选项中没有」的成因。仅在存在待审批时出现，
    // 避免菜单噪音；/approve 带尾空格，方便直接续写编号前缀。
    if (approvalRequests.size > 0) {
      commandSuggestions.push(
        {
          command: "/approve",
          value: "approve ",
          description: t(
            "chat.commands.approve.description",
            "批准待审批的工具（可加编号前缀精确指定）",
          ),
        },
        {
          command: "/deny",
          value: "deny",
          description: t(
            "chat.commands.deny.description",
            "拒绝当前待审批的工具",
          ),
        },
      );
    }

    commandSuggestions.push({
      command: "/stop",
      value: "stop",
      description: t(
        "chat.commands.stop.description",
        "终止当前正在执行的任务",
      ),
    });

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
            <ChatMessagesBridge bridgeRef={chatMessagesBridgeRef} />
          </>
        ),
      },
      welcome: {
        ...i18nConfig.welcome,
        nick: sceneName || "CoApis",
        avatar: "/bee_icon.png",
        greeting: formatMultilineText(sceneWelcomeMessage) || i18nConfig.welcome.greeting,
        // 嵌入式模式（场景代入）：不显示推荐prompts，只显示场景欢迎消息
        prompts: isEmbeddedMode ? [] : (dynamicRecommendations.length > 0
          ? dynamicRecommendations.map((rec) => ({
              value: rec.prompt,  // Use the actual prompt text
              label: `${rec.icon} ${rec.title}`,
            }))
          : i18nConfig.welcome.prompts),
      },
      sender: {
        ...(i18nConfig as any)?.sender,
        disclaimer: undefined,  // 禁用默认的 disclaimer，使用 footer 替代
        beforeSubmit: handleBeforeSubmit,
        allowSpeech: true,
        attachments: {
          // 身份稳定的 trigger（见上方 resourceTrigger）—— 勾选文件后菜单不会被关闭
          trigger: resourceTrigger,
          customRequest: handleFileUpload,
        },
        placeholder: t("chat.inputPlaceholder"),
        suggestions: commandSuggestions.map((item) => ({
          label: renderSuggestionLabel(item.command, item.description),
          value: item.value,
        })),
        // L2 本轮资源条**不在输入框上方**：方案 §3.2 规定它挂在答案气泡
        // 末尾（chat-resources 槽位 order 14），见下方 response.append。
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
            onClearAll={() => {
              setSelectedFiles([]);
              setSelectedKnowledge([]);
            }}
          />
        ),
        // 右下角操作区：模型芯片（LLM/嵌入/重排）+ 模型能力标签
        // 模型芯片：放在语音按钮左侧（prefix 插槽里语音按钮先渲染，用 order:-1 排到它前面）
        prefix: (
          <div
            style={{ display: "inline-flex", alignItems: "center", order: -1 }}
            data-testid="model-chip-affix"
          >
            <ModelChips />
          </div>
        ),
        // 右下角操作区：模型能力标签
        actionAffix: (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              width: "100%",
            }}
          >
            <div
              style={{
                flex: 1,
                display: "flex",
                justifyContent: "flex-end",
              }}
            >
              <ModelCapabilityTag caps={multimodalCaps} />
            </div>
          </div>
        ),
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
          // ⭐ 使用 chatIdRef.current（URL 中的后端 chat UUID），而非 requestSessionIdRef.current（SDK 内部 session ID）
          // 修复：response 事件被错误过滤导致按钮卡在 loading 状态
          const currentChatId = chatIdRef.current;
          
          if (payloadChatId && currentChatId && payloadChatId !== currentChatId) {
            console.log("[SSE] Ignoring payload from other chat:", payloadChatId, "current:", currentChatId);
            // Return a minimal heartbeat event to prevent errors
            // Note: must use object: "message" with type: "heartbeat" for SDK to recognize it
            return { object: "message", type: "heartbeat", status: "completed" };
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

            // ~~Reset loading state on completion~~
            // 注释掉：对齐 QwenPaw 做法，不再手动调 setLoading
            // SDK 内部会根据 response completed 自动更新 loading 状态
            // const resetLoading = () => { ... };
            // if (!resetLoading()) { ... }

            // ⭐ 深拷贝 output，解除 React state 的冻结
            // AgentScope 库会尝试修改消息对象的 cards 属性
            // 但 React state 中的对象是 frozen 的，直接修改会报 TypeError
            // 解决方案：使用 JSON 序列化/反序列化创建全新的对象
            const thawedOutput = JSON.parse(JSON.stringify(builderOutput));

            // ⭐ 知识库引用：后端 enrich_chat_context 把 citations 挂到 completed
            // 响应事件。SDK 的响应气泡只按消息 type 渲染，不读消息级 cards，
            // 所以引用必须挂在响应对象顶层，由 response.append 插槽消费。
            const _kbCites = (payload as any).citations;
            const _turnRes = (payload as any).resources;
            // ⭐ 会话资源（B1/B2）：本轮读到的网页 / 写到工作区的文件，同样
            // 挂顶层，由 response.append 的 CoApisChatResources 消费。
            if (Array.isArray(_turnRes) && _turnRes.length > 0) {
              // 台账是权威底账：本轮结束后刷一次会话资源条，让清单与
              // 气泡里的增量对齐（fire-and-forget，失败不影响消息）。
              setResourceRefresh((n) => n + 1);
            }

            return {
              object: "response",
              status: payload.status || "completed",
              // 正文兜底（B5）：把裸的工作区路径收成 markdown 链接，交给下面的
              // 点击拦截器接管。模型不照提示词写时，用户照样能点到文件。
              output: linkifyMessageOutput(thawedOutput),
              ...(Array.isArray(_kbCites) && _kbCites.length > 0
                ? { citations: _kbCites }
                : {}),
              ...(Array.isArray(_turnRes) && _turnRes.length > 0
                ? { resources: _turnRes }
                : {}),
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
          // ⭐ 方案2：reconnect 也创建新的 AbortController，与 customFetch 保持一致
          const controller = new AbortController();
          abortControllerRef.current = controller;
          const requestId = `req_reconnect_${++requestIdRef.current}_${Date.now()}`;
          activeRequestIdRef.current = requestId;
          console.log("[Request] Reconnect:", requestId, "session:", data.session_id);

          const headers: Record<string, string> = {
            "Content-Type": "application/json",
            ...buildAuthHeaders(),
          };

          const response = await fetch(getApiUrl("/console/chat"), {
            method: "POST",
            headers,
            body: JSON.stringify({
              reconnect: true,
              // ⭐ R1: 后端把运行队列键在 chat.id 上（console.py: tracker.attach(chat.id)），
              // 且 chat_id 优先于 session_id 定位会话（console.py:397/442）。旧写法只发
              // session_id 且优先取全局 window 变量——切去新会话再回来时，全局变量已指向
              // 新会话，后端按 session_id 匹配到别的 chat，attach 不到原来那次运行，
              // 现象就是「回到原会话发现已经中断」。chat_id 才是权威身份。
              chat_id: chatIdRef.current || undefined,
              session_id: data.session_id || window.currentSessionId || "",
              user_id: window.currentUserId || DEFAULT_USER_ID,
              channel: window.currentChannel || DEFAULT_CHANNEL,
            }),
            signal: controller.signal,
          });

          // 清理：如果这不是当前活跃请求，说明已被取消/覆盖
          if (activeRequestIdRef.current !== requestId) {
            console.log("[Request] Discarding stale reconnect:", requestId);
            return buildModelError();
          }

          return response;
        },
      },
      response: {
        append: chatAppendSlots,
      },
      cards: {
        DeepThinking: CoApisDeepThinking,
        KbCitations: CoApisKbCitations,
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
    chatAppendSlots,
  ]);

  return (
    <ChatDisplayConfigContext.Provider value={displayConfig}>
      <div
        ref={chatWindowRef}
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
          isEmbeddedMode={isEmbeddedMode}
          onClose={embeddedOnClose}
          sceneName={activeSceneName}
          chatName={chatName}
          onHistoryClick={() => toggleSidebarCollapsed(!sidebarCollapsed)}
          historyActive={!sidebarCollapsed}
          onNewChat={handleNewChat}
          onSwitchScene={() => setScenePickerOpen(true)}
          isPinned={isEmbeddedMode ? getChatGlobals().isPinned : undefined}
          onTogglePin={isEmbeddedMode ? getChatGlobals().onTogglePin : undefined}
        />
        
        {/* 主内容行：固定左栏（会话列表 + 当前会话资源）+ 聊天区，同级并列。
            左栏是常驻列，不再用绝对定位浮层盖在对话上（批次 D1/D3）。 */}
        <div style={{ flex: 1, minHeight: 0, display: "flex" }}>
          <ChatSessionSidebar
            collapsed={sidebarCollapsed}
            onToggleCollapsed={toggleSidebarCollapsed}
            currentBackendId={chatId}
            onPreview={(path, title) => setPreviewTarget({ path, title })}
            onShowAll={() => setResourcesOpen(true)}
            resourceRefresh={resourceRefresh}
          />
          <div ref={mainAreaRef} style={{ flex: 1, minWidth: 0, minHeight: 0, display: "flex", flexDirection: "column", position: "relative" }}>
        <div className={styles.chatContentArea}>
          
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
        </div>
        </div>

        {/* 文件预览抽屉（B4）：产出卡/资源条点「预览」统一进这里 */}
        <CoApisResourceDrawer
          open={resourcesOpen}
          chatId={chatId}
          refreshSignal={resourceRefresh}
          onClose={() => setResourcesOpen(false)}
          onPreview={(target) => {
            setResourcesOpen(false);
            setPreviewTarget({ path: target.path, title: target.name });
          }}
        />
        <CoApisPreviewDrawer
          target={previewTarget}
          onClose={() => setPreviewTarget(null)}
        />

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
            remainingSeconds={request.remainingSeconds}
            sessionId={request.sessionId}
            rootSessionId={request.rootSessionId}
            onApprove={handleApprove}
            onDeny={handleDeny}
            onTimeout={(requestId) => {
              // Do NOT silently drop the card: move it to the terminal list
              // so the user sees that the approval died and what to do next.
              const dead = approvalRequests.get(requestId);
              setApprovalRequests((prev) => {
                if (!prev.has(requestId)) return prev;
                const next = new Map(prev);
                next.delete(requestId);
                return next;
              });
              setTerminalApprovals((prev) => {
                if (prev.some((item) => item.requestId === requestId)) {
                  return prev;
                }
                return [
                  ...prev,
                  {
                    requestId,
                    toolName: dead?.toolName || "",
                    title: t("approval.expiredTitle", "Approval expired"),
                    message: t(
                      "approval.expiredHint",
                      "This approval timed out. The tool was not executed.",
                    ),
                  },
                ];
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

      {/* Dead approvals: expired / refused by the backend. Stay until the
          user dismisses them — a card that vanishes teaches nothing. */}
      {terminalApprovals.map((dead) => (
        <div
          key={`terminal-${dead.requestId}`}
          style={{
            position: "fixed",
            bottom: 80,
            right: 24,
            width: "min(420px, calc(100vw - 48px))",
            zIndex: 1000,
          }}
        >
          <ApprovalCard
            requestId={dead.requestId}
            toolName={dead.toolName}
            severity="LOW"
            findingsCount={0}
            findingsSummary=""
            toolParams={{}}
            createdAt={0}
            timeoutSeconds={0}
            onApprove={async () => {}}
            onDeny={async () => {}}
            terminal={{ title: dead.title, message: dead.message }}
            onClose={() =>
              setTerminalApprovals((prev) =>
                prev.filter((item) => item.requestId !== dead.requestId),
              )
            }
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


    {/* ─── M4 资源整合：资源浮层（跨目录检索 / 知识库选择） ─────────── */}
    <CascadePickerModal
      open={pickerMode !== null}
      mode={pickerMode ?? "files"}
      rootPath={pickerRoot}
      onClose={() => {
        setPickerMode(null);
        setPickerRoot(null);
      }}
      checked={checkedKeys}
      onToggle={toggleCascadeNode}
    />
    <ScenePickerModal
      open={scenePickerOpen}
      onClose={() => setScenePickerOpen(false)}
      onPick={handleScenePick}
      currentSceneId={sceneId}
      embedded={isEmbeddedMode}
    />

    </ChatDisplayConfigContext.Provider>
  );
}
