// FloatingChatWindow - 可拖拽、可缩放的浮窗组件
import React, { useState, useRef, useEffect, useCallback } from 'react';
import { Spin, message, Button, Tooltip } from 'antd';
import { CloseOutlined, PushpinOutlined, PushpinFilled } from '@ant-design/icons';
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

/**
 * 可拖拽、可缩放的浮窗组件
 * 
 * 功能：
 * 1. 拖拽：按住标题栏移动窗口
 * 2. 缩放：拖拽右下角调整窗口大小
 * 3. 固定：固定后点击外部不关闭
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
  
  // 窗口状态
  const [position, setPosition] = useState({ x: 100, y: 50 });
  const [size, setSize] = useState({ width: initialWidth, height: initialHeight });
  const [isPinned, setIsPinned] = useState(false);
  
  // 拖拽/缩放状态
  const [isDragging, setIsDragging] = useState(false);
  const [isResizing, setIsResizing] = useState(false);
  const dragStartRef = useRef({ x: 0, y: 0, windowX: 0, windowY: 0 });
  const resizeStartRef = useRef({ x: 0, y: 0, width: 0, height: 0 });
  
  const containerRef = useRef<HTMLDivElement>(null);

  // 加载场景数据
  useEffect(() => {
    if (visible && scene) {
      enterScene();
    }
  }, [visible, scene]);

  // 重置状态
  useEffect(() => {
    if (!visible) {
      setChatData(null);
      setPosition({ x: 100, y: 50 });
      setSize({ width: initialWidth, height: initialHeight });
      setIsPinned(false);
    }
  }, [visible]);

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
      setChatData(data);
      message.success(`已进入场景: ${scene.name}`);
    } catch (error) {
      console.error('Failed to enter scene:', error);
      message.error('进入场景失败');
    } finally {
      setLoading(false);
    }
  };

  // 拖拽逻辑
  const handleDragStart = useCallback((e: React.MouseEvent) => {
    if (isResizing) return;
    
    e.preventDefault();
    setIsDragging(true);
    dragStartRef.current = {
      x: e.clientX,
      y: e.clientY,
      windowX: position.x,
      windowY: position.y,
    };
  }, [isResizing, position]);

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

  // 缩放逻辑
  const handleResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsResizing(true);
    resizeStartRef.current = {
      x: e.clientX,
      y: e.clientY,
      width: size.width,
      height: size.height,
    };
  }, [size]);

  useEffect(() => {
    if (!isResizing) return;

    const handleMouseMove = (e: MouseEvent) => {
      const deltaX = e.clientX - resizeStartRef.current.x;
      const deltaY = e.clientY - resizeStartRef.current.y;
      
      const newWidth = Math.max(minWidth, resizeStartRef.current.width + deltaX);
      const newHeight = Math.max(minHeight, resizeStartRef.current.height + deltaY);
      
      setSize({ width: newWidth, height: newHeight });
    };

    const handleMouseUp = () => {
      setIsResizing(false);
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isResizing, minWidth, minHeight]);

  if (!scene) return null;

  return (
    <div
      ref={containerRef}
      className={styles.floatingWindow}
      style={{
        left: position.x,
        top: position.y,
        width: size.width,
        height: size.height,
        cursor: isDragging ? 'move' : 'default',
      }}
    >
      {/* 标题栏 - 可拖拽 */}
      <div
        className={styles.windowHeader}
        onMouseDown={handleDragStart}
      >
        <div className={styles.sceneInfo}>
          <span className={styles.sceneIcon}>{scene.icon}</span>
          <span className={styles.sceneName}>{scene.name}</span>
        </div>
        <div className={styles.headerActions}>
          <Tooltip title={isPinned ? "取消固定" : "固定窗口"}>
            <Button
              type="text"
              size="small"
              icon={isPinned ? <PushpinFilled /> : <PushpinOutlined />}
              onClick={() => setIsPinned(!isPinned)}
              className={isPinned ? styles.pinned : ''}
            />
          </Tooltip>
          <Tooltip title="关闭">
            <Button
              type="text"
              size="small"
              icon={<CloseOutlined />}
              onClick={onClose}
            />
          </Tooltip>
        </div>
      </div>

      {/* 内容区域 */}
      <div className={styles.windowBody}>
        {loading ? (
          <div className={styles.loading}>
            <Spin size="large" tip="加载中..." />
          </div>
        ) : chatData ? (
          <ChatWrapper
            mode="embedded"
            sessionId={chatData.chat_id}
            sceneId={chatData.scene.id}
            sceneName={scene.name}
            welcomeMessage={chatData.welcome_message}
            showToolbar={true}
            compactLayout={true}
            onError={(error) => {
              console.error('Chat error:', error);
              message.error('聊天发生错误');
            }}
          >
            <ChatPage />
          </ChatWrapper>
        ) : null}
      </div>

      {/* 缩放手柄 - 右下角 */}
      <div
        className={styles.resizeHandle}
        onMouseDown={handleResizeStart}
      />
    </div>
  );
};

export default FloatingChatWindow;
