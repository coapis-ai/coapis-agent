// EmbeddedChatPage - 统一的嵌入式聊天组件
// 支持两种模式：iframe（外部嵌入）和 drawer（内部浮动窗口）

import React, { useEffect, useState, Suspense, useRef, useCallback, useMemo } from 'react';
import { Spin, message, ConfigProvider, theme as antdTheme } from 'antd';
import { useSearchParams } from 'react-router-dom';
import { ChatWrapper } from '../../components/ChatWrapper';
import ChatPage from '../Chat';
import { setAuthToken, getApiToken } from '../../api/config';
import type { SceneConfig, EnterSceneResponse } from '../Workbench/types';
import styles from './EmbeddedChatPage.module.less';

// ═══════════════════════════════════════════════════════════════════
// postMessage 通信协议（iframe 模式）
// ═══════════════════════════════════════════════════════════════════

interface CoapisInboundMessage {
  type: 'COAPIS_INIT' | 'COAPIS_SEND_MESSAGE' | 'COAPIS_CLOSE' | 'COAPIS_GET_STATE';
  payload?: {
    token?: string;
    sceneId?: string;
    sceneName?: string;
    message?: string;
    context?: Record<string, any>;
  };
}

interface CoapisOutboundEvent {
  type: 'COAPIS_READY' | 'COAPIS_MESSAGE_RECEIVED' | 'COAPIS_MESSAGE_SENT' | 
        'COAPIS_ERROR' | 'COAPIS_STATE_CHANGE' | 'COAPIS_CLOSE_REQUEST';
  data?: {
    message?: string;
    error?: string;
    state?: 'loading' | 'ready' | 'error';
    chatId?: string;
    sceneId?: string;
  };
}

function postToParent(event: CoapisOutboundEvent) {
  if (window.parent !== window) {
    window.parent.postMessage(event, '*');
  }
}

// ═══════════════════════════════════════════════════════════════════
// 四角缩放和拖拽（drawer 模式）
// ═══════════════════════════════════════════════════════════════════

type ResizeCorner = 'nw' | 'ne' | 'sw' | 'se';

const isMobileDevice = (): boolean => {
  return /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent) 
    || window.innerWidth < 768;
};

// ═══════════════════════════════════════════════════════════════════
// 组件接口
// ═══════════════════════════════════════════════════════════════════

export interface EmbeddedChatProps {
  // 模式选择
  mode?: 'iframe' | 'drawer';
  
  // Drawer 模式参数
  visible?: boolean;
  onClose?: () => void;
  scene?: SceneConfig | null;
  initialWidth?: number;
  initialHeight?: number;
  minWidth?: number;
  minHeight?: number;
}

/**
 * 统一的嵌入式聊天组件
 * 
 * 使用方式：
 * 
 * 1. iframe 模式（外部系统嵌入）：
 *    URL: /chat/embedded?token=xxx&scene_id=xxx
 *    <EmbeddedChat mode="iframe" />
 * 
 * 2. drawer 模式（内部浮动窗口）：
 *    <EmbeddedChat 
 *      mode="drawer"
 *      visible={true}
 *      onClose={handleClose}
 *      scene={selectedScene}
 *    />
 */
const EmbeddedChat: React.FC<EmbeddedChatProps> = ({
  mode = 'iframe',
  visible = true,
  onClose,
  scene = null,
  initialWidth = 700,
  initialHeight = 500,
  minWidth = 400,
  minHeight = 300,
}) => {
  const [searchParams] = useSearchParams();
  const [loading, setLoading] = useState(false);
  const [chatData, setChatData] = useState<EnterSceneResponse | null>(null);
  
  // iframe 模式状态
  const [error, setError] = useState<string | null>(null);
  const sendMessageRef = useRef<((msg: string) => void) | null>(null);
  
  // Drawer 模式状态
  const isMobile = useMemo(() => isMobileDevice(), []);
  const [position, setPosition] = useState(() => {
    if (isMobile) return { x: 0, y: 0 };
    const initialX = Math.max(50, window.innerWidth - initialWidth - 50);
    return { x: initialX, y: 50 };
  });
  const [size, setSize] = useState(() => {
    if (isMobile) {
      return {
        width: window.innerWidth * 0.95,
        height: window.innerHeight * 0.85,
      };
    }
    return { width: initialWidth, height: initialHeight };
  });
  const [isPinned, setIsPinned] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [isResizing, setIsResizing] = useState(false);
  const [resizeCorner, setResizeCorner] = useState<ResizeCorner | null>(null);
  
  const dragStartRef = useRef({ x: 0, y: 0, windowX: 0, windowY: 0 });
  const resizeStartRef = useRef({ x: 0, y: 0, width: 0, height: 0, posX: 0, posY: 0 });
  const containerRef = useRef<HTMLDivElement>(null);

  // ═══════════════════════════════════════════════════════════════════
  // iframe 模式：认证检查
  // ═══════════════════════════════════════════════════════════════════
  
  const token = searchParams.get('token');
  const urlSceneId = searchParams.get('scene_id');
  const urlSceneName = searchParams.get('scene_name') || 'AI 助手';

  useEffect(() => {
    if (mode !== 'iframe') return;
    
    if (!token) {
      setError('缺少认证令牌');
      postToParent({
        type: 'COAPIS_ERROR',
        data: { error: '缺少认证令牌' },
      });
      return;
    }

    setAuthToken(token);

    const verifyToken = async () => {
      try {
        const response = await fetch('/api/auth/verify', {
          headers: { Authorization: `Bearer ${token}` },
        });

        if (!response.ok) {
          throw new Error('认证令牌无效或已过期');
        }

        postToParent({ type: 'COAPIS_READY' });
      } catch (err) {
        setError('认证验证失败');
        postToParent({
          type: 'COAPIS_ERROR',
          data: { error: '认证验证失败' },
        });
      }
    };

    verifyToken();
  }, [mode, token]);

  // ═══════════════════════════════════════════════════════════════════
  // 场景加载（两种模式共用）
  // ═══════════════════════════════════════════════════════════════════
  
  const enterScene = useCallback(async (sceneId: string, sceneName: string) => {
    try {
      setLoading(true);
      const authToken = mode === 'iframe' ? token : getApiToken();
      
      const response = await fetch(`/api/scenes/${sceneId}/enter`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${authToken}`,
        },
      });

      if (!response.ok) {
        throw new Error('进入场景失败');
      }

      const data: EnterSceneResponse = await response.json();
      setChatData(data);
      
      if (mode === 'drawer') {
        message.success(`已进入场景: ${sceneName}`);
      }
      
      return data;
    } catch (err) {
      console.error('Failed to enter scene:', err);
      if (mode === 'drawer') {
        message.error('进入场景失败');
      }
      return null;
    } finally {
      setLoading(false);
    }
  }, [mode, token]);

  // iframe 模式：加载场景
  useEffect(() => {
    if (mode !== 'iframe' || !urlSceneId) return;
    enterScene(urlSceneId, urlSceneName);
  }, [mode, urlSceneId, urlSceneName, enterScene]);

  // drawer 模式：加载场景
  useEffect(() => {
    if (mode !== 'drawer' || !visible || !scene) return;
    enterScene(scene.id, scene.name);
  }, [mode, visible, scene, enterScene]);

  // drawer 模式：重置状态
  useEffect(() => {
    if (mode === 'drawer' && !visible) {
      setChatData(null);
    }
  }, [mode, visible]);

  // ═══════════════════════════════════════════════════════════════════
  // drawer 模式：拖拽和四角缩放
  // ═══════════════════════════════════════════════════════════════════

  const handleDragStart = useCallback((e: React.MouseEvent) => {
    if (isMobile) return;
    e.preventDefault();
    setIsDragging(true);
    dragStartRef.current = {
      x: e.clientX,
      y: e.clientY,
      windowX: position.x,
      windowY: position.y,
    };
  }, [isMobile, position]);

  useEffect(() => {
    if (!isDragging || isMobile) return;

    const handleMouseMove = (e: MouseEvent) => {
      const deltaX = e.clientX - dragStartRef.current.x;
      const deltaY = e.clientY - dragStartRef.current.y;
      setPosition({
        x: dragStartRef.current.windowX + deltaX,
        y: dragStartRef.current.windowY + deltaY,
      });
    };

    const handleMouseUp = () => {
      setIsDragging(false);
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging, isMobile]);

  const handleResizeStart = useCallback((corner: ResizeCorner) => (e: React.MouseEvent) => {
    if (isMobile) return;
    e.preventDefault();
    e.stopPropagation();
    setIsResizing(true);
    setResizeCorner(corner);
    resizeStartRef.current = {
      x: e.clientX,
      y: e.clientY,
      width: size.width,
      height: size.height,
      posX: position.x,
      posY: position.y,
    };
  }, [isMobile, size, position]);

  useEffect(() => {
    if (!isResizing || isMobile) return;

    const handleMouseMove = (e: MouseEvent) => {
      const deltaX = e.clientX - resizeStartRef.current.x;
      const deltaY = e.clientY - resizeStartRef.current.y;

      let newWidth = resizeStartRef.current.width;
      let newHeight = resizeStartRef.current.height;
      let newX = resizeStartRef.current.posX;
      let newY = resizeStartRef.current.posY;

      switch (resizeCorner) {
        case 'nw':
          newWidth = Math.max(minWidth, resizeStartRef.current.width - deltaX);
          newHeight = Math.max(minHeight, resizeStartRef.current.height - deltaY);
          newX = resizeStartRef.current.posX + (resizeStartRef.current.width - newWidth);
          newY = resizeStartRef.current.posY + (resizeStartRef.current.height - newHeight);
          break;
        case 'ne':
          newWidth = Math.max(minWidth, resizeStartRef.current.width + deltaX);
          newHeight = Math.max(minHeight, resizeStartRef.current.height - deltaY);
          newY = resizeStartRef.current.posY + (resizeStartRef.current.height - newHeight);
          break;
        case 'sw':
          newWidth = Math.max(minWidth, resizeStartRef.current.width - deltaX);
          newHeight = Math.max(minHeight, resizeStartRef.current.height + deltaY);
          newX = resizeStartRef.current.posX + (resizeStartRef.current.width - newWidth);
          break;
        case 'se':
          newWidth = Math.max(minWidth, resizeStartRef.current.width + deltaX);
          newHeight = Math.max(minHeight, resizeStartRef.current.height + deltaY);
          break;
      }

      newX = Math.max(0, newX);
      newY = Math.max(0, newY);

      setSize({ width: newWidth, height: newHeight });
      setPosition({ x: newX, y: newY });
    };

    const handleMouseUp = () => {
      setIsResizing(false);
      setResizeCorner(null);
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isResizing, resizeCorner, minWidth, minHeight, isMobile]);

  // ═══════════════════════════════════════════════════════════════════
  // iframe 模式：postMessage 监听
  // ═══════════════════════════════════════════════════════════════════

  useEffect(() => {
    if (mode !== 'iframe') return;

    const handleMessage = (event: MessageEvent) => {
      if (event.source !== window.parent) return;

      const msg = event.data as CoapisInboundMessage;
      if (!msg || !msg.type) return;

      switch (msg.type) {
        case 'COAPIS_SEND_MESSAGE':
          if (msg.payload?.message && sendMessageRef.current) {
            sendMessageRef.current(msg.payload.message);
            postToParent({
              type: 'COAPIS_MESSAGE_SENT',
              data: { message: msg.payload.message },
            });
          }
          break;

        case 'COAPIS_CLOSE':
          postToParent({ type: 'COAPIS_CLOSE_REQUEST' });
          break;

        case 'COAPIS_GET_STATE':
          postToParent({
            type: 'COAPIS_STATE_CHANGE',
            data: {
              state: loading ? 'loading' : error ? 'error' : 'ready',
              sceneId: chatData?.scene.id,
              chatId: chatData?.chat_id,
            },
          });
          break;
      }
    };

    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [mode, loading, error, chatData]);

  // 暴露消息发送接口
  useEffect(() => {
    (window as any).__COAPIS_SEND_MESSAGE__ = (msg: string) => {
      if (sendMessageRef.current) {
        sendMessageRef.current(msg);
      }
    };

    (window as any).__COAPIS_NOTIFY_MESSAGE_RECEIVED__ = (msg: string) => {
      postToParent({
        type: 'COAPIS_MESSAGE_RECEIVED',
        data: { message: msg },
      });
    };

    return () => {
      delete (window as any).__COAPIS_SEND_MESSAGE__;
      delete (window as any).__COAPIS_NOTIFY_MESSAGE_RECEIVED__;
    };
  }, []);

  // ═══════════════════════════════════════════════════════════════════
  // 渲染
  // ═══════════════════════════════════════════════════════════════════

  // drawer 模式：未显示时不渲染
  if (mode === 'drawer' && !visible) return null;

  // iframe 模式：错误状态
  if (mode === 'iframe' && error) {
    return (
      <div className={styles.embeddedError}>
        <p>⚠️ {error}</p>
        <p>请检查 URL 参数或联系管理员</p>
      </div>
    );
  }

  // drawer 模式：渲染浮窗
  if (mode === 'drawer') {
    return (
      <div
        ref={containerRef}
        className={`${styles.floatingWindow} ${isMobile ? styles.mobileWindow : ''}`}
        style={{
          left: isMobile ? '50%' : position.x,
          top: isMobile ? '7.5vh' : position.y,
          width: size.width,
          height: size.height,
          cursor: isDragging ? 'move' : 'default',
          transform: isMobile ? 'translateX(-50%)' : 'none',
        }}
      >
        {/* 四角缩放手柄（桌面端） */}
        {!isMobile && (
          <>
            <div 
              className={`${styles.resizeHandle} ${styles.nw}`}
              onMouseDown={handleResizeStart('nw')}
            />
            <div 
              className={`${styles.resizeHandle} ${styles.ne}`}
              onMouseDown={handleResizeStart('ne')}
            />
            <div 
              className={`${styles.resizeHandle} ${styles.sw}`}
              onMouseDown={handleResizeStart('sw')}
            />
            <div 
              className={`${styles.resizeHandle} ${styles.se}`}
              onMouseDown={handleResizeStart('se')}
            />
          </>
        )}

        {/* 内容区域 */}
        <div className={styles.windowBodyNoHeader}>
          {loading ? (
            <div className={styles.loading}>
              <Spin size="large" tip="加载中..." />
            </div>
          ) : scene && chatData ? (
            // 场景聊天
            <ChatWrapper
              mode="embedded"
              sessionId={chatData.chat_id}
              sceneId={chatData.scene.id}
              sceneName={scene.name}
              welcomeMessage={chatData.welcome_message}
              showToolbar={true}
              compactLayout={true}
              onClose={onClose}
              onTogglePin={() => setIsPinned(!isPinned)}
              isPinned={isPinned}
              onDragStart={handleDragStart}
            >
              <ChatPage />
            </ChatWrapper>
          ) : (
            // 无场景模式：默认智能体
            <ChatWrapper
              mode="embedded"
              showToolbar={true}
              compactLayout={true}
              onClose={onClose}
            >
              <ChatPage />
            </ChatWrapper>
          )}
        </div>
      </div>
    );
  }

  // iframe 模式：纯聊天界面
  return (
    <div className={styles.embeddedChatContainer}>
      {loading ? (
        <div className={styles.embeddedLoading}>
          <Spin size="large" tip="加载中..." />
        </div>
      ) : chatData ? (
        <ChatWrapper
          mode="embedded"
          sessionId={chatData.chat_id}
          sceneId={chatData.scene.id}
          sceneName={urlSceneName}
          welcomeMessage={chatData.welcome_message}
          showToolbar={true}
          compactLayout={true}
        >
          <ChatPage />
        </ChatWrapper>
      ) : (
        <ChatWrapper
          mode="embedded"
          showToolbar={true}
          compactLayout={true}
        >
          <ChatPage />
        </ChatWrapper>
      )}
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════
// 独立的嵌入式页面入口（iframe 模式专用）
// ═══════════════════════════════════════════════════════════════════

const EmbeddedChatPageWrapper: React.FC = () => {
  return (
    <ConfigProvider
      theme={{
        algorithm: antdTheme.defaultAlgorithm,
        token: {
          colorPrimary: '#FF7F16',
        },
      }}
    >
      <Suspense fallback={<Spin size="large" />}>
        <EmbeddedChat mode="iframe" />
      </Suspense>
    </ConfigProvider>
  );
};

export default EmbeddedChatPageWrapper;
export { EmbeddedChat };
