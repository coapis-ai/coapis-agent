import React from "react";
import { useChatAnywhereSessionsState } from "@agentscope-ai/chat";
import styles from "./index.module.less";

/**
 * Find the current session using multiple matching strategies.
 *
 * After applyChatsToSessionList merges backend data with local sessions,
 * a session's id might be a local timestamp while currentSessionId is the
 * backend UUID (from URL).  We need to match by realId and sessionId too.
 */
function findSession(
  sessions: readonly any[],
  currentSessionId: string | null | undefined,
) {
  if (!currentSessionId || sessions.length === 0) return undefined;
  return (
    sessions.find((s) => s.id === currentSessionId) ??
    sessions.find((s) => (s as any).realId === currentSessionId) ??
    sessions.find((s) => (s as any).sessionId === currentSessionId)
  );
}

const ChatHeaderTitle: React.FC = () => {
  const { sessions, currentSessionId } = useChatAnywhereSessionsState();
  const currentSession = findSession(sessions, currentSessionId);
  const chatName = currentSession?.name || "New Chat";

  return <span className={styles.chatName}>{chatName}</span>;
};

export default ChatHeaderTitle;
