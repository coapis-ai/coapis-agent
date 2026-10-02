import React, { useCallback, useState, useEffect } from 'react';
import { Flex, Tooltip, Button } from 'antd';
import {
  MenuOutlined,
  CloseOutlined,
  PushpinOutlined,
  PushpinFilled,
  ArrowsAltOutlined,
  VerticalLeftOutlined,
} from '@ant-design/icons';
import { IconButton } from '@agentscope-ai/design';
import { SparkNewChatFill } from '@agentscope-ai/icons';
import { useChatAnywhereSessionsState } from '@agentscope-ai/chat';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import sessionApi from '../../sessionApi';
import { getChatGlobals } from '../../../../lib/chatGlobals';
import { getLastNonChatPath } from '../../../../lib/lastNonChatPath';
import { useChatWindow } from '../../../../contexts/ChatWindowContext';
import styles from './index.module.less';

interface ChatSessionHeaderProps {
  onShowDisplaySettings?: () => void;
  onToolbarToggle?: () => void;  // 工具栏切换回调
  isEmbeddedMode?: boolean;  // 嵌入式模式
  onClose?: () => void;  // 关闭浮窗
  sceneName?: string;  // 场景名称
}

const ChatSessionHeader: React.FC<ChatSessionHeaderProps> = ({ 
  onToolbarToggle,
  isEmbeddedMode = false,
  onClose: onCloseProp,
  sceneName,
}) => {
  const { t } = useTranslation();
  const { sessions, currentSessionId } = useChatAnywhereSessionsState();
  const [isPinned, setIsPinned] = useState(false);
  const [onTogglePin, setOnTogglePin] = useState<(() => void) | null>(null);
  const [onDragStart, setOnDragStart] = useState<((e: React.MouseEvent) => void) | null>(null);
  const [onClose, setOnClose] = useState<(() => void) | null>(null);

  // 从 lib/chatGlobals 命名空间读取嵌入式模式参数（M3/T3.2：替代旧 __CHAT_*__ 全局变量）
  useEffect(() => {
    if (isEmbeddedMode) {
      const g = getChatGlobals();
      const windowOnTogglePin = g.onTogglePin;
      const windowIsPinned = g.isPinned;
      const windowOnDragStart = g.onDragStart;
      const windowOnClose = g.onClose;

      if (typeof windowOnTogglePin === 'function') {
        setOnTogglePin(() => windowOnTogglePin);
      }
      if (typeof windowIsPinned === 'boolean') {
        setIsPinned(windowIsPinned);
      }
      if (typeof windowOnDragStart === 'function') {
        setOnDragStart(() => windowOnDragStart);
      }
      if (typeof windowOnClose === 'function') {
        setOnClose(() => windowOnClose);
      }
    }
  }, [isEmbeddedMode]);

  // M3/T3.1：全屏 ⇄ 浮窗双向联动（切换不丢会话：两侧共享同一全局会话状态）
  const navigate = useNavigate();
  const { openChat } = useChatWindow();

  // 浮窗 → 展开为全屏
  const handleExpandToFull = useCallback(() => {
    navigate('/chat');
  }, [navigate]);

  // 全屏 → 最小化回浮窗（关闭全屏 = 回到原页面，会话保留）
  const handleMinimizeToFloat = useCallback(() => {
    navigate(getLastNonChatPath() || '/workbench');
    openChat(null);
  }, [navigate, openChat]);

  // Direct new chat: go through sessionApi so sidebar updates immediately
  const handleNewChat = useCallback(async () => {
    try {
      await sessionApi.createSession({ name: '' });
    } catch (err) {
      console.error('[NewChat] Failed to create chat:', err);
    }
  }, []);

  // Get current session title — prefer real-time data from sessionApi
  // Match by id, realId, or sessionId to handle merge scenarios where
  // the session's id is a local timestamp but currentSessionId is a UUID.
  const liveSession = sessionApi.currentSession;
  const currentSession =
    sessions.find((s) => s.id === currentSessionId) ??
    sessions.find((s) => (s as any).realId === currentSessionId) ??
    sessions.find((s) => (s as any).sessionId === currentSessionId) ??
    liveSession;
  
  // 嵌入式模式：显示场景名称，否则显示会话标题
  const chatTitle = isEmbeddedMode && sceneName 
    ? sceneName 
    : (currentSession?.name || t('chat.newChatTitle', 'New Chat'));

  const handlePin = () => {
    if (onTogglePin) {
      onTogglePin();
      setIsPinned(!isPinned);
    }
  };

  const handleMouseDown = (e: React.MouseEvent) => {
    if (onDragStart) {
      onDragStart(e);
    }
  };

  return (
    <div 
      className={styles.chatSessionHeader}
      onMouseDown={isEmbeddedMode ? handleMouseDown : undefined}
      style={isEmbeddedMode ? { cursor: 'move' } : undefined}
    >
      <Flex gap={8} align="center" style={{ width: '100%' }}>
        {/* 左侧：工具栏按钮 + 新聊天按钮 */}
        <Tooltip title={t('chat.toolbarTooltip', '工具栏')} mouseEnterDelay={0.5}>
          <IconButton
            bordered={false}
            icon={<MenuOutlined />}
            onClick={onToolbarToggle}
          />
        </Tooltip>

        <Tooltip title={t('chat.newChatTooltip')} mouseEnterDelay={0.5}>
          <IconButton
            bordered={false}
            icon={<SparkNewChatFill />}
            onClick={handleNewChat}
          />
        </Tooltip>

        {/* 中间：聊天标题 */}
        <span className={styles.sessionTitle}>{chatTitle}</span>

        {/* 右侧：嵌入式模式下的操作按钮 */}
        {isEmbeddedMode && (
          <Flex gap={4} align="center" style={{ marginLeft: 'auto' }}>
            {/* M3/T3.1：浮窗 → 展开为全屏（切换不丢会话） */}
            <Tooltip title="展开为全屏" mouseEnterDelay={0.5}>
              <Button
                type="text"
                size="small"
                icon={<ArrowsAltOutlined />}
                onClick={handleExpandToFull}
              />
            </Tooltip>
            {onTogglePin && (
              <Tooltip title={isPinned ? "取消固定" : "固定窗口"} mouseEnterDelay={0.5}>
                <Button
                  type="text"
                  size="small"
                  icon={isPinned ? <PushpinFilled /> : <PushpinOutlined />}
                  onClick={handlePin}
                  className={isPinned ? styles.pinned : ''}
                />
              </Tooltip>
            )}
            {(onClose || onCloseProp) && (
              <Tooltip title="关闭" mouseEnterDelay={0.5}>
                <Button
                  type="text"
                  size="small"
                  icon={<CloseOutlined />}
                  onClick={() => {
                    // 优先使用从 window 读取的 onClose
                    if (onClose) {
                      onClose();
                    } else if (onCloseProp) {
                      onCloseProp();
                    }
                  }}
                />
              </Tooltip>
            )}
          </Flex>
        )}

        {/* M3/T3.1 + T3.3：全屏模式 → 最小化为浮窗（关闭全屏 = 回到原页面，会话保留） */}
        {!isEmbeddedMode && (
          <Flex gap={4} align="center" style={{ marginLeft: 'auto' }}>
            <Tooltip title="最小化到浮窗（回到原页面）" mouseEnterDelay={0.5}>
              <Button
                type="text"
                size="small"
                icon={<VerticalLeftOutlined />}
                onClick={handleMinimizeToFloat}
              />
            </Tooltip>
          </Flex>
        )}
      </Flex>
    </div>
  );
};

export default ChatSessionHeader;
