import React, { useCallback, useState } from 'react';
import { Flex, Tooltip, Button } from 'antd';
import { MenuOutlined, CloseOutlined, ExpandOutlined, CompressOutlined } from '@ant-design/icons';
import { IconButton } from '@agentscope-ai/design';
import { SparkNewChatFill } from '@agentscope-ai/icons';
import { useChatAnywhereSessionsState } from '@agentscope-ai/chat';
import { useTranslation } from 'react-i18next';
import sessionApi from '../../sessionApi';
import styles from './index.module.less';

interface ChatSessionHeaderProps {
  onShowDisplaySettings?: () => void;
  onToolbarToggle?: () => void;  // 工具栏切换回调
  isEmbeddedMode?: boolean;  // 嵌入式模式
  onClose?: () => void;  // 关闭浮窗
  onExpand?: () => void;  // 展开到完整页面
  sceneName?: string;  // 场景名称
}

const ChatSessionHeader: React.FC<ChatSessionHeaderProps> = ({ 
  onToolbarToggle,
  isEmbeddedMode = false,
  onClose,
  onExpand,
  sceneName,
}) => {
  const { t } = useTranslation();
  const { sessions, currentSessionId } = useChatAnywhereSessionsState();
  const [isPinned, setIsPinned] = useState(false);

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
    setIsPinned(!isPinned);
  };

  return (
    <div className={styles.chatSessionHeader}>
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
            {onExpand && (
              <Tooltip title="展开到完整页面" mouseEnterDelay={0.5}>
                <Button
                  type="text"
                  size="small"
                  icon={<ExpandOutlined />}
                  onClick={onExpand}
                />
              </Tooltip>
            )}
            <Tooltip title={isPinned ? "取消固定" : "固定显示"} mouseEnterDelay={0.5}>
              <Button
                type="text"
                size="small"
                icon={isPinned ? <CompressOutlined /> : <ExpandOutlined />}
                onClick={handlePin}
              />
            </Tooltip>
            {onClose && (
              <Tooltip title="关闭" mouseEnterDelay={0.5}>
                <Button
                  type="text"
                  size="small"
                  icon={<CloseOutlined />}
                  onClick={onClose}
                />
              </Tooltip>
            )}
          </Flex>
        )}
      </Flex>
    </div>
  );
};

export default ChatSessionHeader;
