declare const VITE_API_BASE_URL: string;
declare const TOKEN: string;

// 不再直接使用常量，改用 AuthStorage 统一管理
// const AUTH_TOKEN_KEY = "coapis_auth_token";

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
 * Get the API token - 使用 AuthStorage 统一管理
 * 优先级：sessionStorage（当前标签页） > localStorage（记住的账号）
 * @returns API token string or empty string
 */
export function getApiToken(): string {
  // 使用 AuthStorage 统一管理
  const { AuthStorage } = require('../utils/authStorage');
  const stored = AuthStorage.getToken();
  if (stored) return stored;
  
  // 向后兼容：如果 AuthStorage 没有，尝试从旧的 localStorage 读取
  const legacyToken = localStorage.getItem("coapis_auth_token");
  if (legacyToken) return legacyToken;
  
  // 最后尝试构建时的 TOKEN 常量
  return typeof TOKEN !== "undefined" ? TOKEN : "";
}

/**
 * Store the auth token - 使用 AuthStorage 统一管理
 * 默认保存到 sessionStorage（不记住），如果需要"记住我"，使用 AuthStorage.login()
 * @param token - JWT token
 * @param remember - 是否"记住我"（可选，默认 false）
 */
export function setAuthToken(token: string, remember: boolean = false): void {
  const { AuthStorage } = require('../utils/authStorage');
  AuthStorage.saveToken(token, remember);
}

/**
 * Remove the auth token - 使用 AuthStorage 统一管理
 * @param clearAll - 是否清除所有（包括记住的账号）
 */
export function clearAuthToken(clearAll: boolean = false): void {
  const { AuthStorage } = require('../utils/authStorage');
  AuthStorage.clearToken(clearAll);
}

/**
 * Get the current username from the JWT auth token.
 * 优先使用 AuthStorage，如果失败则从 token 解析
 * @returns username string or empty string
 */
export function getCurrentUsername(): string {
  // 优先从 AuthStorage 读取
  const { AuthStorage } = require('../utils/authStorage');
  const username = AuthStorage.getUsername();
  if (username) return username;
  
  // 如果 AuthStorage 没有，尝试从 token 解析（向后兼容）
  try {
    const token = localStorage.getItem("coapis_auth_token");
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
