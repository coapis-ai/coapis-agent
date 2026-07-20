// ChatWrapper - 聊天页面包装器
// 支持完整模式和嵌入式模式

import React, { useEffect } from 'react';

export interface ChatWrapperProps {
  // 显示模式
  mode?: 'full' | 'embedded';
  
  // 场景相关（嵌入式模式）
  sessionId?: string;
  sceneId?: string;
  sceneName?: string;
  welcomeMessage?: string;
  
  // 显示控制
  showToolbar?: boolean;
  compactLayout?: boolean;
  
  // 浮窗控制（嵌入式模式）
  onClose?: () => void;
  onExpand?: () => void;
  onTogglePin?: () => void;
  isPinned?: boolean;
  onDragStart?: (e: React.MouseEvent) => void;
  
  // 回调
  onSessionCreated?: (id: string) => void;
  onError?: (error: Error) => void;
  
  // 子组件（Chat页面）
  children: React.ReactNode;
}

/**
 * ChatWrapper组件
 * 
 * 包装Chat页面，提供：
 * - 场景参数注入
 * - 布局模式控制
 * - 状态管理桥接
 * 
 * 关键：必须在渲染子组件前同步设置window参数
 */
export function ChatWrapper({
  mode = 'full',
  sessionId,
  sceneId,
  sceneName,
  welcomeMessage,
  showToolbar = true,
  compactLayout = false,
  onClose,
  onExpand,
  onTogglePin,
  isPinned,
  onDragStart,
  onSessionCreated,
  onError,
  children,
}: ChatWrapperProps) {
  // CRITICAL: 在渲染前同步设置window参数
  // 这样Chat组件在首次渲染时就能读取到正确的参数
  if (mode === 'embedded') {
    (window as any).__CHAT_MODE__ = 'embedded';
    (window as any).__CHAT_SESSION_ID__ = sessionId;
    (window as any).__CHAT_SCENE_ID__ = sceneId;
    (window as any).__CHAT_SCENE_NAME__ = sceneName;
    (window as any).__CHAT_WELCOME_MESSAGE__ = welcomeMessage;
    (window as any).__CHAT_SHOW_TOOLBAR__ = showToolbar;
    (window as any).__CHAT_COMPACT__ = compactLayout;
    (window as any).__CHAT_ON_CLOSE__ = onClose;
    (window as any).__CHAT_ON_EXPAND__ = onExpand;
    (window as any).__CHAT_ON_TOGGLE_PIN__ = onTogglePin;
    (window as any).__CHAT_IS_PINNED__ = isPinned;
    (window as any).__CHAT_ON_DRAG_START__ = onDragStart;
    (window as any).__CHAT_ON_SESSION_CREATED__ = onSessionCreated;
    (window as any).__CHAT_ON_ERROR__ = onError;
  } else {
    // 完整模式：清理场景参数
    delete (window as any).__CHAT_MODE__;
    delete (window as any).__CHAT_SESSION_ID__;
    delete (window as any).__CHAT_SCENE_ID__;
    delete (window as any).__CHAT_SCENE_NAME__;
    delete (window as any).__CHAT_WELCOME_MESSAGE__;
    delete (window as any).__CHAT_SHOW_TOOLBAR__;
    delete (window as any).__CHAT_COMPACT__;
    delete (window as any).__CHAT_ON_CLOSE__;
    delete (window as any).__CHAT_ON_EXPAND__;
    delete (window as any).__CHAT_ON_TOGGLE_PIN__;
    delete (window as any).__CHAT_IS_PINNED__;
    delete (window as any).__CHAT_ON_DRAG_START__;
    delete (window as any).__CHAT_ON_SESSION_CREATED__;
    delete (window as any).__CHAT_ON_ERROR__;
  }
  
  // 组件卸载时清理window参数
  useEffect(() => {
    return () => {
      delete (window as any).__CHAT_MODE__;
      delete (window as any).__CHAT_SESSION_ID__;
      delete (window as any).__CHAT_SCENE_ID__;
      delete (window as any).__CHAT_SCENE_NAME__;
      delete (window as any).__CHAT_WELCOME_MESSAGE__;
      delete (window as any).__CHAT_SHOW_TOOLBAR__;
      delete (window as any).__CHAT_COMPACT__;
      delete (window as any).__CHAT_ON_CLOSE__;
      delete (window as any).__CHAT_ON_EXPAND__;
      delete (window as any).__CHAT_ON_TOGGLE_PIN__;
      delete (window as any).__CHAT_IS_PINNED__;
      delete (window as any).__CHAT_ON_DRAG_START__;
      delete (window as any).__CHAT_ON_SESSION_CREATED__;
      delete (window as any).__CHAT_ON_ERROR__;
    };
  }, []);
  
  return <>{children}</>;
}
