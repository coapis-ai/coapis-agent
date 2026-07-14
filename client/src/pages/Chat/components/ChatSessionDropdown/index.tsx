import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Spin, Input } from "antd";
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
import { useAgentStore } from "../../../../stores/agentStore";
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
const ITEM_HEIGHT = 77;

/** Data passed to each row via FixedSizeList's itemData prop */
interface SessionRowData {
  sortedSessions: ExtendedChatSession[];
  currentSessionId: string | undefined;
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
}

/** Memoized row renderer — only re-renders when its specific props change */
const SessionRow = React.memo(function SessionRow({
  index,
  style,
  data,
}: ListChildComponentProps<SessionRowData>) {
  const session = data.sortedSessions[index];
  const channelKey = session.channel?.trim() || "";
  const channelLabel = channelKey
    ? getChannelLabel(channelKey, data.t)
    : undefined;
  const isEditing = data.editingSessionId === session.id;

  return (
    <div style={style}>
      <ChatSessionItem
        sessionId={session.id!}
        name={session.name || "New Chat"}
        time={formatCreatedAt(session.createdAt ?? null)}
        channelKey={channelKey || undefined}
        channelLabel={channelLabel}
        chatStatus={session.status}
        generating={session.generating}
        pinned={session.pinned}
        active={session.id === data.currentSessionId}
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
      />
    </div>
  );
});

/** Sessions from CoApis backend include extra fields beyond the runtime UI type */
interface ExtendedChatSession extends IAgentScopeRuntimeWebUISession {
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
  /** Whether the dropdown is visible */
  open: boolean;
  /** Callback to close the dropdown */
  onClose: () => void;
  /** Search keyword to filter sessions */
  searchKeyword?: string;
  /** Show search input */
  showSearch?: boolean;
  /** Callback when search keyword changes */
  onSearchChange?: (keyword: string) => void;
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
    props.onClose();
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

  /** Load session list on mount and when selectedAgent changes */
  const selectedAgent = useAgentStore((s) => s.selectedAgent);
  useEffect(() => {
    console.log(`[ChatSessionDropdown] loading sessions (agent=${selectedAgent})...`);
    setListLoading(true);
    sessionApi
      .getSessionList()
      .then((list) => {
        console.log(`[ChatSessionDropdown] loaded ${list.length} sessions`);
        setLocalSessions(list as unknown as ExtendedChatSession[]);
        setSessions(list); // also sync to library context
        setListLoading(false);
      })
      .catch((err) => {
        console.error(`[ChatSessionDropdown] load failed:`, err);
        setListLoading(false);
      });
  }, [selectedAgent]); // re-load when agent changes

  /** Refresh session list every time the dropdown opens, so newly created
   *  chats from the main chat area appear immediately without page refresh */
  useEffect(() => {
    if (!props.open) return;
    sessionApi
      .getSessionList()
      .then((list) => {
        setLocalSessions(list as unknown as ExtendedChatSession[]);
        setSessions(list);
      })
      .catch((err) => {
        console.error(`[ChatSessionDropdown] refresh on open failed:`, err);
      });
  }, [props.open, setSessions]);

  /** Navigate to a session and close the dropdown */
  const handleSessionClick = useCallback(
    (sessionId: string) => {
      // Resolve the real backend UUID — session.id may be a local timestamp
      // after applyChatsToSessionList merging, but the URL needs the UUID.
      const session = localSessions.find((s) => s.id === sessionId);
      const backendId = session ? getBackendId(session) : null;
      const targetId = backendId || sessionId;
      console.log(`[ChatSessionDropdown] handleSessionClick: sessionId=${sessionId}, backendId=${backendId}, targetId=${targetId}`);
      props.onClose();
      navigate(`/chat/${targetId}`, { replace: true });
    },
    [props.onClose, localSessions, navigate],
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

    setSessions(
      localSessions.map((s) =>
        s.id === editingSessionId
          ? { ...s, name: editValue.trim() }
          : s,
      ),
    );

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

      setSessions(
        localSessions.map((s) =>
          s.id === sessionId
            ? { ...s, pinned: !currentPinned }
            : s,
        ),
      );
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

  return (
    <div className={styles.dropdownContainer}>
      {/* Header bar */}
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
      <div className={styles.listWrapper} ref={listWrapperRef}>
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
            {/* Background loading — only show when content overflows the container,
                so it's visible through unrendered gaps during fast scroll */}
            {sortedSessions.length * ITEM_HEIGHT > listHeight && (
              <div className={styles.virtualListBackground}>
                <Spin size="small" />
              </div>
            )}
            <FixedSizeList
              height={listHeight}
              width="100%"
              itemCount={sortedSessions.length}
              itemSize={ITEM_HEIGHT}
              overscanCount={20}
              itemData={{
                sortedSessions,
                currentSessionId,
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
              }}
              className={styles.list}
            >
              {SessionRow}
            </FixedSizeList>
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
