/**
 * useChatDisplayFromUser — 从 UserContext 读取聊天偏好，并同步回后端
 *
 * 桥接 ChatDisplayConfig（本地）与 UserPreferences（后端）。
 * 优先从 UserContext 读取，若无则回退到 localStorage。
 * 修改时同时更新 localStorage 和后端。
 */
import { useCallback, useState, useEffect, useRef } from 'react';
import { useUser } from '@/contexts/UserContext';
import {
  ChatDisplayConfig,
  DEFAULT_CHAT_DISPLAY_CONFIG,
  loadChatDisplayConfig,
  saveChatDisplayConfig,
} from '@/pages/Chat/types';

/**
 * 将后端偏好响应转换为 ChatDisplayConfig
 *
 * 后端 GET /user/preferences 返回的是**嵌套**结构：
 *   { chat_display: { hideToolCall, autoScroll, fontSize, codeTheme, ... } }
 * 旧实现读的是扁平的 prefs.chat_hide_details，后端从不返回该字段，
 * 于是恒为 false 并在挂载时覆盖 localStorage —— 持久化链断裂。
 */
function prefsToChatDisplay(prefs: UserPreferences): ChatDisplayConfig {
  const cd = prefs.chat_display;
  return {
    hideDetails: cd?.hideToolCall ?? DEFAULT_CHAT_DISPLAY_CONFIG.hideDetails,
    autoScroll: cd?.autoScroll ?? DEFAULT_CHAT_DISPLAY_CONFIG.autoScroll,
    fontSize: cd?.fontSize ?? DEFAULT_CHAT_DISPLAY_CONFIG.fontSize,
    codeTheme: cd?.codeTheme ?? DEFAULT_CHAT_DISPLAY_CONFIG.codeTheme,
  };
}

/**
 * 将 ChatDisplayConfig 转换为后端可接受的扁平偏好（用于 PUT /user/preferences）
 *
 * 后端 FlatPreferencesUpdate 只认 chat_hide_tool_call / chat_auto_scroll /
 * chat_font_size / chat_code_theme；旧实现发的 chat_hide_details 是未知键，
 * 被 Pydantic 静默丢弃。
 */
import type { UserPreferences } from '@/contexts/UserContext';
function chatDisplayToPrefs(cfg: ChatDisplayConfig): Partial<UserPreferences> {
  return {
    chat_hide_tool_call: cfg.hideDetails ? 1 : 0,
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
  // 后端只在「本机从未存过配置」时播种一次。
  // 旧实现在每次 user/preferences 变化时都用后端快照回灌并写回 localStorage，
  // 于是本地刚改的值会被旧快照冲掉（PUT 与读回存在竞态），表现为
  // localStorage 与后端不一致、开关刷新后跳变。
  const seededFromBackend = useRef(
    localStorage.getItem('coapis_chat_display_config') !== null,
  );

  useEffect(() => {
    if (!user || !preferences || seededFromBackend.current) return;
    seededFromBackend.current = true;
    const backendConfig = prefsToChatDisplay(preferences);
    setDisplayConfig((prev) => {
      const merged = { ...prev, ...backendConfig };
      saveChatDisplayConfig(merged);
      return merged;
    });
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
