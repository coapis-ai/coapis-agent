// ChatWrapper - 聊天页面包装器
// 支持完整模式和嵌入式模式

import { useEffect } from 'react';
import { setChatGlobals, clearChatGlobals } from '../../lib/chatGlobals';

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

  // 回调（保留接口兼容；onSessionCreated/onError 已无全局通道，仅经 props 传递）
  onSessionCreated?: (id: string) => void;
  onError?: (error: Error) => void;

  // 子组件（Chat页面）
  children: React.ReactNode;
}

/**
 * ChatWrapper组件
 *
 * 包装Chat页面，提供：
 * - 场景参数注入（M3/T3.2：统一走 lib/chatGlobals 单一命名空间，
 *   14 个散落全局变量收敛为 10 字段的 window.__COAPIS_CHAT__，
 *   旧 __CHAT_*__ 键在过渡期内继续写穿）
 * - 布局模式控制
 * - 状态管理桥接
 *
 * 关键：必须在渲染子组件前同步设置全局参数
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
  // CRITICAL: 在渲染前同步设置全局参数
  // 这样Chat组件在首次渲染时就能读取到正确的参数
  if (mode === 'embedded') {
    setChatGlobals({
      mode: 'embedded',
      sessionId,
      sceneId,
      sceneName,
      welcomeMessage,
      compact: compactLayout,
      onClose,
      onTogglePin,
      isPinned,
      onDragStart: onDragStart
        ? (e: unknown) => onDragStart(e as React.MouseEvent)
        : undefined,
    });
  } else {
    // 完整模式：清理全局参数
    clearChatGlobals();
  }

  // 组件卸载时清理全局参数
  useEffect(() => {
    return () => {
      clearChatGlobals();
    };
  }, []);

  // 以下两个回调不再有全局通道（原 __CHAT_ON_EXPAND__ / __CHAT_ON_SESSION_CREATED__ /
  // __CHAT_ON_ERROR__ 无任何消费者，已在 T3.2 中裁撤）；保留 props 以便父级直接使用。
  void onExpand;
  void onSessionCreated;
  void onError;
  void showToolbar;

  return <>{children}</>;
}
