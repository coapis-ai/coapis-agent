declare const VITE_API_BASE_URL: string;
declare const TOKEN: string;

// ==================== AuthStorage 内联实现 ====================
// 由于浏览器环境不支持 require，直接在此文件实现核心功能

const STORAGE_KEYS = {
  CURRENT_TOKEN: 'coapis_auth_token',
  CURRENT_USERNAME: 'coapis_current_username',
  SAVED_ACCOUNTS: 'coapis_saved_accounts',
  CURRENT_USERNAME_GLOBAL: 'coapis-current-username',
};

/**
 * 保存认证 token
 */
function saveToken(token: string, remember: boolean = false): void {
  sessionStorage.setItem(STORAGE_KEYS.CURRENT_TOKEN, token);
  if (remember) {
    localStorage.setItem(STORAGE_KEYS.CURRENT_TOKEN, token);
  }
}

/**
 * 获取认证 token
 * 优先级：sessionStorage > localStorage
 */
function getToken(): string | null {
  const sessionToken = sessionStorage.getItem(STORAGE_KEYS.CURRENT_TOKEN);
  if (sessionToken) return sessionToken;
  return localStorage.getItem(STORAGE_KEYS.CURRENT_TOKEN);
}

/**
 * 保存当前用户名
 */
function saveUsername(username: string, remember: boolean = false): void {
  sessionStorage.setItem(STORAGE_KEYS.CURRENT_USERNAME, username);
  localStorage.setItem(STORAGE_KEYS.CURRENT_USERNAME_GLOBAL, username);
  if (remember) {
    localStorage.setItem(STORAGE_KEYS.CURRENT_USERNAME, username);
  }
}

/**
 * 获取当前用户名
 */
function getUsername(): string | null {
  const sessionUsername = sessionStorage.getItem(STORAGE_KEYS.CURRENT_USERNAME);
  if (sessionUsername) return sessionUsername;
  return localStorage.getItem(STORAGE_KEYS.CURRENT_USERNAME);
}

// ==================== API 配置 ====================

/**
 * Get the full API URL with /api prefix
 */
export function getApiUrl(path: string): string {
  const base = VITE_API_BASE_URL || "";
  const apiPrefix = "/api";
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${base}${apiPrefix}${normalizedPath}`;
}

/**
 * Get the API token - 使用混合存储方案
 * 优先级：sessionStorage > localStorage
 * 
 * 注意：不再使用构建时TOKEN作为fallback
 * 原因：构建时TOKEN可能导致前端误判为"已登录"，产生不必要的401错误
 */
export function getApiToken(): string {
  const stored = getToken();
  if (stored) return stored;
  return "";
}

/**
 * Store the auth token - 使用混合存储方案
 */
export function setAuthToken(token: string, remember: boolean = false): void {
  saveToken(token, remember);
}

/**
 * Remove the auth token
 */
export function clearAuthToken(clearAll: boolean = false): void {
  sessionStorage.removeItem(STORAGE_KEYS.CURRENT_TOKEN);
  if (clearAll) {
    localStorage.removeItem(STORAGE_KEYS.CURRENT_TOKEN);
    localStorage.removeItem(STORAGE_KEYS.CURRENT_USERNAME);
    localStorage.removeItem(STORAGE_KEYS.SAVED_ACCOUNTS);
  }
}

/**
 * Get the current username
 */
export function getCurrentUsername(): string {
  const username = getUsername();
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
 * Save current username（导出供其他模块使用）
 */
export function setCurrentUsername(username: string, remember: boolean = false): void {
  saveUsername(username, remember);
}

/**
 * User-scoped localStorage key for agent store.
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
