// 全局聊天窗口状态管理
import { createContext, useContext, useState, ReactNode } from 'react';
import type { SceneConfig } from '../pages/Workbench/types';

interface ChatWindowState {
  visible: boolean;
  scene: SceneConfig | null;
  setScene: (scene: SceneConfig | null) => void;
  openChat: (scene?: SceneConfig | null) => void;
  closeChat: () => void;
}

const ChatWindowContext = createContext<ChatWindowState | null>(null);

export function ChatWindowProvider({ children }: { children: ReactNode }) {
  const [visible, setVisible] = useState(false);
  const [scene, setScene] = useState<SceneConfig | null>(null);

  const openChat = (newScene?: SceneConfig | null) => {
    setScene(newScene || null);
    setVisible(true);
  };

  const closeChat = () => {
    setVisible(false);
  };

  return (
    <ChatWindowContext.Provider value={{ visible, scene, setScene, openChat, closeChat }}>
      {children}
    </ChatWindowContext.Provider>
  );
}

export function useChatWindow() {
  const context = useContext(ChatWindowContext);
  if (!context) {
    throw new Error('useChatWindow must be used within ChatWindowProvider');
  }
  return context;
}
