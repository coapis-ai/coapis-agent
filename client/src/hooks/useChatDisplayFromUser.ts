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
    hideDetails: !!(prefs.chat_hide_details ?? DEFAULT_CHAT_DISPLAY_CONFIG.hideDetails),
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
    chat_hide_details: cfg.hideDetails ? 1 : 0,
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
      // 合并：后端值优先，但保留 localStorage 中的其他设置
      setDisplayConfig((prev) => {
        const merged = { ...prev, ...backendConfig };
        saveChatDisplayConfig(merged);
        return merged;
      });
    }
  }, [user, preferences]);

  const updateDisplayConfig = useCallback(
    (key: keyof ChatDisplayConfig, value: boolean | string) => {
      setDisplayConfig((prev) => {
        const newConfig = { ...prev, [key]: value };
        saveChatDisplayConfig(newConfig);
        // 同步到后端
        if (updatePreferences) {
          updatePreferences(chatDisplayToPrefs(newConfig));
        }
        return newConfig;
      });
    },
    [updatePreferences],
  );

  const resetToDefaults = useCallback(() => {
    const defaultConfig = { ...DEFAULT_CHAT_DISPLAY_CONFIG };
    setDisplayConfig(defaultConfig);
    saveChatDisplayConfig(defaultConfig);
    // 同步到后端
    if (updatePreferences) {
      updatePreferences(chatDisplayToPrefs(defaultConfig));
    }
  }, [updatePreferences]);

  return {
    displayConfig,
    setDisplayConfig,
    updateDisplayConfig,
    resetToDefaults,
  };
}
