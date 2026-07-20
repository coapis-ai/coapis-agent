import React, { useEffect, useState, Suspense } from 'react';
import { Spin, message, ConfigProvider, theme as antdTheme } from 'antd';
import { useSearchParams } from 'react-router-dom';
import { ChatWrapper } from '../../components/ChatWrapper';
import ChatPage from '../Chat';
import { setAuthToken } from '../../api/config';
import styles from './EmbeddedChatPage.module.less';

/**
 * 嵌入式聊天页面
 * 
 * URL 参数：
 * - token: 认证令牌（必需）
 * - scene_id: 场景 ID（可选，不传则使用默认智能体）
 * - scene_name: 场景名称（可选，用于显示）
 * 
 * 示例：
 * - 有场景：/chat/embedded?token=xxx&scene_id=meeting-minutes&scene_name=会议纪要
 * - 无场景：/chat/embedded?token=xxx
 */
const EmbeddedChatPage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sceneData, setSceneData] = useState<{
    id: string;
    name: string;
    chatId?: string;
    welcomeMessage?: string;
  } | null>(null);

  // 解析 URL 参数
  const token = searchParams.get('token');
  const sceneId = searchParams.get('scene_id');
  const sceneName = searchParams.get('scene_name') || 'AI 助手';

  // 认证检查
  useEffect(() => {
    if (!token) {
      setError('缺少认证令牌');
      setLoading(false);
      return;
    }

    // 设置 token
    setAuthToken(token);

    // 验证 token
    const verifyToken = async () => {
      try {
        const response = await fetch('/api/auth/verify', {
          headers: { Authorization: `Bearer ${token}` },
        });

        if (!response.ok) {
          setError('认证令牌无效或已过期');
          setLoading(false);
          return;
        }

        setLoading(false);
      } catch (err) {
        setError('认证验证失败');
        setLoading(false);
      }
    };

    verifyToken();
  }, [token]);

  // 进入场景（如果指定了场景）
  useEffect(() => {
    if (loading || error || !sceneId) return;

    const enterScene = async () => {
      try {
        setLoading(true);
        const response = await fetch(`/api/scenes/${sceneId}/enter`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`,
          },
        });

        if (!response.ok) {
          throw new Error('进入场景失败');
        }

        const data = await response.json();
        setSceneData({
          id: sceneId,
          name: sceneName,
          chatId: data.chat_id,
          welcomeMessage: data.welcome_message,
        });
      } catch (err) {
        console.error('Failed to enter scene:', err);
        message.error('进入场景失败，将使用默认智能体');
        // 即使场景失败，也允许聊天（使用默认智能体）
        setSceneData({
          id: sceneId,
          name: sceneName,
        });
      } finally {
        setLoading(false);
      }
    };

    enterScene();
  }, [loading, error, sceneId, sceneName, token]);

  // 监听 postMessage（可选的动态初始化）
  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      // 安全检查：只接受来自父窗口的消息
      if (event.source !== window.parent) return;

      const { type, payload } = event.data || {};

      switch (type) {
        case 'COAPIS_INIT':
          // 动态初始化
          if (payload.token) {
            setAuthToken(payload.token);
          }
          if (payload.sceneId) {
            // 可以动态设置场景
            window.location.search = `?token=${payload.token}&scene_id=${payload.sceneId}`;
          }
          break;

        case 'COAPIS_MESSAGE':
          // 外部发送消息
          // 可以通过 window.__COAPIS_SEND_MESSAGE__ 注入消息
          break;

        case 'COAPIS_CLOSE':
          // 外部请求关闭
          if (window.parent !== window) {
            window.parent.postMessage({ type: 'COAPIS_CLOSE_REQUEST' }, '*');
          }
          break;
      }
    };

    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, []);

  // 加载中
  if (loading) {
    return (
      <div className={styles.embeddedLoading}>
        <Spin size="large" tip="加载中..." />
      </div>
    );
  }

  // 错误状态
  if (error) {
    return (
      <div className={styles.embeddedError}>
        <p>⚠️ {error}</p>
        <p>请检查 URL 参数或联系管理员</p>
      </div>
    );
  }

  // 有场景：使用场景会话 ID
  // 无场景：使用默认智能体
  return (
    <div className={styles.embeddedChatContainer}>
      <ChatWrapper
        mode="embedded"
        sessionId={sceneData?.chatId}
        sceneId={sceneData?.id}
        sceneName={sceneData?.name || 'AI 助手'}
        welcomeMessage={sceneData?.welcomeMessage}
        showToolbar={true}
        compactLayout={true}
      >
        <ChatPage />
      </ChatWrapper>
    </div>
  );
};

// 独立的嵌入式页面入口（不依赖 MainLayout）
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
        <EmbeddedChatPage />
      </Suspense>
    </ConfigProvider>
  );
};

export default EmbeddedChatPageWrapper;
