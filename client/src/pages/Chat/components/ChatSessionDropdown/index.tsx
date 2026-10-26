import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Spin, Input, Tooltip } from "antd";
import { RightOutlined } from "@ant-design/icons";
import { FixedSizeList, type ListChildComponentProps } from "react-window";
import { IconButton } from "@agentscope-ai/design";
import { SparkOperateRightLine } from "@agentscope-ai/icons";
import {
  useChatAnywhereSessionsState,
  type IAgentScopeRuntimeWebUISession,
} from "@agentscope-ai/chat";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import type { ChatStatus } from "../../../../api/types/chat";
import { chatApi } from "../../../../api/modules/chat";
import sessionApi from "../../sessionApi";
import ChatSessionItem from "../ChatSessionItem";
import { getChannelLabel } from "../../../Control/Channels/components";
import {
  ContextMenu,
  useContextMenu,
  type ContextMenuItem,
} from "../../../../components/ContextMenu";
import styles from "./index.module.less";

/** Fixed height of each session item in pixels (matches CSS min-height) */
/**
 * Fixed height of each session item in pixels (matches CSS min-height).
 *
 * B2 moved 编辑/删除/置顶 out of the title area into their own row under the
 * meta line, so a row is 104px: 12 top padding + 30 title + 20 meta
 * + 24 action row + 1 border + 17 slack.
 */
const ITEM_HEIGHT = 104;

/** 左栏分页（B5）：首屏只取一页 20 条，滚到底才要下一页。 */
const PAGE_SIZE = 20;

/** Data passed to each row via FixedSizeList's itemData prop */
interface SessionRowData {
  sortedSessions: ExtendedChatSession[];
  currentSessionId: string | undefined;
  /** 左栏形态判定当前会话用（后端 UUID）；见 Props.currentBackendId */
  currentBackendId?: string | null;
  editingSessionId: string | null;
  editValue: string;
  t: ReturnType<typeof useTranslation>["t"];
  handleSessionClick: (sessionId: string) => void;
  handleEditStart: (sessionId: string, currentName: string) => void;
  handleDelete: (sessionId: string) => void;
  handlePinToggle: (sessionId: string) => void;
  handleEditChange: (value: string) => void;
  handleEditSubmit: () => void;
  handleEditCancel: () => void;
  handleItemContextMenu: (sessionId: string, event: React.MouseEvent) => void;
  // 批次 B2：caret 长在标题行、面板在行下，展开态得从上层传下来
  expandedId: string | null;
  onToggleExpand: (sessionId: string) => void;
}

/**
 * 单行会话（浮层与左栏共用一份渲染，避免两处各写一套 props 映射）。
 * `extra`：左栏形态挂在当前会话行下方的内容（会话资源面板，批次 D2）。
 */
const SessionLine = React.memo(function SessionLine({
  session,
  data,
  extra,
}: {
  session: ExtendedChatSession;
  data: SessionRowData;
  extra?: React.ReactNode;
}) {
  const channelKey = session.channel?.trim() || "";
  const channelLabel = channelKey
    ? getChannelLabel(channelKey, data.t)
    : undefined;
  const isEditing = data.editingSessionId === session.id;
  const expanded = data.expandedId === session.id;

  return (
    <div className={styles.lineWrap}>
      <ChatSessionItem
        sessionId={session.id!}
        name={session.name || "New Chat"}
        time={formatCreatedAt(session.createdAt ?? null)}
        channelKey={channelKey || undefined}
        channelLabel={channelLabel}
        chatStatus={session.status}
        generating={session.generating}
        pinned={session.pinned ?? false}
        active={
          data.currentBackendId
            ? getBackendId(session) === data.currentBackendId
            : session.id === data.currentSessionId
        }
        editing={isEditing}
        editValue={isEditing ? data.editValue : undefined}
        onClick={data.handleSessionClick}
        onEdit={data.handleEditStart}
        onDelete={data.handleDelete}
        onPin={data.handlePinToggle}
        onEditChange={data.handleEditChange}
        onEditSubmit={data.handleEditSubmit}
        onEditCancel={data.handleEditCancel}
        onContextMenu={data.handleItemContextMenu}
        // 批次 B2：caret 挂在标题行末尾。原来它长在资源面板头部
        // （"会话资源"标题 + caret），和会话本身割裂，已删。只有当前
        // 会话有资源面板，caret 也就只出现在这一行。
        expandSlot={
          extra ? (
            <Tooltip
              title={
                expanded
                  ? data.t("chat.collapseSessionResources", "收起会话资源")
                  : data.t("chat.expandSessionResources", "展开会话资源")
              }
              mouseEnterDelay={0.6}
            >
              <span
                role="button"
                tabIndex={0}
                className={styles.expandCaret}
                aria-expanded={expanded}
                aria-controls={`chat-res-${session.id}`}
                aria-label={
                  expanded
                    ? data.t("chat.collapseSessionResources", "收起会话资源")
                    : data.t("chat.expandSessionResources", "展开会话资源")
                }
                onClick={(e) => {
                  e.stopPropagation();
                  data.onToggleExpand(session.id);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    e.stopPropagation();
                    data.onToggleExpand(session.id);
                  }
                }}
              >
                <RightOutlined
                  className={expanded ? styles.caretOpen : styles.caret}
                />
              </span>
            </Tooltip>
          ) : undefined
        }
      />
      {extra}
    </div>
  );
});

/** 虚拟化行（浮层形态）：定高壳 + 共用行渲染 */
const SessionRow = React.memo(function SessionRow({
  index,
  style,
  data,
}: ListChildComponentProps<SessionRowData>) {
  const session = data.sortedSessions[index];
  if (!session) return null;
  return (
    <div style={style}>
      <SessionLine session={session} data={data} />
    </div>
  );
});

/** Sessions from CoApis backend include extra fields beyond the runtime UI type */
export interface ExtendedChatSession extends IAgentScopeRuntimeWebUISession {
  realId?: string;
  sessionId?: string;
  userId?: string;
  channel?: string;
  createdAt?: string | null;
  meta?: Record<string, unknown>;
  status?: ChatStatus;
  generating?: boolean;
  pinned?: boolean;
}

interface ChatSessionDropdownProps {
  /** Whether the dropdown is visible（sidebar 变体常驻，可省略） */
  open?: boolean;
  /** Callback to close the dropdown（sidebar 变体可省略） */
  onClose?: () => void;
  /** Search keyword to filter sessions */
  searchKeyword?: string;
  /** Show search input */
  showSearch?: boolean;
  /** Callback when search keyword changes */
  onSearchChange?: (keyword: string) => void;
  /** 选择模式：提供后点击会话不跳转，而是回调（M4 历史会话引用芯片） */
  onSelect?: (session: { id: string; name: string }) => void;
  /** 最大高度（px）：调用方按输入框位置测量传入，避免盖住输入框/超出显示区 */
  maxHeight?: number;
  /**
   * 呈现形态（批次 D1）：
   *  - "overlay"（默认）：顶栏触发的浮层面板（历史行为，含标题栏/关闭按钮）
   *  - "sidebar"：嵌在固定左栏里 —— 常驻、无标题栏/关闭按钮、列表不虚拟化
   *    （当前会话要在自己节点下方内嵌资源面板，虚拟化做不到变高行）
   */
  variant?: "overlay" | "sidebar";
  /** 左栏形态：给指定会话（通常=当前会话）在其行下方追加内容（会话资源）。
   *  第二参数是后端 chat id（资源台账按它取数），组件自己算，调用方不必关心。 */
  renderItemExtra?: (
    session: ExtendedChatSession,
    backendId: string | null,
  ) => React.ReactNode;
  /** 左栏形态判定「当前会话」用：页面层的 chatId（后端 UUID）。
   *  左栏挂在 ChatAnywhere provider 之外，useChatAnywhereSessionsState() 在这里
   *  只能拿到默认空值——靠它匹配，当前会话的高亮和行下方内容都会恒失效。 */
  currentBackendId?: string | null;
  /** 受控展开态（侧栏常驻展开）。 */
  onOpenChange?: (open: boolean) => void;
  /** 台账写入后自增：透传给行下方的资源面板，让它重新取数。 */
  refreshKey?: number;
  /**
   * 交互模式（overlay 变体）："select" 点击即选中并收起；"manage" 点击进管理页。
   * 侧栏变体不传，走 onSelect/onSelectSession。
   */
  mode?: "select" | "manage";
  /** 移动端全屏态：选中后要收起全屏面板。 */
  isMobile?: boolean;
}

/** Format an ISO 8601 timestamp to YYYY-MM-DD HH:mm:ss */
const formatCreatedAt = (raw: string | null | undefined): string => {
  if (!raw) return "";
  const date = new Date(raw);
  if (isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(
    date.getDate(),
  )} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(
    date.getSeconds(),
  )}`;
};

/** Resolve the real backend UUID from an extended session (id may be a local timestamp) */
const getBackendId = (session: ExtendedChatSession): string | null => {
  if (session.realId) return session.realId;
  const id = session.id;
  if (!/^\d+$/.test(id)) return id;
  return null;
};

const ChatSessionDropdown: React.FC<ChatSessionDropdownProps> = (props) => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { currentSessionId, setCurrentSessionId, setSessions } =
    useChatAnywhereSessionsState();

  // Local session list — bypass library's stale context state
  const [localSessions, setLocalSessions] = useState<ExtendedChatSession[]>([]);

  /** Create a new session and close the dropdown */
  const handleCreateSession = useCallback(async () => {
    try {
      await sessionApi.createSession({ name: '' });
      // Refresh the session list so the new chat appears immediately
      const list = await sessionApi.getSessionList();
      setLocalSessions(list as unknown as ExtendedChatSession[]);
      setSessions(list);
    } catch (err) {
      console.error('[NewChat] Failed:', err);
    }
    props.onClose?.();
  }, [props.onClose, setSessions]);

  /** ID of the session currently being renamed */
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  /** Current value of the rename input */
  const [editValue, setEditValue] = useState("");

  /** Whether the session list is being fetched (default true because destroyOnClose re-mounts) */
  const [listLoading, setListLoading] = useState(true);

  /** Height of the virtual list container — fixed value since ResizeObserver
   *  doesn't reliably fire inside Popover portals */
  const [listHeight, setListHeight] = useState(360);

  // ── 左栏分页（B5）─────────────────────────────────────────────────
  // 原先每次打开都 getSessionList() 全量拉 100 条，左栏一打开就要等整包数据 ——
  // 这是「加载会话列表非常慢」的第一根因。现在首屏只要 20 条，触底再要下一页。
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  /** 后端返回的总条数：分页文案与「是否还有下一页」都看它。 */
  const [total, setTotal] = useState(0);
  /** 已加载条数：触底请求下一页时的 offset。用 ref 免得闭包读到旧长度。 */
  const loadedRef = useRef(0);

  // ── 左栏展开位（B4）───────────────────────────────────────────────
  // 资源下拉挂在「展开的那一行」下方，默认就是当前会话；点别的会话跟过去。
  // 一次只展开一行：多行同时展开会把左栏变成资源墙，列表就没法扫了。
  const [expandedId, setExpandedId] = useState<string | null>(
    props.currentBackendId ?? null,
  );

  /**
   * 展开位切换。入参是**后端 id**（不是前端 chatId）：展开态、资源面板、
   * 高亮判定全部按后端 UUID 记账，传前端 id 会让面板挂在错误的行下。
   */
  const handleToggleExpand = useCallback((backendId: string | null) => {
    if (!backendId) return;
    setExpandedId((prev) => (prev === backendId ? null : backendId));
  }, []);

  // 当前会话变化（新建 / 切换 / 删除后回退）时，展开位跟着走
  useEffect(() => {
    if (props.variant === "sidebar" && props.currentBackendId) {
      setExpandedId(props.currentBackendId);
    }
  }, [props.variant, props.currentBackendId]);
  const observerRef = useRef<ResizeObserver | null>(null);

  /** Callback ref: attach a ResizeObserver whenever the wrapper DOM node appears */
  const listWrapperRef = useCallback((node: HTMLDivElement | null) => {
    // Cleanup previous observer
    if (observerRef.current) {
      observerRef.current.disconnect();
      observerRef.current = null;
    }

    if (!node) return;

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const height = entry.contentRect.height;
        if (height > 100) {
          setListHeight(height);
        }
      }
    });

    observer.observe(node);
    observerRef.current = observer;

    // Measure immediately in case layout is already stable
    const initialHeight = node.clientHeight;
    if (initialHeight > 100) {
      setListHeight(initialHeight);
    }
  }, []);

  /** Shared context menu — only one instance instead of one per item */
  const sharedContextMenu = useContextMenu();
  const [contextMenuSessionId, setContextMenuSessionId] = useState<
    string | null
  >(null);

  /** Sessions sorted by pinned first, then by updatedAt descending */
  const sortedSessions = useMemo(() => {
    const sessions = [...localSessions].sort((a, b) => {
      const extA = a as ExtendedChatSession;
      const extB = b as ExtendedChatSession;

      if (extA.pinned && !extB.pinned) return -1;
      if (!extA.pinned && extB.pinned) return 1;

      const aTime = (extA as any).updatedAt || extA.createdAt;
      const bTime = (extB as any).updatedAt || extB.createdAt;
      if (aTime && bTime) return bTime.localeCompare(aTime);
      if (aTime) return -1;
      if (bTime) return 1;
      return 0;
    });

    // 根据搜索关键词过滤
    if (props.searchKeyword) {
      const keyword = props.searchKeyword.toLowerCase();
      return sessions.filter(s => 
        s.name?.toLowerCase().includes(keyword)
      );
    }

    return sessions;
  }, [localSessions, props.searchKeyword]);

  /** 把一页并进已有列表：按 id 去重，保持已加载顺序。 */
  const mergePages = useCallback(
    (prev: ExtendedChatSession[], incoming: ExtendedChatSession[]) => {
      const seen = new Set(prev.map((s) => s.id));
      const extra = incoming.filter((s) => s.id && !seen.has(s.id));
      return extra.length ? [...prev, ...extra] : prev;
    },
    [],
  );

  /** 拉一页会话。append=false 首屏/刷新（整表替换）；true 触底追加。 */
  const loadSessions = useCallback(
    async (opts?: { append?: boolean }) => {
      const append = opts?.append === true;
      const offset = append ? loadedRef.current : 0;
      if (append) setLoadingMore(true);
      else setListLoading(true);
      try {
        const page = await sessionApi.getSessionListPage(offset, PAGE_SIZE);
        const mapped = page.sessions as unknown as ExtendedChatSession[];
        setLocalSessions((prev) => {
          const next = append ? mergePages(prev, mapped) : mapped;
          loadedRef.current = next.length;
          return next;
        });
        setSessions(mapped as never);
        setTotal(page.total);
        setHasMore(page.hasMore);
      } catch (err) {
        console.error(`[ChatSessionDropdown] load failed:`, err);
      } finally {
        setListLoading(false);
        setLoadingMore(false);
      }
    },
    [mergePages, setSessions],
  );

  /** 首屏/刷新：挂载、切 agent、下拉重新打开时都要拿到最新的第一页。 */
  useEffect(() => {
    if (props.variant === "sidebar" || props.open) {
      loadSessions();
    }
  }, [props.variant, props.open, props.refreshKey, loadSessions]);

  /** 滚动触底（距底 80px）加载下一页。 */
  const handleListScroll = useCallback(
    (e: React.UIEvent<HTMLDivElement>) => {
      if (
        props.variant !== "sidebar" ||
        !hasMore ||
        loadingMore ||
        listLoading
      ) {
        return;
      }
      const el = e.currentTarget;
      if (el.scrollHeight - el.scrollTop - el.clientHeight < 80) {
        loadSessions({ append: true });
      }
    },
    [props.variant, hasMore, loadingMore, listLoading, loadSessions],
  );

  /** Navigate to a session and close the dropdown (or select it in select mode) */
  const handleSessionClick = useCallback(
    (sessionId: string) => {
      // 入参是前端 chatId，行数据在 sessions 里；展开态/资源面板按后端 UUID 记账，
      // 所以要先从行上取 backendId，不能拿前端 id 去拼路由。
      const session = localSessions.find(
        (s) => (s as ExtendedChatSession).id === sessionId,
      );
      const backendId = session ? getBackendId(session) : null;
      navigate(
        backendId
          ? `/chat/${encodeURIComponent(backendId)}`
          : `/chat/${encodeURIComponent(sessionId)}`,
      );
      // 左栏形态：点一行就把资源下拉展开到这一行；再点已展开那行则收起。
      if (props.variant === "sidebar") {
        const expandKey = backendId ?? sessionId;
        setExpandedId((prev) => (prev === expandKey ? null : expandKey));
      }
      if (props.mode === "select" && props.onSelect) {
        props.onSelect({
          id: sessionId,
          name: (session as ExtendedChatSession)?.name ?? "",
        });
      }
      // Close dropdown on mobile after selection
      if (props.isMobile) {
        props.onOpenChange?.(false);
      }
    },
    [
      navigate,
      props.mode,
      props.onSelect,
      props.isMobile,
      props.onOpenChange,
      props.variant,
    ],
  );

  /** Start editing a session name */
  const handleEditStart = useCallback(
    (sessionId: string, currentName: string) => {
      setEditingSessionId(sessionId);
      setEditValue(currentName);
    },
    [],
  );

  /** Cancel editing */
  const handleEditCancel = useCallback(() => {
    setEditingSessionId(null);
    setEditValue("");
  }, []);

  /** Submit rename */
  const handleEditSubmit = useCallback(async () => {
    if (!editingSessionId || !editValue.trim()) {
      handleEditCancel();
      return;
    }

    const session = localSessions.find((s) => s.id === editingSessionId) as
      | ExtendedChatSession
      | undefined;
    const backendId = session ? getBackendId(session) : null;

    if (backendId) {
      try {
        await chatApi.updateChat(backendId, { name: editValue.trim() });
      } catch {
        // Silently fail — will sync on next list load
      }
    }

    // 同上：改名后左栏读的是 localSessions，两边都要落
      const nextRenamed = localSessions.map((s) =>
        s.id === editingSessionId ? { ...s, name: editValue.trim() } : s,
      );
      setLocalSessions(nextRenamed);
      setSessions(nextRenamed);

    handleEditCancel();
  }, [editingSessionId, editValue, localSessions, setSessions, handleEditCancel]);

  /** Delete a session */
  const handleDelete = useCallback(
    async (sessionId: string) => {
      const session = localSessions.find((s) => s.id === sessionId) as
        | ExtendedChatSession
        | undefined;
      const backendId = session ? getBackendId(session) : null;

      if (backendId) {
        try {
          await chatApi.deleteChat(backendId);
        } catch {
          // Silently fail
        }
      }

      const filtered = localSessions.filter((s) => s.id !== sessionId);
      setLocalSessions(filtered);
      setSessions(filtered);
      // 页脚显示的是后端 total，删完不回落就会一直显示"共 250 条"
      setTotal((prev) => Math.max(0, prev - 1));

      if (sessionId === currentSessionId) {
        setCurrentSessionId(undefined);
      }
    },
    [localSessions, currentSessionId, setCurrentSessionId, setSessions],
  );

  /** Toggle pin status */
  const handlePinToggle = useCallback(
    async (sessionId: string) => {
      const session = localSessions.find((s) => s.id === sessionId) as
        | ExtendedChatSession
        | undefined;
      const backendId = session ? getBackendId(session) : null;
      const currentPinned = session?.pinned ?? false;

      if (backendId) {
        try {
          await chatApi.updateChat(backendId, { pinned: !currentPinned });
        } catch {
          // Silently fail
        }
      }

      // 左栏渲染的是 localSessions，只写 context 的话点完置顶界面不动
      const nextPinned = localSessions.map((s) =>
        s.id === sessionId ? { ...s, pinned: !currentPinned } : s,
      );
      setLocalSessions(nextPinned);
      setSessions(nextPinned);
    },
    [localSessions, setSessions],
  );

  /** Context menu for session items */
  const handleItemContextMenu = useCallback(
    (sessionId: string, event: React.MouseEvent) => {
      event.preventDefault();
      setContextMenuSessionId(sessionId);
      sharedContextMenu.show(event);
    },
    [sharedContextMenu],
  );

  /** Context menu items */
  const contextMenuItems: ContextMenuItem[] = useMemo(() => {
    if (!contextMenuSessionId) return [];

    const session = localSessions.find((s) => s.id === contextMenuSessionId) as
      | ExtendedChatSession
      | undefined;
    const pinned = session?.pinned ?? false;

    return [
      {
        key: "rename",
        label: t("chat.rename"),
        onClick: () => {
          const name = session?.name || "New Chat";
          handleEditStart(contextMenuSessionId, name);
        },
      },
      {
        key: "pin",
        label: pinned ? t("chat.unpin") : t("chat.pin"),
        onClick: () => handlePinToggle(contextMenuSessionId),
      },
      {
        key: "delete",
        label: t("chat.delete"),
        danger: true,
        onClick: () => handleDelete(contextMenuSessionId),
      },
    ];
  }, [contextMenuSessionId, localSessions, t, handleEditStart, handlePinToggle, handleDelete]);

  const isSidebar = props.variant === "sidebar";
  const isCurrentSession = (session: ExtendedChatSession): boolean =>
    props.currentBackendId
      ? getBackendId(session) === props.currentBackendId
      : session.id === currentSessionId;

  const rowHandlers = {
    sortedSessions,
    currentSessionId,
    currentBackendId: props.currentBackendId,
    editingSessionId,
    editValue,
    t,
    handleSessionClick,
    handleEditStart,
    handleDelete,
    handlePinToggle,
    handleEditChange: setEditValue,
    handleEditSubmit,
    handleEditCancel,
    handleItemContextMenu,
    // 批次 B2：caret 在标题行，展开态与切换回调要一起下去
    expandedId,
    onToggleExpand: handleToggleExpand,
  };

  return (
    <div
      className={
        isSidebar
          ? `${styles.dropdownContainer} ${styles.sidebarContainer}`
          : styles.dropdownContainer
      }
      style={props.maxHeight ? { maxHeight: props.maxHeight } : undefined}
    >
      {/* Header bar（浮层形态才有；左栏是常驻面板，不需要「关闭」） */}
      {!isSidebar && (
        <div className={styles.header}>
          <div className={styles.headerLeft}>
            <span className={styles.headerTitle}>{t("chat.allChats")}</span>
          </div>
          <div className={styles.headerRight}>
            <IconButton
              bordered={false}
              icon={<SparkOperateRightLine />}
              onClick={props.onClose}
            />
          </div>
        </div>
      )}

      {/* Create new chat button */}
      <div className={styles.createSection}>
        <div className={styles.createButton} onClick={handleCreateSession}>
          {t("chat.createNewChat")}
        </div>
      </div>

      {/* Search box */}
      {props.showSearch && (
        <div style={{ padding: "0 16px 12px" }}>
          <Input.Search
            placeholder={t("chat.searchHistory", "搜索聊天历史...")}
            allowClear
            value={props.searchKeyword}
            onChange={(e) => props.onSearchChange?.(e.target.value)}
          />
        </div>
      )}

      {/* Session list */}
      {/* B5: onScroll 必须挂在真正会滚动的容器上。
          .listWrapper 是 overflow:hidden（只作浮层定位上下文，永不滚动），
          左栏的滚动容器是内层 .list —— 挂错地方 = 分页永不触发。 */}
      <div
        className={styles.listWrapper}
        ref={listWrapperRef}
      >
        <div className={styles.topGradient} />
        {listLoading ? (
          <div
            style={{
              display: "flex",
              justifyContent: "center",
              padding: 40,
            }}
          >
            <Spin />
          </div>
        ) : (
          <>
            {/* Background loading — only while a page is actually being
                fetched. Gating on `loadingMore` keeps the spinner from
                sitting in the list permanently whenever content overflows. */}
            {sortedSessions.length * ITEM_HEIGHT > listHeight && loadingMore && (
              <div className={styles.virtualListBackground}>
                <Spin size="small" />
              </div>
            )}
            {isSidebar ? (
              /* 左栏形态：普通滚动列表。当前会话要在自己节点下方内嵌资源
                 面板（变高行），虚拟化定高列表做不到，所以这里不虚拟化。 */
              <div className={styles.list} onScroll={handleListScroll}>
                {sortedSessions.map((session) => (
                  <SessionLine
                    key={session.id}
                    session={session}
                    data={rowHandlers}
                    extra={
                      props.renderItemExtra &&
                      (expandedId
                        ? session.id === expandedId
                        : isCurrentSession(session))
                        ? props.renderItemExtra(
                            session,
                            getBackendId(session),
                          )
                        : null
                    }
                  />
                ))}
                {loadingMore && (
                  <div className={styles.pageFooter}>
                    <Spin size="small" />
                    <span>{t("chat.loadingMore", "加载中…")}</span>
                  </div>
                )}
                {!loadingMore && sortedSessions.length > 0 && (
                  <div className={styles.pageFooter}>
                    {hasMore
                      ? t(
                          "chat.scrollForMore",
                          `继续向下滚动加载更多（已加载 ${sortedSessions.length}/${total}）`,
                        )
                      : t(
                          "chat.allLoaded",
                          `已加载全部会话（${total}）`,
                        )}
                  </div>
                )}
              </div>
            ) : (
              <FixedSizeList
                height={listHeight}
                width="100%"
                itemCount={sortedSessions.length}
                itemSize={ITEM_HEIGHT}
                overscanCount={20}
                itemData={rowHandlers}
                className={styles.list}
              >
                {SessionRow}
              </FixedSizeList>
            )}
          </>
        )}
        <div className={styles.bottomGradient} />
      </div>

      {/* Shared context menu — single instance for all session items */}
      <ContextMenu
        visible={sharedContextMenu.visible}
        x={sharedContextMenu.x}
        y={sharedContextMenu.y}
        items={contextMenuItems}
        onClose={() => {
          sharedContextMenu.hide();
          setContextMenuSessionId(null);
        }}
      />
    </div>
  );
};

export default ChatSessionDropdown;
