// 聊天全局参数 —— 单一命名空间（M3/T3.2：14 → 10，过渡期兼容旧变量）
//
// 背景：嵌入式（浮窗/场景）模式需要把参数传给 Chat 页面。历史上散落成 14 个
// window.__CHAT_*__ 全局变量，其中 4 个无任何消费者（onExpand / onSessionCreated /
// onError / showToolbar），已裁撤。现收敛为单一命名空间对象 window.__COAPIS_CHAT__，
// 共 10 个字段。
//
// 过渡期兼容：setter 同时写穿（write-through）旧版 __CHAT_*__ 键，第三方/旧代码
// 仍可读取；消费方已全部迁移到 getChatGlobals()。

export interface ChatGlobals {
  mode: 'full' | 'embedded';
  sessionId?: string;
  sceneId?: string;
  sceneName?: string;
  welcomeMessage?: string;
  compact?: boolean;
  onClose?: () => void;
  onTogglePin?: () => void;
  isPinned?: boolean;
  onDragStart?: (e: unknown) => void;
}

const NS_KEY = '__COAPIS_CHAT__';

declare global {
  interface Window {
    [NS_KEY]?: Partial<ChatGlobals>;
  }
}

function win(): Window {
  return typeof window !== 'undefined' ? (window as unknown as Window) : ({} as Window);
}

/** 读取当前聊天全局参数（未设置时返回空对象） */
export function getChatGlobals(): Partial<ChatGlobals> {
  return win()[NS_KEY] ?? {};
}

/**
 * 写入聊天全局参数（部分更新）。
 * 同时写穿旧版 __CHAT_*__ 键（过渡期兼容）。
 */
export function setChatGlobals(partial: Partial<ChatGlobals>): void {
  const w = win();
  w[NS_KEY] = { ...(w[NS_KEY] ?? {}), ...partial };

  // 写穿旧变量（过渡期兼容）
  const legacyMap: Record<string, string> = {
    mode: '__CHAT_MODE__',
    sessionId: '__CHAT_SESSION_ID__',
    sceneId: '__CHAT_SCENE_ID__',
    sceneName: '__CHAT_SCENE_NAME__',
    welcomeMessage: '__CHAT_WELCOME_MESSAGE__',
    compact: '__CHAT_COMPACT__',
    onClose: '__CHAT_ON_CLOSE__',
    onTogglePin: '__CHAT_ON_TOGGLE_PIN__',
    isPinned: '__CHAT_IS_PINNED__',
    onDragStart: '__CHAT_ON_DRAG_START__',
  };
  Object.entries(legacyMap).forEach(([field, legacyKey]) => {
    if (field in partial) {
      (w as unknown as Record<string, unknown>)[legacyKey] =
        partial[field as keyof ChatGlobals];
    }
  });
}

/**
 * 清理聊天全局参数（完整模式 / 组件卸载时调用）。
 * 同时删除旧版 __CHAT_*__ 键。
 */
export function clearChatGlobals(): void {
  const w = win();
  delete w[NS_KEY];
  [
    '__CHAT_MODE__',
    '__CHAT_SESSION_ID__',
    '__CHAT_SCENE_ID__',
    '__CHAT_SCENE_NAME__',
    '__CHAT_WELCOME_MESSAGE__',
    '__CHAT_SHOW_TOOLBAR__',
    '__CHAT_COMPACT__',
    '__CHAT_ON_CLOSE__',
    '__CHAT_ON_EXPAND__',
    '__CHAT_ON_TOGGLE_PIN__',
    '__CHAT_IS_PINNED__',
    '__CHAT_ON_DRAG_START__',
    '__CHAT_ON_SESSION_CREATED__',
    '__CHAT_ON_ERROR__',
  ].forEach((k) => {
    delete (w as unknown as Record<string, unknown>)[k];
  });
}
