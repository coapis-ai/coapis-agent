import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react';
import { getApiToken, clearAuthToken, getApiUrl, getAgentStorageKey, getLastUsedAgentKey } from '../api/config';
import { updateUserPreferences } from '../api/modules/user_me';

// ── Types ─────────────────────────────────────────────────────────────────

interface User {
  id: number;
  username: string;
  display_name: string | null;
  avatar_url: string | null;
  role: 'user' | 'admin' | 'superadmin';
  token_remaining: number;
  is_active: boolean;
}

interface UserPreferences {
  theme?: string;
  language?: string;
  sidebar_collapsed?: number;
  chat_hide_details?: number;
  chat_auto_scroll?: number;
  chat_font_size?: string;
  chat_code_theme?: string;
  email_notifications?: number;
  push_notifications?: number;
  default_agent_id?: string;
  default_model?: string;
}

export type { UserPreferences };

interface UserContextValue {
  user: User | null;
  preferences: UserPreferences;
  isLoading: boolean;
  isAuthenticated: boolean;
  isAdmin: boolean;
  refreshUser: () => Promise<void>;
  logout: () => void;
  updatePreferences: (data: Partial<UserPreferences>) => Promise<void>;
}

// ── Context ───────────────────────────────────────────────────────────────

const UserContext = createContext<UserContextValue>({
  user: null,
  preferences: {},
  isLoading: true,
  isAuthenticated: false,
  isAdmin: false,
  refreshUser: async () => {},
  logout: () => {},
  updatePreferences: async () => {},
});

// ── Hook ──────────────────────────────────────────────────────────────────

export function useUser(): UserContextValue {
  return useContext(UserContext);
}

// ── Provider ──────────────────────────────────────────────────────────────

interface UserProviderProps {
  children: ReactNode;
}

export default function UserProvider({ children }: UserProviderProps) {
  const [user, setUser] = useState<User | null>(null);
  const [preferences, setPreferences] = useState<UserPreferences>({});
  const [isLoading, setIsLoading] = useState(true);

  const isAuthenticated = !!user;
  const isAdmin = user?.role === 'admin' || user?.role === 'superadmin';

  const refreshUser = useCallback(async () => {
    const token = getApiToken();
    if (!token) {
      setUser(null);
      setPreferences({});
      setIsLoading(false);
      return;
    }

    // Detect user change and clear old data to prevent cross-user data leakage
    const oldUsername = localStorage.getItem('coapis-current-username');
    const newUsername = getCurrentUsername();

    if (oldUsername && oldUsername !== newUsername) {
      console.log(`User changed: ${oldUsername} -> ${newUsername}, clearing old data`);
      // Clear old user's agent store data
      const oldKey = `coapis-agent-storage-${oldUsername}`;
      const oldLastUsedKey = `coapis-last-used-agent-${oldUsername}`;
      localStorage.removeItem(oldKey);
      localStorage.removeItem(oldLastUsedKey);
      // Clear sessionStorage (may contain old user's selectedAgent)
      sessionStorage.clear();
    }

    // Save current username for next login detection
    localStorage.setItem('coapis-current-username', newUsername || '');

    // Use direct fetch to bypass the global 401 handler in request.ts
    // which would clearAuthToken() and redirect to /login on any 401
    const authHeaders = { Authorization: `Bearer ${token}` };
    try {
      const [meRes, prefsRes] = await Promise.all([
        fetch(getApiUrl('/user/me'), { headers: authHeaders }),
        fetch(getApiUrl('/user/preferences'), { headers: authHeaders }),
      ]);

      if (meRes.ok) {
        setUser((await meRes.json()) as User);
      } else {
        // Token invalid or expired — clear silently, no redirect
        clearAuthToken();
        setUser(null);
      }

      if (prefsRes.ok) {
        const data = await prefsRes.json();
        setPreferences(data || {});
      }
    } catch {
      setUser(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const logout = useCallback(() => {
    // Read keys BEFORE clearing token (keys depend on JWT username)
    const agentKey = getAgentStorageKey();
    const lastUsedKey = getLastUsedAgentKey();
    clearAuthToken();
    setUser(null);
    setPreferences({});
    // Clear all per-user cached state to prevent data leakage
    // between sessions (e.g. agentStore in sessionStorage/localStorage)
    try {
      sessionStorage.clear();
      localStorage.removeItem(agentKey);
      localStorage.removeItem(lastUsedKey);
    } catch { /* ignore */ }
    window.location.href = '/login';
  }, []);

  const updatePreferences = useCallback(async (data: Partial<UserPreferences>) => {
    setPreferences((prev) => ({ ...prev, ...data }));
    try {
      await updateUserPreferences(data);
    } catch {
      // Silently fail - localStorage is primary, backend is backup
      console.warn('Failed to sync preferences to backend:', data);
    }
  }, []);

  // Initial load
  useEffect(() => {
    refreshUser();
  }, [refreshUser]);

  // Poll for token changes to detect login/logout from other components
  useEffect(() => {
    let currentToken = getApiToken();
    const interval = setInterval(() => {
      const newToken = getApiToken();
      if (currentToken !== newToken) {
        currentToken = newToken;
        refreshUser();
      }
    }, 1000);
    return () => clearInterval(interval);
  }, [refreshUser]);

  return (
    <UserContext.Provider
      value={{
        user,
        preferences,
        isLoading,
        isAuthenticated,
        isAdmin,
        refreshUser,
        logout,
        updatePreferences,
      }}
    >
      {children}
    </UserContext.Provider>
  );
}
