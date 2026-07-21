import React, { useEffect, useMemo, useRef } from "react";
import { useLocation } from "react-router-dom";
import {
  useChatAnywhereSessions,
  useChatAnywhereSessionsState,
} from "@agentscope-ai/chat";
import { useAgentStore } from "../../../../stores/agentStore";
import sessionApi from "../../sessionApi";

interface ChatSessionInitializerProps {
  /**
   * When ChatSessionInitializer sets currentSessionId, it sets this ref to true
   * first. onSessionSelected checks this ref and skips navigation when true,
   * breaking the URL ↔ session sync loop.
   */
  skipNextSessionSelectedRef: React.MutableRefObject<boolean>;
}

/**
 * URL chatId → context currentSessionId (one direction of bidirectional sync).
 *
 * Only reacts to URL or session list changes. currentSessionId is read via ref
 * to avoid triggering the effect when the context changes from the other direction
 * (context → URL via onSessionSelected), which would cause circular re-loads.
 *
 * COAPIS FIX: For brand-new agents with no existing sessions, we create a fresh
 * session up-front. This avoids the race in @agentscope-ai/chat where the first
 * user message is cleared by the session loader that runs when currentSessionId
 * changes from undefined to a new id during handleSubmit.
 *
 * COAPIS FIX 2: In embedded mode (scenes), chatId comes from window.__CHAT_SESSION_ID__
 * instead of URL, so we need to read from window object as well.
 */
const ChatSessionInitializer: React.FC<ChatSessionInitializerProps> = ({
  skipNextSessionSelectedRef,
}) => {
  const location = useLocation();
  
  // ⭐ 嵌入式模式：从 window 对象获取 chatId
  const isEmbeddedMode = useMemo(() => {
    return (window as any).__CHAT_MODE__ === 'embedded';
  }, []);
  
  const windowChatId = useMemo(() => {
    return (window as any).__CHAT_SESSION_ID__;
  }, []);
  
  const chatId = useMemo(() => {
    // 嵌入式模式：优先使用 window.__CHAT_SESSION_ID__
    if (isEmbeddedMode && windowChatId) {
      return windowChatId;
    }
    // 完整模式：从路由获取
    const match = location.pathname.match(/^\/chat\/(.+)$/);
    return match?.[1];
  }, [isEmbeddedMode, windowChatId, location.pathname]);

  const { sessions, currentSessionId, setCurrentSessionId } =
    useChatAnywhereSessionsState();
  const { createSession } = useChatAnywhereSessions();
  const selectedAgent = useAgentStore((s) => s.selectedAgent);

  const currentSessionIdRef = useRef(currentSessionId);
  currentSessionIdRef.current = currentSessionId;

  const createSessionRef = useRef(createSession);
  createSessionRef.current = createSession;

  const selectedAgentRef = useRef(selectedAgent);
  selectedAgentRef.current = selectedAgent;

  const creatingRef = useRef(false);

  // Keep sessionApi in sync with the library context so external guards can
  // create a session before the first message is sent.
  useEffect(() => {
    sessionApi.libraryCurrentSessionId = currentSessionIdRef.current ?? undefined;
    sessionApi.createSessionIfNeeded = async () => {
      if (currentSessionIdRef.current) return currentSessionIdRef.current;
      // Wait for an in-flight auto-create to finish.
      while (creatingRef.current) {
        await new Promise((resolve) => setTimeout(resolve, 50));
      }
      if (currentSessionIdRef.current) return currentSessionIdRef.current;
      creatingRef.current = true;
      try {
        const newId = await createSessionRef.current({ name: "" });
        return newId;
      } finally {
        creatingRef.current = false;
      }
    };
  }, [currentSessionId, createSession]);

  useEffect(() => {
    // ── No chatId in URL: auto-select latest session or create a fresh one ──
    // This handles first load (/chat) and agent switch (navigates to /chat).
    if (!chatId) {
      if (sessions.length > 0 && !currentSessionIdRef.current) {
        const latest = sessions[0]; // sessions are sorted newest-first
        const targetId = (latest as any).realId || latest.id;
        console.log(`[ChatSessionInitializer] no chatId, auto-selecting latest: id=${targetId}`);
        skipNextSessionSelectedRef.current = true;
        setCurrentSessionId(targetId);
      } else if (
        sessions.length === 0 &&
        !currentSessionIdRef.current &&
        !creatingRef.current &&
        sessionApi._sessionListLoaded
      ) {
        // Brand-new agent with no sessions: create one up-front so the first
        // message is sent in a stable session context.
        creatingRef.current = true;
        createSessionRef.current({ name: "" }).finally(() => {
          creatingRef.current = false;
        });
      }
      return;
    }

    if (sessions.length > 0) {
      // Match by id, realId (resolved UUID), or sessionId (backend session_id)
      // to handle both timestamp-based and UUID-based session IDs.
      const matching = sessions.find(
        (s) => s.id === chatId || (s as any).realId === chatId || (s as any).sessionId === chatId,
      );
      console.log(`[ChatSessionInitializer] chatId=${chatId}, sessions=${sessions.length}, matched=${!!matching}, currentSessionId=${currentSessionIdRef.current}`);
      if (matching) {
        console.log(`[ChatSessionInitializer] matched session: id=${matching.id}, realId=${(matching as any).realId}`);
        const targetId = (matching as any).realId || matching.id;
        if (currentSessionIdRef.current !== targetId) {
          skipNextSessionSelectedRef.current = true;
          setCurrentSessionId(targetId);
          return;
        }
      }
      // Already matched and current — nothing to do
      if (matching) return;
    }

    // Fallback: chatId not found in sessions yet (e.g., navigated via full page
    // reload from ChatSessionDropdown, or session list hasn't loaded yet).
    // Set chatId as current so sessionApi.getSession can fetch from backend
    // using the real UUID directly.
    if (currentSessionIdRef.current !== chatId) {
      console.log(`[ChatSessionInitializer] chatId=${chatId} not matched in ${sessions.length} sessions, setting as current`);
      skipNextSessionSelectedRef.current = true;
      setCurrentSessionId(chatId);
    }
    // Intentionally exclude currentSessionId from deps: only react to URL / session list changes.
    // currentSessionId is read via ref to avoid circular triggers.
    // selectedAgent is read via ref because agent changes already trigger remount of this component.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatId, sessions, setCurrentSessionId]);

  return null;
};

export default ChatSessionInitializer;
