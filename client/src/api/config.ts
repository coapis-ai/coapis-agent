declare const VITE_API_BASE_URL: string;
declare const TOKEN: string;

const AUTH_TOKEN_KEY = "coapis_auth_token";

/**
 * Get the full API URL with /api prefix
 * @param path - API path (e.g., "/models", "/skills")
 * @returns Full API URL (e.g., "http://localhost:8088/api/models" or "/api/models")
 */
export function getApiUrl(path: string): string {
  const base = VITE_API_BASE_URL || "";
  const apiPrefix = "/api";
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${base}${apiPrefix}${normalizedPath}`;
}

/**
 * Get the API token - checks localStorage first (auth login),
 * then falls back to the build-time TOKEN constant.
 * @returns API token string or empty string
 */
export function getApiToken(): string {
  const stored = localStorage.getItem(AUTH_TOKEN_KEY);
  if (stored) return stored;
  return typeof TOKEN !== "undefined" ? TOKEN : "";
}

/**
 * Store the auth token in localStorage after login.
 */
export function setAuthToken(token: string): void {
  localStorage.setItem(AUTH_TOKEN_KEY, token);
}

/**
 * Remove the auth token from localStorage (logout / 401).
 */
export function clearAuthToken(): void {
  localStorage.removeItem(AUTH_TOKEN_KEY);
}

/**
 * Get the current username from the JWT auth token.
 * Returns empty string if not available.
 */
export function getCurrentUsername(): string {
  try {
    const token = localStorage.getItem(AUTH_TOKEN_KEY);
    if (token) {
      const payload = JSON.parse(atob(token.split(".")[1] || ""));
      return payload?.sub || payload?.username || "";
    }
  } catch { /* ignore */ }
  return "";
}

/**
 * User-scoped localStorage key for agent store.
 * Prevents agent leakage between different users sharing the same browser.
 */
export function getAgentStorageKey(): string {
  const username = getCurrentUsername();
  return username ? `coapis-agent-storage-${username}` : "coapis-agent-storage";
}

/**
 * User-scoped localStorage key for last-used agent.
 */
export function getLastUsedAgentKey(): string {
  const username = getCurrentUsername();
  return username ? `coapis-last-used-agent-${username}` : "coapis-last-used-agent";
}
