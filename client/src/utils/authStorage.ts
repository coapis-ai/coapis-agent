/**
 * 认证存储管理 - 混合方案
 * 
 * 架构设计：
 * - localStorage：保存"记住我"的账号列表（持久化）
 * - sessionStorage：保存当前标签页的登录状态（临时）
 * 
 * 优点：
 * - 支持多标签页同时登录不同账号
 * - 支持"记住我"功能
 * - 提供账号快速切换
 * - 每个标签页独立隔离
 */

// 存储键名
const STORAGE_KEYS = {
  // sessionStorage - 当前标签页的登录状态
  CURRENT_TOKEN: 'coapis_auth_token',
  CURRENT_USERNAME: 'coapis_current_username',
  
  // localStorage - 记住的账号列表
  SAVED_ACCOUNTS: 'coapis_saved_accounts',
  
  // localStorage - 其他状态
  CURRENT_USERNAME_GLOBAL: 'coapis-current-username',
};

// 账号信息
export interface SavedAccount {
  username: string;
  display_name?: string;
  token: string;
  last_login: string;
  avatar?: string;
}

/**
 * 认证存储管理类
 */
export class AuthStorage {
  // ==================== Token 管理 ====================
  
  /**
   * 保存认证 token
   * @param token - JWT token
   * @param remember - 是否"记住我"
   */
  static saveToken(token: string, remember: boolean = false): void {
    // 始终保存到 sessionStorage（当前标签页）
    sessionStorage.setItem(STORAGE_KEYS.CURRENT_TOKEN, token);
    
    // 如果勾选"记住我"，同时保存到 localStorage
    if (remember) {
      localStorage.setItem(STORAGE_KEYS.CURRENT_TOKEN, token);
    }
  }
  
  /**
   * 获取认证 token
   * 优先级：sessionStorage > localStorage
   */
  static getToken(): string | null {
    // 优先从 sessionStorage 读取（当前标签页）
    const sessionToken = sessionStorage.getItem(STORAGE_KEYS.CURRENT_TOKEN);
    if (sessionToken) return sessionToken;
    
    // 如果 sessionStorage 没有，从 localStorage 读取（记住我的账号）
    return localStorage.getItem(STORAGE_KEYS.CURRENT_TOKEN);
  }
  
  /**
   * 清除认证 token
   * @param clearAll - 是否清除所有（包括记住的账号）
   */
  static clearToken(clearAll: boolean = false): void {
    sessionStorage.removeItem(STORAGE_KEYS.CURRENT_TOKEN);
    
    if (clearAll) {
      localStorage.removeItem(STORAGE_KEYS.CURRENT_TOKEN);
    }
  }
  
  // ==================== 用户名管理 ====================
  
  /**
   * 保存当前用户名
   */
  static saveUsername(username: string, remember: boolean = false): void {
    sessionStorage.setItem(STORAGE_KEYS.CURRENT_USERNAME, username);
    localStorage.setItem(STORAGE_KEYS.CURRENT_USERNAME_GLOBAL, username);
    
    if (remember) {
      localStorage.setItem(STORAGE_KEYS.CURRENT_USERNAME, username);
    }
  }
  
  /**
   * 获取当前用户名
   */
  static getUsername(): string | null {
    const sessionUsername = sessionStorage.getItem(STORAGE_KEYS.CURRENT_USERNAME);
    if (sessionUsername) return sessionUsername;
    
    return localStorage.getItem(STORAGE_KEYS.CURRENT_USERNAME);
  }
  
  /**
   * 清除当前用户名
   */
  static clearUsername(): void {
    sessionStorage.removeItem(STORAGE_KEYS.CURRENT_USERNAME);
    localStorage.removeItem(STORAGE_KEYS.CURRENT_USERNAME_GLOBAL);
    // 不清除 localStorage 中的记住的用户名（保留用于快速切换）
  }
  
  // ==================== 账号列表管理 ====================
  
  /**
   * 获取保存的账号列表
   */
  static getSavedAccounts(): SavedAccount[] {
    try {
      const data = localStorage.getItem(STORAGE_KEYS.SAVED_ACCOUNTS);
      return data ? JSON.parse(data) : [];
    } catch {
      return [];
    }
  }
  
  /**
   * 保存账号到列表（用于"记住我"）
   */
  static saveAccount(account: SavedAccount): void {
    const accounts = this.getSavedAccounts();
    
    // 查找是否已存在
    const index = accounts.findIndex(a => a.username === account.username);
    
    if (index >= 0) {
      // 更新现有账号
      accounts[index] = { ...accounts[index], ...account, last_login: new Date().toISOString() };
    } else {
      // 添加新账号
      accounts.push({ ...account, last_login: new Date().toISOString() });
    }
    
    localStorage.setItem(STORAGE_KEYS.SAVED_ACCOUNTS, JSON.stringify(accounts));
  }
  
  /**
   * 从列表中移除账号
   */
  static removeAccount(username: string): void {
    const accounts = this.getSavedAccounts();
    const filtered = accounts.filter(a => a.username !== username);
    localStorage.setItem(STORAGE_KEYS.SAVED_ACCOUNTS, JSON.stringify(filtered));
  }
  
  /**
   * 清除所有保存的账号
   */
  static clearSavedAccounts(): void {
    localStorage.removeItem(STORAGE_KEYS.SAVED_ACCOUNTS);
  }
  
  // ==================== 登录/登出管理 ====================
  
  /**
   * 登录成功后保存状态
   */
  static login(
    token: string,
    username: string,
    options: {
      remember?: boolean;
      display_name?: string;
      avatar?: string;
    } = {}
  ): void {
    const { remember = false, display_name, avatar } = options;
    
    // 保存 token 和用户名
    this.saveToken(token, remember);
    this.saveUsername(username, remember);
    
    // 如果勾选"记住我"，保存到账号列表
    if (remember) {
      this.saveAccount({
        username,
        token,
        display_name: display_name || username,
        avatar,
        last_login: new Date().toISOString(),
      });
    }
    
    // 设置全局变量
    if (typeof window !== 'undefined') {
      (window as any).currentUserId = username;
      (window as any).currentChannel = '';
    }
  }
  
  /**
   * 登出
   * @param clearAll - 是否清除所有（包括记住的账号）
   */
  static logout(clearAll: boolean = false): void {
    this.clearToken(clearAll);
    this.clearUsername();
    
    if (clearAll) {
      this.clearSavedAccounts();
    }
    
    // 清除全局变量
    if (typeof window !== 'undefined') {
      delete (window as any).currentUserId;
      delete (window as any).currentChannel;
    }
    
    // 清除所有 session 相关数据
    if (typeof window !== 'undefined') {
      Object.keys(sessionStorage).forEach(key => {
        if (key.startsWith('chat_') || key.startsWith('session_') || key.startsWith('agent_')) {
          sessionStorage.removeItem(key);
        }
      });
    }
  }
  
  /**
   * 切换到已保存的账号
   */
  static switchAccount(username: string): boolean {
    const accounts = this.getSavedAccounts();
    const account = accounts.find(a => a.username === username);
    
    if (!account) return false;
    
    // 使用记住的 token 登录
    this.login(account.token, account.username, {
      remember: true,
      display_name: account.display_name,
      avatar: account.avatar,
    });
    
    return true;
  }
  
  /**
   * 检查当前是否已登录
   */
  static isLoggedIn(): boolean {
    return !!this.getToken();
  }
  
  /**
   * 获取当前登录信息
   */
  static getCurrentAuth(): { token: string; username: string } | null {
    const token = this.getToken();
    const username = this.getUsername();
    
    if (!token || !username) return null;
    
    return { token, username };
  }
}

// 导出便捷函数
export const authStorage = AuthStorage;
