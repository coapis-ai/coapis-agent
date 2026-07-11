import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { AgentSummary } from "../api/types/agents";
import { getAgentStorageKey, getLastUsedAgentKey } from "../api/config";

/**
 * Storage key used by both sessionStorage (per-tab state) and localStorage
 * (cross-tab shared state).
 *
 * IMPORTANT: The key is user-scoped to prevent agent leakage between users.
 * NOTE: We use a placeholder here; actual key is resolved dynamically in storage methods.
 */
const STORAGE_KEY = "coapis-agent-storage";  // Placeholder, actual key is dynamic

interface AgentStore {
  selectedAgent: string;
  agents: AgentSummary[];
  /** Per-agent last active chat ID for restoring on agent switch */
  lastChatIdByAgent: Record<string, string>;
  setSelectedAgent: (agentId: string) => void;
  setAgents: (agents: AgentSummary[]) => void;
  addAgent: (agent: AgentSummary) => void;
  removeAgent: (agentId: string) => void;
  updateAgent: (agentId: string, updates: Partial<AgentSummary>) => void;
  setLastChatId: (agentId: string, chatId: string) => void;
  getLastChatId: (agentId: string) => string | undefined;
}

/**
 * Determines the initial selectedAgent for this tab.
 *
 * Priority:
 *  1. sessionStorage (returning to a tab that already picked an agent)
 *  2. localStorage lastUsedAgent (new tab inherits the most recent choice)
 *  3. "" (empty — Sidebar will resolve the user's default agent)
 */
function getInitialSelectedAgent(): string {
  // Get dynamic storage key for current user
  const dynamicKey = getAgentStorageKey();
  const dynamicLastUsedKey = getLastUsedAgentKey();

  // 1. sessionStorage: returning to a tab that already picked an agent
  try {
    const sessionValue = sessionStorage.getItem(dynamicKey);
    if (sessionValue) {
      const parsed = JSON.parse(sessionValue);
      const agent = parsed?.state?.selectedAgent;
      if (agent) return agent;
    }
  } catch {
    /* ignore */
  }
  // 2. Dedicated localStorage key (written by setSelectedAgent)
  try {
    const lastUsed = localStorage.getItem(dynamicLastUsedKey);
    if (lastUsed) return lastUsed;
  } catch {
    /* ignore */
  }
  // 3. Shared localStorage state (written by persist middleware)
  try {
    const shared = localStorage.getItem(dynamicKey);
    if (shared) {
      const parsed = JSON.parse(shared);
      const agent = parsed?.state?.selectedAgent;
      if (agent) return agent;
    }
  } catch {
    /* ignore */
  }
  return "";
}

export const useAgentStore = create<AgentStore>()(
  persist(
    (set, get) => ({
      selectedAgent: getInitialSelectedAgent(),
      agents: [],
      lastChatIdByAgent: {},

      setSelectedAgent: (agentId) => {
        set({ selectedAgent: agentId });
        // Persist to localStorage so new tabs inherit this choice
        // Use dynamic key for current user
        try {
          localStorage.setItem(getLastUsedAgentKey(), agentId);
        } catch {
          /* ignore */
        }
      },

      setAgents: (agents) => set({ agents }),

      addAgent: (agent) =>
        set((state) => ({
          agents: [...state.agents, agent],
        })),

      removeAgent: (agentId) =>
        set((state) => {
          const { [agentId]: _, ...remainingChatIds } = state.lastChatIdByAgent;
          return {
            agents: state.agents.filter((a) => a.id !== agentId),
            lastChatIdByAgent: remainingChatIds,
            ...(state.selectedAgent === agentId
              ? { selectedAgent: "" }
              : {}),
          };
        }),

      updateAgent: (agentId, updates) =>
        set((state) => ({
          agents: state.agents.map((a) =>
            a.id === agentId ? { ...a, ...updates } : a,
          ),
        })),

      setLastChatId: (agentId, chatId) =>
        set((state) => ({
          lastChatIdByAgent: { ...state.lastChatIdByAgent, [agentId]: chatId },
        })),

      getLastChatId: (agentId) => get().lastChatIdByAgent[agentId],
    }),
    {
      name: STORAGE_KEY,
      storage: {
        getItem: (_name) => {
          // Use dynamic key for current user
          const dynamicKey = getAgentStorageKey();
          try {
            // Read per-tab state from sessionStorage
            const value = sessionStorage.getItem(dynamicKey);
            if (value) return JSON.parse(value);
          } catch {
            /* ignore */
          }
          // Fall back to localStorage for shared data (agents list, etc.)
          try {
            const shared = localStorage.getItem(dynamicKey);
            return shared ? JSON.parse(shared) : null;
          } catch (error) {
            console.error(`Failed to parse agent storage "${dynamicKey}":`, error);
            localStorage.removeItem(dynamicKey);
            return null;
          }
        },
        setItem: (_name, value) => {
          // Use dynamic key for current user
          const dynamicKey = getAgentStorageKey();
          try {
            // Per-tab state (includes selectedAgent)
            sessionStorage.setItem(dynamicKey, JSON.stringify(value));
          } catch {
            /* ignore */
          }
          try {
            // Shared state (agents list, lastChatIdByAgent)
            localStorage.setItem(dynamicKey, JSON.stringify(value));
          } catch (error) {
            console.error(`Failed to save agent storage "${dynamicKey}":`, error);
          }
        },
        removeItem: (_name) => {
          // Use dynamic key for current user
          const dynamicKey = getAgentStorageKey();
          sessionStorage.removeItem(dynamicKey);
          localStorage.removeItem(dynamicKey);
        },
      },
    },
  ),
);
