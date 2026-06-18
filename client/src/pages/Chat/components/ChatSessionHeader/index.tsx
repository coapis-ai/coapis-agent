import React, { useState, useEffect, useCallback } from 'react';
import { Flex, Tooltip, Popover } from 'antd';
import { BgColorsOutlined } from '@ant-design/icons';
import { IconButton } from '@agentscope-ai/design';
import {
  SparkHistoryLine,
  SparkNewChatFill,
  SparkSearchLine,
} from '@agentscope-ai/icons';
import { useChatAnywhereSessionsState } from '@agentscope-ai/chat';
import { useTranslation } from 'react-i18next';
import ChatSessionDropdown from '../ChatSessionDropdown';
import ChatSearchDropdown from '../ChatSearchDropdown';
import PlanPanel from '../../../../components/PlanPanel';
import { planApi } from '../../../../api/modules/plan';
import sessionApi from '../../sessionApi';
import { useAgentStore } from '../../../../stores/agentStore';
import ModelSelector from '../../ModelSelector';
import styles from './index.module.less';

interface ChatSessionHeaderProps {
  onShowDisplaySettings: () => void;
}

const PlanIcon = () => (
  <svg
    width="1em"
    height="1em"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d="M9 11l3 3L22 4" />
    <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
  </svg>
);

const ChatSessionHeader: React.FC<ChatSessionHeaderProps> = ({ onShowDisplaySettings }) => {
  const { t } = useTranslation();
  const [historyOpen, setHistoryOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [planOpen, setPlanOpen] = useState(false);
  const [planEnabled, setPlanEnabled] = useState(false);
  const { sessions, currentSessionId } = useChatAnywhereSessionsState();
  const { selectedAgent } = useAgentStore();

  // Direct new chat: go through sessionApi so sidebar updates immediately
  const handleNewChat = useCallback(async () => {
    try {
      await sessionApi.createSession({ name: '' });
    } catch (err) {
      console.error('[NewChat] Failed to create chat:', err);
    }
  }, []);

  // Get current session title — prefer real-time data from sessionApi
  const liveSession = sessionApi.currentSession;
  const currentSession = sessions.find((s) => s.id === currentSessionId) || liveSession;
  const chatTitle = currentSession?.name || t('chat.newChatTitle', 'New Chat');

  useEffect(() => {
    let cancelled = false;
    planApi
      .getPlanConfig()
      .then((cfg) => {
        if (!cancelled) setPlanEnabled(cfg.enabled);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [selectedAgent]);

  // Close other panels when one opens
  const handleHistoryToggle = () => {
    if (historyOpen) {
      setHistoryOpen(false);
      setSearchOpen(false);
    } else {
      setHistoryOpen(true);
      setSearchOpen(false);
    }
  };

  const handleSearchToggle = () => {
    if (searchOpen) {
      setSearchOpen(false);
      setHistoryOpen(false);
    } else {
      setSearchOpen(true);
      setHistoryOpen(false);
    }
  };

  return (
    <div className={styles.sessionHeader}>
      {/* Left side: icons + title */}
      <Flex align="center" className={styles.headerLeft} gap={4}>
        {/* Order: Display Settings → Search → History → New Chat → Title */}
        <Tooltip title={t('chat.settings.title', { defaultValue: '聊天显示设置' })}>
          <IconButton
            bordered={false}
            icon={<BgColorsOutlined />}
            onClick={onShowDisplaySettings}
          />
        </Tooltip>
        
        {/* Search - dropdown below button */}
        <Popover
          content={
            <ChatSearchDropdown
              open={searchOpen}
              onClose={() => setSearchOpen(false)}
            />
          }
          open={searchOpen}
          onOpenChange={handleSearchToggle}
          placement="bottomLeft"
          arrow={{ pointAtCenter: false }}
          overlayInnerStyle={{ padding: 0 }}
          overlayStyle={{ marginLeft: '-8px' }}
        >
          <Tooltip title={t('chat.searchTooltip')} mouseEnterDelay={0.5}>
            <span>
              <IconButton
                bordered={false}
                icon={<SparkSearchLine />}
                onClick={handleSearchToggle}
              />
            </span>
          </Tooltip>
        </Popover>
        
        {/* History - dropdown below button */}
        <Popover
          content={
            <ChatSessionDropdown
              open={historyOpen}
              onClose={() => setHistoryOpen(false)}
            />
          }
          open={historyOpen}
          onOpenChange={(open) => {
            setHistoryOpen(open);
            if (open) setSearchOpen(false);
          }}
          placement="bottomLeft"
          arrow={{ pointAtCenter: false }}
          overlayInnerStyle={{ padding: 0 }}
          overlayStyle={{ marginLeft: '-8px' }}
        >
          <Tooltip title={t('chat.chatHistoryTooltip')} mouseEnterDelay={0.5}>
            <span>
              <IconButton
                bordered={false}
                icon={<SparkHistoryLine />}
                onClick={handleHistoryToggle}
              />
            </span>
          </Tooltip>
        </Popover>
        
        <Tooltip title={t('chat.newChatTooltip')} mouseEnterDelay={0.5}>
          <IconButton
            bordered={false}
            icon={<SparkNewChatFill />}
            onClick={handleNewChat}
          />
        </Tooltip>
        <span className={styles.sessionTitle}>{chatTitle}</span>
      </Flex>
      {/* Right side: model selector + plan */}
      <Flex gap={4} align="center" className={styles.headerRight}>
        <ModelSelector />
        {planEnabled && (
          <Tooltip title={t('plan.title', 'Plan')} mouseEnterDelay={0.5}>
            <IconButton
              bordered={false}
              icon={<PlanIcon />}
              onClick={() => setPlanOpen(true)}
            />
          </Tooltip>
        )}
        {planEnabled && (
          <PlanPanel open={planOpen} onClose={() => setPlanOpen(false)} />
        )}
      </Flex>
    </div>
  );
};

export default ChatSessionHeader;
