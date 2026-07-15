import React, { useCallback } from 'react';
import { Flex, Tooltip } from 'antd';
import { MenuOutlined } from '@ant-design/icons';
import { IconButton } from '@agentscope-ai/design';
import { SparkNewChatFill } from '@agentscope-ai/icons';
import { useChatAnywhereSessionsState } from '@agentscope-ai/chat';
import { useTranslation } from 'react-i18next';
import sessionApi from '../../sessionApi';
import styles from './index.module.less';

interface ChatSessionHeaderProps {
  onShowDisplaySettings?: () => void;
  onToolbarToggle?: () => void;  // 工具栏切换回调
}

const ChatSessionHeader: React.FC<ChatSessionHeaderProps> = ({ 
  onToolbarToggle,
}) => {
  const { t } = useTranslation();
  const { sessions, currentSessionId } = useChatAnywhereSessionsState();

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
  const chatTitle = currentSession?.name || t('chat.newChatTitle', 'New Chat');

  return (
    <div className={styles.chatSessionHeader}>
      <Flex gap={8} align="center" justify="space-between" style={{ width: '100%' }}>
        {/* 左侧：根工具按钮 */}
        <Tooltip title={t('chat.toolbarTooltip', '工具栏')} mouseEnterDelay={0.5}>
          <IconButton
            bordered={false}
            icon={<MenuOutlined />}
            onClick={onToolbarToggle}
          />
        </Tooltip>

        {/* 中间：聊天标题 */}
        <span className={styles.sessionTitle}>{chatTitle}</span>

        {/* 右侧：新聊天按钮 */}
        <Tooltip title={t('chat.newChatTooltip')} mouseEnterDelay={0.5}>
          <IconButton
            bordered={false}
            icon={<SparkNewChatFill />}
            onClick={handleNewChat}
          />
        </Tooltip>
      </Flex>
    </div>
  );
};

export default ChatSessionHeader;
