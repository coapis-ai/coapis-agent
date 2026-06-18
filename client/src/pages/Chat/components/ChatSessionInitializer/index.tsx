import React, { useEffect, useMemo, useRef } from "react";
import { useLocation } from "react-router-dom";
import { useChatAnywhereSessionsState } from "@agentscope-ai/chat";

/**
 * URL chatId → context currentSessionId (one direction of bidirectional sync).
 *
 * Only reacts to URL or session list changes. currentSessionId is read via ref
 * to avoid triggering the effect when the context changes from the other direction
 * (context → URL via onSessionSelected), which would cause circular re-loads.
 */
const ChatSessionInitializer: React.FC = () => {
  const location = useLocation();
  const chatId = useMemo(() => {
    const match = location.pathname.match(/^\/chat\/(.+)$/);
    return match?.[1];
  }, [location.pathname]);

  const { sessions, currentSessionId, setCurrentSessionId } =
    useChatAnywhereSessionsState();

  const currentSessionIdRef = useRef(currentSessionId);
  currentSessionIdRef.current = currentSessionId;

  useEffect(() => {
    // ── No chatId in URL: auto-select latest session ──
    // This handles first load (/chat) and agent switch (navigates to /chat).
    if (!chatId) {
      if (sessions.length > 0 && !currentSessionIdRef.current) {
        const latest = sessions[0]; // sessions are sorted newest-first
        const targetId = (latest as any).realId || latest.id;
        console.log(`[ChatSessionInitializer] no chatId, auto-selecting latest: id=${targetId}`);
        setCurrentSessionId(targetId);
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
      setCurrentSessionId(chatId);
    }
    // Intentionally exclude currentSessionId from deps: only react to URL / session list changes.
    // currentSessionId is read via ref to avoid circular triggers.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatId, sessions, setCurrentSessionId]);

  return null;
};

export default ChatSessionInitializer;
