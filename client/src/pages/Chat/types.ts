/**
 * Chat display configuration for CoApis.
 *
 * Controls which elements are shown in the chat message area.
 * Stored in localStorage for persistence across sessions.
 */
export interface ChatDisplayConfig {
  /** 隐藏细节：开启后显示摘要，点击可展开查看完整内容 */
  hideDetails: boolean;
  /** 自动滚动到最新消息 */
  autoScroll: boolean;
  /** 字体大小 */
  fontSize: 'small' | 'normal' | 'large';
  /** 代码主题 */
  codeTheme: 'light' | 'dark';
}

export const DEFAULT_CHAT_DISPLAY_CONFIG: ChatDisplayConfig = {
  hideDetails: false,
  autoScroll: true,
  fontSize: 'normal',
  codeTheme: 'dark',
};

const STORAGE_KEY = 'coapis_chat_display_config';

/** Load config from localStorage, falling back to defaults */
export function loadChatDisplayConfig(): ChatDisplayConfig {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      const parsed = JSON.parse(stored);
      // Merge with defaults to handle missing keys from older versions
      return { ...DEFAULT_CHAT_DISPLAY_CONFIG, ...parsed };
    }
  } catch {
    // localStorage unavailable or corrupted
  }
  return { ...DEFAULT_CHAT_DISPLAY_CONFIG };
}

/** Save config to localStorage */
export function saveChatDisplayConfig(config: ChatDisplayConfig): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
  } catch {
    // localStorage unavailable — silently ignore
  }
}
