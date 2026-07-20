// EmbeddedChatPage - 嵌入式聊天页面
// 用于外部系统通过 iframe 嵌入，支持场景可选

import React, { useEffect, useState, Suspense, useRef, useCallback } from 'react';
import { Spin, message, ConfigProvider, theme as antdTheme } from 'antd';
import { useSearchParams } from 'react-router-dom';
import { ChatWrapper } from '../../components/ChatWrapper';
import ChatPage from '../Chat';
import { setAuthToken } from '../../api/config';
import styles from './EmbeddedChatPage.module.less';

// ═══════════════════════════════════════════════════════════════════
// postMessage 通信协议
// ═══════════════════════════════════════════════════════════════════

/**
 * 外部系统 -> CoApis 消息类型
 */
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

/**
 * CoApis -> 外部系统 事件类型
 */
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

/**
 * 发送事件到父窗口
 */
function postToParent(event: CoapisOutboundEvent) {
  if (window.parent !== window) {
    window.parent.postMessage(event, '*');
  }
}

// ═══════════════════════════════════════════════════════════════════

/**
 * 嵌入式聊天页面
 * 
 * URL 参数：
 * - token: 认证令牌（必需）
 * - scene_id: 场景 ID（可选，不传则使用默认智能体）
 * - scene_name: 场景名称（可选，用于显示）
 * 
 * postMessage API:
 * 
 * 入站消息（外部系统 -> CoApis）：
 * - COAPIS_INIT: 初始化（动态设置 token、sceneId）
 * - COAPIS_SEND_MESSAGE: 发送消息
 * - COAPIS_CLOSE: 关闭请求
 * - COAPIS_GET_STATE: 获取状态
 * 
 * 出站事件（CoApis -> 外部系统）：
 * - COAPIS_READY: 页面就绪
 * - COAPIS_MESSAGE_RECEIVED: 收到 AI 回复
 * - COAPIS_MESSAGE_SENT: 用户消息已发送
 * - COAPIS_ERROR: 错误事件
 * - COAPIS_STATE_CHANGE: 状态变化
 * - COAPIS_CLOSE_REQUEST: 请求关闭
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

  // 消息发送接口（通过 window 暴露给 ChatPage）
  const sendMessageRef = useRef<((msg: string) => void) | null>(null);

  // 解析 URL 参数
  const token = searchParams.get('token');
  const sceneId = searchParams.get('scene_id');
  const sceneName = searchParams.get('scene_name') || 'AI 助手';

  // 发送状态变化事件
  const notifyStateChange = useCallback((state: 'loading' | 'ready' | 'error', data?: any) => {
    postToParent({
      type: 'COAPIS_STATE_CHANGE',
      data: { state, ...data },
    });
  }, []);

  // 认证检查
  useEffect(() => {
    if (!token) {
      const errorMsg = '缺少认证令牌';
      setError(errorMsg);
      setLoading(false);
      notifyStateChange('error', { error: errorMsg });
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
          const errorMsg = '认证令牌无效或已过期';
          setError(errorMsg);
          setLoading(false);
          notifyStateChange('error', { error: errorMsg });
          return;
        }

        setLoading(false);
        notifyStateChange('ready');
        
        // 通知父窗口页面就绪
        postToParent({ type: 'COAPIS_READY' });
      } catch (err) {
        const errorMsg = '认证验证失败';
        setError(errorMsg);
        setLoading(false);
        notifyStateChange('error', { error: errorMsg });
      }
    };

    verifyToken();
  }, [token, notifyStateChange]);

  // 进入场景（如果指定了场景）
  useEffect(() => {
    if (loading || error || !sceneId) return;

    const enterScene = async () => {
      try {
        setLoading(true);
        notifyStateChange('loading');

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
        
        notifyStateChange('ready', { sceneId, chatId: data.chat_id });
      } catch (err) {
        console.error('Failed to enter scene:', err);
        message.error('进入场景失败，将使用默认智能体');
        // 即使场景失败，也允许聊天（使用默认智能体）
        setSceneData({
          id: sceneId,
          name: sceneName,
        });
        notifyStateChange('ready', { sceneId });
      } finally {
        setLoading(false);
      }
    };

    enterScene();
  }, [loading, error, sceneId, sceneName, token, notifyStateChange]);

  // 监听 postMessage
  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      // 安全检查：只接受来自父窗口的消息
      if (event.source !== window.parent) return;

      const msg = event.data as CoapisInboundMessage;
      if (!msg || !msg.type) return;

      switch (msg.type) {
        case 'COAPIS_INIT':
          // 动态初始化
          if (msg.payload?.token) {
            setAuthToken(msg.payload.token);
          }
          if (msg.payload?.sceneId) {
            // 动态切换场景
            const newUrl = new URL(window.location.href);
            if (msg.payload.token) newUrl.searchParams.set('token', msg.payload.token);
            if (msg.payload.sceneId) newUrl.searchParams.set('scene_id', msg.payload.sceneId);
            if (msg.payload.sceneName) newUrl.searchParams.set('scene_name', msg.payload.sceneName);
            window.location.href = newUrl.toString();
          }
          break;

        case 'COAPIS_SEND_MESSAGE':
          // 外部发送消息
          if (msg.payload?.message && sendMessageRef.current) {
            sendMessageRef.current(msg.payload.message);
            postToParent({
              type: 'COAPIS_MESSAGE_SENT',
              data: { message: msg.payload.message },
            });
          }
          break;

        case 'COAPIS_CLOSE':
          // 外部请求关闭
          postToParent({ type: 'COAPIS_CLOSE_REQUEST' });
          break;

        case 'COAPIS_GET_STATE':
          // 返回当前状态
          postToParent({
            type: 'COAPIS_STATE_CHANGE',
            data: {
              state: loading ? 'loading' : error ? 'error' : 'ready',
              sceneId: sceneData?.id,
              chatId: sceneData?.chatId,
            },
          });
          break;
      }
    };

    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [loading, error, sceneData]);

  // 暴露消息发送接口（ChatPage 可以通过 window 调用）
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
