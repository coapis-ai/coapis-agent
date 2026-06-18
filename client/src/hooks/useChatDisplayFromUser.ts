/**
 * useChatDisplayFromUser — 从 UserContext 读取聊天偏好，并同步回后端
 *
 * 桥接 ChatDisplayConfig（本地）与 UserPreferences（后端）。
 * 优先从 UserContext 读取，若无则回退到 localStorage。
 * 修改时同时更新 localStorage 和后端。
 */
import { useCallback, useState, useEffect } from 'react';
import { useUser } from '@/contexts/UserContext';
import {
  ChatDisplayConfig,
  DEFAULT_CHAT_DISPLAY_CONFIG,
  loadChatDisplayConfig,
  saveChatDisplayConfig,
} from '@/pages/Chat/types';

/**
 * 将 UserPreferences 转换为 ChatDisplayConfig
 */
function prefsToChatDisplay(prefs: Partial<UserPreferences>): ChatDisplayConfig {
  return {
    hideToolCall: !!(prefs.chat_hide_tool_call ?? DEFAULT_CHAT_DISPLAY_CONFIG.hideToolCall),
    hideThinking: !!(prefs.chat_hide_thinking ?? DEFAULT_CHAT_DISPLAY_CONFIG.hideThinking),
    hideFooter: !!(prefs.chat_hide_footer ?? DEFAULT_CHAT_DISPLAY_CONFIG.hideFooter),
    hideSystemMessages: !!(prefs.chat_hide_system_messages ?? DEFAULT_CHAT_DISPLAY_CONFIG.hideSystemMessages),
    displayMode: (prefs.chat_display_mode as 'simple' | 'detailed') || DEFAULT_CHAT_DISPLAY_CONFIG.displayMode,
    showTimestamps: !!(prefs.chat_show_timestamps ?? DEFAULT_CHAT_DISPLAY_CONFIG.showTimestamps),
    showTokenCounts: !!(prefs.chat_show_token_counts ?? DEFAULT_CHAT_DISPLAY_CONFIG.showTokenCounts),
    showModelName: !!(prefs.chat_show_model_name ?? DEFAULT_CHAT_DISPLAY_CONFIG.showModelName),
    autoScroll: !!(prefs.chat_auto_scroll ?? DEFAULT_CHAT_DISPLAY_CONFIG.autoScroll),
    fontSize: (prefs.chat_font_size as 'small' | 'normal' | 'large') || DEFAULT_CHAT_DISPLAY_CONFIG.fontSize,
    codeTheme: (prefs.chat_code_theme as 'light' | 'dark') || DEFAULT_CHAT_DISPLAY_CONFIG.codeTheme,
  };
}

/**
 * 将 ChatDisplayConfig 转换为用户偏好（用于持久化到后端）
 */
import type { UserPreferences } from '@/contexts/UserContext';
function chatDisplayToPrefs(cfg: ChatDisplayConfig): Partial<UserPreferences> {
  return {
    chat_hide_tool_call: cfg.hideToolCall ? 1 : 0,
    chat_hide_thinking: cfg.hideThinking ? 1 : 0,
    chat_hide_footer: cfg.hideFooter ? 1 : 0,
    chat_hide_system_messages: cfg.hideSystemMessages ? 1 : 0,
    chat_display_mode: cfg.displayMode,
    chat_show_timestamps: cfg.showTimestamps ? 1 : 0,
    chat_show_token_counts: cfg.showTokenCounts ? 1 : 0,
    chat_show_model_name: cfg.showModelName ? 1 : 0,
    chat_auto_scroll: cfg.autoScroll ? 1 : 0,
    chat_font_size: cfg.fontSize,
    chat_code_theme: cfg.codeTheme,
  };
}

export function useChatDisplayFromUser() {
  const { user, preferences, updatePreferences } = useUser();
  const [displayConfig, setDisplayConfig] = useState<ChatDisplayConfig>(() => {
    // 初始值从 localStorage 加载（UserContext 可能还没加载完）
    return loadChatDisplayConfig();
  });

  // 当 UserContext 加载完成后，从后端偏好同步到本地
  useEffect(() => {
    if (user && preferences) {
      const backendConfig = prefsToChatDisplay(preferences);
      setDisplayConfig(backendConfig);
      saveChatDisplayConfig(backendConfig);
    }
  }, [user, preferences]);

  const updateDisplayConfig = useCallback(
    (key: keyof ChatDisplayConfig, value: boolean | string) => {
      const newConfig: ChatDisplayConfig = { ...displayConfig, [key]: value };
      setDisplayConfig(newConfig);
      saveChatDisplayConfig(newConfig);
      // 同步到后端
      if (user) {
        updatePreferences(chatDisplayToPrefs(newConfig));
      }
    },
    [displayConfig, user, updatePreferences],
  );

  const resetToDefaults = useCallback(() => {
    const cfg = { ...DEFAULT_CHAT_DISPLAY_CONFIG };
    setDisplayConfig(cfg);
    saveChatDisplayConfig(cfg);
    if (user) {
      updatePreferences(chatDisplayToPrefs(cfg));
    }
  }, [user, updatePreferences]);

  return {
    displayConfig,
    setDisplayConfig,
    updateDisplayConfig,
    resetToDefaults,
  };
}
