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
 */
export function ChatWrapper({
  mode = 'full',
  sessionId,
  sceneId,
  sceneName,
  welcomeMessage,
  showToolbar = true,
  compactLayout = false,
  onSessionCreated,
  onError,
  children,
}: ChatWrapperProps) {
  // 注入场景参数到window对象（供Chat页面使用）
  useEffect(() => {
    if (mode === 'embedded') {
      // 嵌入式模式：注入场景参数
      (window as any).__CHAT_MODE__ = 'embedded';
      (window as any).__CHAT_SESSION_ID__ = sessionId;
      (window as any).__CHAT_SCENE_ID__ = sceneId;
      (window as any).__CHAT_SCENE_NAME__ = sceneName;
      (window as any).__CHAT_WELCOME_MESSAGE__ = welcomeMessage;
      (window as any).__CHAT_SHOW_TOOLBAR__ = showToolbar;
      (window as any).__CHAT_COMPACT__ = compactLayout;
      
      // 回调
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
      delete (window as any).__CHAT_ON_SESSION_CREATED__;
      delete (window as any).__CHAT_ON_ERROR__;
    }
    
    return () => {
      // 清理
      delete (window as any).__CHAT_MODE__;
      delete (window as any).__CHAT_SESSION_ID__;
      delete (window as any).__CHAT_SCENE_ID__;
      delete (window as any).__CHAT_SCENE_NAME__;
      delete (window as any).__CHAT_WELCOME_MESSAGE__;
      delete (window as any).__CHAT_SHOW_TOOLBAR__;
      delete (window as any).__CHAT_COMPACT__;
      delete (window as any).__CHAT_ON_SESSION_CREATED__;
      delete (window as any).__CHAT_ON_ERROR__;
    };
  }, [mode, sessionId, sceneId, sceneName, welcomeMessage, showToolbar, compactLayout, onSessionCreated, onError]);
  
  return <>{children}</>;
}
