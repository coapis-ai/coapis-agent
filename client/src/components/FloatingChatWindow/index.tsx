// FloatingChatWindow - 可拖拽、可缩放的浮窗组件
import React, { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { Spin, message } from 'antd';
import type { SceneConfig, EnterSceneResponse } from '../../pages/Workbench/types';
import styles from './index.module.less';
import { getApiToken } from '../../api/config';
import { ChatWrapper } from '../ChatWrapper';
import ChatPage from '../../pages/Chat';

interface FloatingChatWindowProps {
  visible: boolean;
  scene: SceneConfig | null;
  onClose: () => void;
  initialWidth?: number;
  initialHeight?: number;
  minWidth?: number;
  minHeight?: number;
}

// 缩放角类型
type ResizeCorner = 'nw' | 'ne' | 'sw' | 'se';

/**
 * 检测是否为移动设备
 */
const isMobileDevice = (): boolean => {
  return /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent) 
    || window.innerWidth < 768;
};

/**
 * 可拖拽、可缩放的浮窗组件
 * 
 * 功能：
 * 1. 拖拽：按住标题栏移动窗口（桌面端）
 * 2. 四角缩放：拖拽四个角调整窗口大小（桌面端）
 * 3. 固定：固定后点击外部不关闭
 * 4. 移动端优化：自适应尺寸，接近全屏
 */
const FloatingChatWindow: React.FC<FloatingChatWindowProps> = ({
  visible,
  scene,
  onClose,
  initialWidth = 700,
  initialHeight = 500,
  minWidth = 400,
  minHeight = 300,
}) => {
  const [loading, setLoading] = useState(false);
  const [chatData, setChatData] = useState<EnterSceneResponse | null>(null);
  
  // 检测移动设备
  const isMobile = useMemo(() => isMobileDevice(), []);
  
  // 移动端使用自适应尺寸，桌面端使用固定尺寸
  const [position, setPosition] = useState(() => {
    if (isMobile) {
      // 移动端：固定在顶部
      return { x: 0, y: 0 };
    }
    // 桌面端：初始位置偏右侧
    const initialX = Math.max(50, window.innerWidth - initialWidth - 50);
    return { x: initialX, y: 50 };
  });
  
  const [size, setSize] = useState(() => {
    if (isMobile) {
      // 移动端：接近全屏（95vw × 85vh）
      return {
        width: window.innerWidth * 0.95,
        height: window.innerHeight * 0.85,
      };
    }
    // 桌面端：使用传入的尺寸
    return { width: initialWidth, height: initialHeight };
  });
  
  const [isPinned, setIsPinned] = useState(false);
  
  // 拖拽状态（移动端禁用）
  const [isDragging, setIsDragging] = useState(false);
  const dragStartRef = useRef({ x: 0, y: 0, windowX: 0, windowY: 0 });
  
  // 缩放状态（移动端禁用）
  const [isResizing, setIsResizing] = useState(false);
  const [resizeCorner, setResizeCorner] = useState<ResizeCorner | null>(null);
  const resizeStartRef = useRef({ x: 0, y: 0, width: 0, height: 0, posX: 0, posY: 0 });
  
  const containerRef = useRef<HTMLDivElement>(null);

  // 加载场景数据
  useEffect(() => {
    if (visible) {
      if (scene) {
        // 场景聊天：调用 enterScene API
        enterScene();
      } else {
        // 普通聊天：清空场景数据，使用默认智能体
        setChatData(null);
      }
    }
  }, [visible, scene]);

  // 重置状态（仅在未固定时）
  useEffect(() => {
    if (!visible) {
      setChatData(null);
      // 未固定时才重置位置和大小
      if (!isPinned) {
        // 初始位置：偏右侧
        const initialX = Math.max(50, window.innerWidth - initialWidth - 50);
        setPosition({ x: initialX, y: 50 });
        setSize({ width: initialWidth, height: initialHeight });
      }
      setIsPinned(false);
    }
  }, [visible, isPinned, initialWidth, initialHeight]);

  // 点击外部关闭（未固定时）
  useEffect(() => {
    if (!visible || isPinned) return;

    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        onClose();
      }
    };

    // 延迟添加监听，避免立即触发
    const timer = setTimeout(() => {
      document.addEventListener('mousedown', handleClickOutside);
    }, 100);

    return () => {
      clearTimeout(timer);
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [visible, isPinned, onClose]);

  const enterScene = async () => {
    if (!scene) return;
    
    try {
      setLoading(true);
      const token = getApiToken();
      const response = await fetch(`/api/scenes/${scene.id}/enter`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
      });

      if (!response.ok) {
        throw new Error('Failed to enter scene');
      }

      const data: EnterSceneResponse = await response.json();
      
      // 🔍 调试：打印返回的数据
      console.log('🔍 [enterScene] Response:', {
        chat_id: data.chat_id,
        session_id: data.session_id,
        scene_id: data.scene?.id,
        agent_id: data.agent?.id,
      });
      
      setChatData(data);
      message.success(`已进入场景: ${scene.name}`);
    } catch (error) {
      console.error('Failed to enter scene:', error);
      message.error('进入场景失败');
    } finally {
      setLoading(false);
    }
  };

  // 拖拽逻辑（移动端禁用）
  const handleDragStart = useCallback((e: React.MouseEvent) => {
    // 移动端禁用拖拽
    if (isMobile) return;
    if (isResizing) return;
    
    e.preventDefault();
    setIsDragging(true);
    dragStartRef.current = {
      x: e.clientX,
      y: e.clientY,
      windowX: position.x,
      windowY: position.y,
    };
  }, [isMobile, isResizing, position]);

  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e: MouseEvent) => {
      const deltaX = e.clientX - dragStartRef.current.x;
      const deltaY = e.clientY - dragStartRef.current.y;
      
      const newX = Math.max(0, Math.min(window.innerWidth - size.width, dragStartRef.current.windowX + deltaX));
      const newY = Math.max(0, Math.min(window.innerHeight - 100, dragStartRef.current.windowY + deltaY));
      
      setPosition({ x: newX, y: newY });
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
  }, [isDragging, size]);

  // 四角缩放逻辑（移动端禁用）
  const handleResizeStart = useCallback((corner: ResizeCorner) => (e: React.MouseEvent) => {
    // 移动端禁用缩放
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
    if (!isResizing || !resizeCorner) return;

    const handleMouseMove = (e: MouseEvent) => {
      const deltaX = e.clientX - resizeStartRef.current.x;
      const deltaY = e.clientY - resizeStartRef.current.y;
      
      let newWidth = resizeStartRef.current.width;
      let newHeight = resizeStartRef.current.height;
      let newX = resizeStartRef.current.posX;
      let newY = resizeStartRef.current.posY;
      
      // 根据角的位置计算新尺寸和位置
      switch (resizeCorner) {
        case 'nw': // 左上角：向左上缩放
          newWidth = Math.max(minWidth, resizeStartRef.current.width - deltaX);
          newHeight = Math.max(minHeight, resizeStartRef.current.height - deltaY);
          newX = resizeStartRef.current.posX + (resizeStartRef.current.width - newWidth);
          newY = resizeStartRef.current.posY + (resizeStartRef.current.height - newHeight);
          break;
        case 'ne': // 右上角：向右上缩放
          newWidth = Math.max(minWidth, resizeStartRef.current.width + deltaX);
          newHeight = Math.max(minHeight, resizeStartRef.current.height - deltaY);
          newY = resizeStartRef.current.posY + (resizeStartRef.current.height - newHeight);
          break;
        case 'sw': // 左下角：向左下缩放
          newWidth = Math.max(minWidth, resizeStartRef.current.width - deltaX);
          newHeight = Math.max(minHeight, resizeStartRef.current.height + deltaY);
          newX = resizeStartRef.current.posX + (resizeStartRef.current.width - newWidth);
          break;
        case 'se': // 右下角：向右下缩放
          newWidth = Math.max(minWidth, resizeStartRef.current.width + deltaX);
          newHeight = Math.max(minHeight, resizeStartRef.current.height + deltaY);
          break;
      }
      
      // 边界限制
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
  }, [isResizing, resizeCorner, minWidth, minHeight]);

  // 如果不可见，不渲染
  if (!visible) return null;

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
      {/* 内容区域（无标题栏，由 ChatSessionHeader 作为标题栏） */}
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
            onError={(error) => {
              console.error('Chat error:', error);
              message.error('聊天发生错误');
            }}
          >
            <ChatPage />
          </ChatWrapper>
        ) : !scene ? (
          // 无场景模式：默认智能体聊天
          <ChatWrapper
            mode="embedded"
            showToolbar={true}
            compactLayout={true}
            onClose={onClose}
            onTogglePin={() => setIsPinned(!isPinned)}
            isPinned={isPinned}
            onDragStart={handleDragStart}
          >
            <ChatPage />
          </ChatWrapper>
        ) : null}
      </div>

      {/* 四角缩放手柄（移动端隐藏） */}
      {!isMobile && (
        <>
          <div className={`${styles.resizeHandle} ${styles.resizeNw}`} onMouseDown={handleResizeStart('nw')} />
          <div className={`${styles.resizeHandle} ${styles.resizeNe}`} onMouseDown={handleResizeStart('ne')} />
          <div className={`${styles.resizeHandle} ${styles.resizeSw}`} onMouseDown={handleResizeStart('sw')} />
          <div className={`${styles.resizeHandle} ${styles.resizeSe}`} onMouseDown={handleResizeStart('se')} />
        </>
      )}
    </div>
  );
};

export default FloatingChatWindow;
