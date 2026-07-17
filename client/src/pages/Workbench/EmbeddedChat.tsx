// Embedded chat drawer component
import React, { useState, useEffect } from 'react';
import { Drawer, Button, Spin, Empty, message } from 'antd';
import { CloseOutlined, ExpandOutlined } from '@ant-design/icons';
import type { SceneConfig, EnterSceneResponse } from '../Workbench/types';
import styles from './EmbeddedChat.module.less';

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
      const response = await fetch(`/api/scenes/${scene.id}/enter`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
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
      title={
        <div className={styles.drawerHeader}>
          <div className={styles.sceneInfo}>
            <span className={styles.sceneIcon}>{scene.icon}</span>
            <span className={styles.sceneName}>{scene.name}</span>
          </div>
          <div className={styles.actions}>
            {onExpand && (
              <Button
                type="text"
                icon={<ExpandOutlined />}
                onClick={handleExpand}
                title="展开到完整页面"
              />
            )}
          </div>
        </div>
      }
      placement="right"
      width={600}
      open={visible}
      onClose={onClose}
      closeIcon={<CloseOutlined />}
      className={styles.embeddedChat}
      destroyOnClose
    >
      {loading ? (
        <div className={styles.loading}>
          <Spin size="large" tip="加载中..." />
        </div>
      ) : chatData ? (
        <div className={styles.chatContent}>
          {/* Welcome message */}
          {chatData.welcome_message && (
            <div className={styles.welcomeMessage}>
              <p>{chatData.welcome_message}</p>
            </div>
          )}
          
          {/* TODO: Integrate with @agentscope-ai/chat component */}
          {/* For now, show placeholder */}
          <div className={styles.chatPlaceholder}>
            <Empty
              description={
                <span>
                  聊天功能开发中...
                  <br />
                  Chat ID: {chatData.chat_id}
                </span>
              }
            />
          </div>
        </div>
      ) : (
        <Empty description="场景加载失败" />
      )}
    </Drawer>
  );
};

export default EmbeddedChat;
