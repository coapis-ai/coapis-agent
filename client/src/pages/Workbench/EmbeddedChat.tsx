// Embedded chat drawer component
import React, { useState, useEffect } from 'react';
import { Drawer, Spin, message } from 'antd';
import type { SceneConfig, EnterSceneResponse } from './types';
import styles from './EmbeddedChat.module.less';
import { getApiToken } from '../../api/config';
import { ChatWrapper } from '../../components/ChatWrapper';
import ChatPage from '../../pages/Chat';

interface EmbeddedChatProps {
  visible: boolean;
  scene: SceneConfig | null;
  onClose: () => void;
  onExpand?: (chatId: string) => void;
}

const EmbeddedChat: React.FC<EmbeddedChatProps> = ({
  visible,
  scene,
  onClose,
  onExpand,
}) => {
  const [loading, setLoading] = useState(false);
  const [chatData, setChatData] = useState<EnterSceneResponse | null>(null);

  // Load scene data when scene changes
  useEffect(() => {
    if (visible && scene) {
      enterScene();
    }
  }, [visible, scene]);

  // Reset state when drawer closes
  useEffect(() => {
    if (!visible) {
      setChatData(null);
    }
  }, [visible]);

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

  const handleExpand = () => {
    if (chatData && onExpand) {
      onExpand(chatData.chat_id);
      onClose();
    }
  };

  if (!scene) {
    return null;
  }

  return (
    <Drawer
      title={null}
      placement="right"
      width={800}
      open={visible}
      onClose={onClose}
      closable={false}
      className={styles.embeddedChat}
      destroyOnClose
      styles={{ 
        body: { padding: 0, height: '100%', display: 'flex', flexDirection: 'column' },
        wrapper: { height: 'calc(100vh - 64px)', top: '64px' }
      }}
    >
      {loading ? (
        <div className={styles.loading}>
          <Spin size="large" tip="加载中..." />
        </div>
      ) : chatData ? (
        <div className={styles.chatContent}>
          {/* 使用ChatWrapper包装Chat页面 */}
          <ChatWrapper
            mode="embedded"
            sessionId={chatData.chat_id}
            sceneId={chatData.scene.id}
            sceneName={scene.name}
            welcomeMessage={chatData.welcome_message}
            showToolbar={true}
            compactLayout={true}
            onClose={onClose}
            onExpand={onExpand ? handleExpand : undefined}
            onError={(error) => {
              console.error('Chat error:', error);
              message.error('聊天发生错误');
            }}
          >
            <ChatPage />
          </ChatWrapper>
        </div>
      ) : null}
    </Drawer>
  );
};

export default EmbeddedChat;
