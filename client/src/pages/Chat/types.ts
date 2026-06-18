/**
 * Chat display configuration for CoApis.
 *
 * Controls which elements are shown in the chat message area.
 * Stored in localStorage for persistence across sessions.
 */
export interface ChatDisplayConfig {
  /** Hide tool call cards (default: true for cleaner UI) */
  hideToolCall: boolean;
  /** Hide thinking/deep-think cards (default: true for cleaner UI) */
  hideThinking: boolean;
  /** Hide footer with token count, timestamp, model name (default: true) */
  hideFooter: boolean;
  /** Hide system messages (default: true) */
  hideSystemMessages: boolean;
  /** Display mode: 'simple' = only user+assistant text, 'detailed' = show all */
  displayMode: 'simple' | 'detailed';
  /** Show timestamps on messages (default: false) */
  showTimestamps: boolean;
  /** Show token counts on messages (default: false) */
  showTokenCounts: boolean;
  /** Show model name in message footer (default: false) */
  showModelName: boolean;
  /** Auto-scroll to bottom on new messages (default: true) */
  autoScroll: boolean;
  /** Message font size: 'small' | 'normal' | 'large' */
  fontSize: 'small' | 'normal' | 'large';
  /** Code block theme: 'light' | 'dark' */
  codeTheme: 'light' | 'dark';
}

export const DEFAULT_CHAT_DISPLAY_CONFIG: ChatDisplayConfig = {
  hideToolCall: false,
  hideThinking: true,
  hideFooter: false,
  hideSystemMessages: false,
  displayMode: 'detailed',
  showTimestamps: false,
  showTokenCounts: false,
  showModelName: false,
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
