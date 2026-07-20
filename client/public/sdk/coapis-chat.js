/**
 * CoApis Chat SDK - 嵌入式聊天 JavaScript SDK
 * 
 * 用于外部系统嵌入 CoApis 聊天功能
 * 
 * 功能：
 * - 创建浮动聊天窗口
 * - postMessage 通信
 * - 场景代入
 * - 事件回调
 * 
 * 使用示例：
 * ```javascript
 * const chat = CoApisChat.init({
 *   baseUrl: 'https://coapis.example.com',
 *   token: 'your-auth-token',
 *   sceneId: 'meeting-minutes', // 可选
 *   container: document.getElementById('chat-container'), // 可选
 *   onMessage: (msg) => console.log('AI 回复:', msg),
 *   onError: (err) => console.error('错误:', err),
 * });
 * 
 * // 发送消息
 * chat.sendMessage('你好');
 * 
 * // 关闭
 * chat.close();
 * ```
 */

interface CoApisChatConfig {
  baseUrl: string;           // CoApis 服务地址
  token: string;             // 认证令牌
  sceneId?: string;          // 场景 ID（可选）
  sceneName?: string;        // 场景名称（可选）
  container?: HTMLElement;   // 容器元素（不传则创建浮动窗口）
  width?: number | string;   // 宽度（默认 700px）
  height?: number | string;  // 高度（默认 500px）
  position?: {               // 浮动窗口位置（仅当无 container 时）
    x?: number;
    y?: number;
  };
  draggable?: boolean;       // 是否可拖拽（默认 true）
  resizable?: boolean;       // 是否可缩放（默认 true）
  theme?: 'light' | 'dark';  // 主题（默认 light）
  onReady?: () => void;      // 就绪回调
  onMessage?: (message: string) => void;    // 收到消息回调
  onMessageSent?: (message: string) => void; // 消息已发送回调
  onError?: (error: string) => void;        // 错误回调
  onClose?: () => void;      // 关闭回调
}

interface CoApisChatInstance {
  sendMessage: (message: string) => void;
  getState: () => void;
  close: () => void;
  destroy: () => void;
}

class CoApisChatSDK {
  private config: CoApisChatConfig;
  private iframe: HTMLIFrameElement | null = null;
  private container: HTMLElement | null = null;
  private isFloating: boolean = false;
  private isDragging: boolean = false;
  private isResizing: boolean = false;
  private dragStart: { x: number; y: number; left: number; top: number } = { x: 0, y: 0, left: 0, top: 0 };
  private resizeStart: { x: number; y: number; width: number; height: number } = { x: 0, y: 0, width: 0, height: 0 };

  constructor(config: CoApisChatConfig) {
    this.config = {
      width: 700,
      height: 500,
      draggable: true,
      resizable: true,
      theme: 'light',
      ...config,
    };
    
    this.init();
  }

  private init(): void {
    // 构建 iframe URL
    const url = this.buildUrl();
    
    if (this.config.container) {
      // 嵌入指定容器
      this.embedInContainer(url);
    } else {
      // 创建浮动窗口
      this.createFloatingWindow(url);
    }

    // 监听 postMessage
    window.addEventListener('message', this.handleMessage);
  }

  private buildUrl(): string {
    const { baseUrl, token, sceneId, sceneName } = this.config;
    const url = new URL('/chat/embedded', baseUrl);
    url.searchParams.set('token', token);
    if (sceneId) url.searchParams.set('scene_id', sceneId);
    if (sceneName) url.searchParams.set('scene_name', sceneName);
    return url.toString();
  }

  private embedInContainer(url: string): void {
    const { container, width, height } = this.config;
    
    if (!container) return;

    // 创建 iframe
    this.iframe = document.createElement('iframe');
    this.iframe.src = url;
    this.iframe.style.width = typeof width === 'number' ? `${width}px` : width;
    this.iframe.style.height = typeof height === 'number' ? `${height}px` : height;
    this.iframe.style.border = 'none';
    this.iframe.style.borderRadius = '8px';
    this.iframe.style.overflow = 'hidden';

    // 清空容器并插入 iframe
    container.innerHTML = '';
    container.appendChild(this.iframe);
    
    this.container = container;
  }

  private createFloatingWindow(url: string): void {
    const { width, height, position, theme } = this.config;
    
    // 创建浮动容器
    this.container = document.createElement('div');
    this.container.id = 'coapis-chat-floating';
    this.container.style.cssText = `
      position: fixed;
      left: ${position?.x || 100}px;
      top: ${position?.y || 100}px;
      width: ${typeof width === 'number' ? `${width}px` : width};
      height: ${typeof height === 'number' ? `${height}px` : height};
      z-index: 9999;
      background: ${theme === 'dark' ? '#1f1f1f' : '#fff'};
      border-radius: 8px;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
      overflow: hidden;
    `;

    // 创建标题栏（可拖拽）
    const header = document.createElement('div');
    header.id = 'coapis-chat-header';
    header.style.cssText = `
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 12px 16px;
      background: ${theme === 'dark' ? '#141414' : '#fafafa'};
      border-bottom: 1px solid ${theme === 'dark' ? '#303030' : '#f0f0f0'};
      cursor: move;
      user-select: none;
    `;
    header.innerHTML = `
      <span style="font-weight: 600; color: ${theme === 'dark' ? '#fff' : '#262626'};">
        ${this.config.sceneName || 'AI 助手'}
      </span>
      <button id="coapis-close-btn" style="
        background: none;
        border: none;
        font-size: 16px;
        cursor: pointer;
        color: ${theme === 'dark' ? '#a6a6a6' : '#595959'};
      ">✕</button>
    `;

    // 创建 iframe
    this.iframe = document.createElement('iframe');
    this.iframe.src = url;
    this.iframe.style.cssText = `
      width: 100%;
      height: calc(100% - 48px);
      border: none;
    `;

    // 创建缩放手柄
    const resizeHandle = document.createElement('div');
    resizeHandle.id = 'coapis-resize-handle';
    resizeHandle.style.cssText = `
      position: absolute;
      right: 0;
      bottom: 0;
      width: 16px;
      height: 16px;
      cursor: nwse-resize;
    `;
    resizeHandle.innerHTML = `
      <div style="
        position: absolute;
        right: 4px;
        bottom: 4px;
        width: 8px;
        height: 8px;
        border-right: 2px solid ${theme === 'dark' ? '#595959' : '#bfbfbf'};
        border-bottom: 2px solid ${theme === 'dark' ? '#595959' : '#bfbfbf'};
      "></div>
    `;

    // 组装
    this.container.appendChild(header);
    this.container.appendChild(this.iframe);
    this.container.appendChild(resizeHandle);
    document.body.appendChild(this.container);

    this.isFloating = true;

    // 绑定事件
    this.bindFloatingEvents(header, resizeHandle);
  }

  private bindFloatingEvents(header: HTMLElement, resizeHandle: HTMLElement): void {
    const { draggable, resizable } = this.config;

    // 拖拽
    if (draggable) {
      header.addEventListener('mousedown', this.handleDragStart);
    }

    // 缩放
    if (resizable) {
      resizeHandle.addEventListener('mousedown', this.handleResizeStart);
    }

    // 关闭按钮
    const closeBtn = document.getElementById('coapis-close-btn');
    closeBtn?.addEventListener('click', () => {
      this.close();
    });
  }

  private handleDragStart = (e: MouseEvent): void => {
    if (!this.container || !this.isFloating) return;
    
    this.isDragging = true;
    const rect = this.container.getBoundingClientRect();
    this.dragStart = {
      x: e.clientX,
      y: e.clientY,
      left: rect.left,
      top: rect.top,
    };

    document.addEventListener('mousemove', this.handleDragMove);
    document.addEventListener('mouseup', this.handleDragEnd);
  };

  private handleDragMove = (e: MouseEvent): void => {
    if (!this.isDragging || !this.container) return;

    const deltaX = e.clientX - this.dragStart.x;
    const deltaY = e.clientY - this.dragStart.y;

    const newLeft = Math.max(0, Math.min(window.innerWidth - this.container.offsetWidth, this.dragStart.left + deltaX));
    const newTop = Math.max(0, Math.min(window.innerHeight - this.container.offsetHeight, this.dragStart.top + deltaY));

    this.container.style.left = `${newLeft}px`;
    this.container.style.top = `${newTop}px`;
  };

  private handleDragEnd = (): void => {
    this.isDragging = false;
    document.removeEventListener('mousemove', this.handleDragMove);
    document.removeEventListener('mouseup', this.handleDragEnd);
  };

  private handleResizeStart = (e: MouseEvent): void => {
    if (!this.container || !this.isFloating) return;
    
    this.isResizing = true;
    this.resizeStart = {
      x: e.clientX,
      y: e.clientY,
      width: this.container.offsetWidth,
      height: this.container.offsetHeight,
    };

    document.addEventListener('mousemove', this.handleResizeMove);
    document.addEventListener('mouseup', this.handleResizeEnd);
  };

  private handleResizeMove = (e: MouseEvent): void => {
    if (!this.isResizing || !this.container) return;

    const deltaX = e.clientX - this.resizeStart.x;
    const deltaY = e.clientY - this.resizeStart.y;

    const newWidth = Math.max(400, this.resizeStart.width + deltaX);
    const newHeight = Math.max(300, this.resizeStart.height + deltaY);

    this.container.style.width = `${newWidth}px`;
    this.container.style.height = `${newHeight}px`;
  };

  private handleResizeEnd = (): void => {
    this.isResizing = false;
    document.removeEventListener('mousemove', this.handleResizeMove);
    document.removeEventListener('mouseup', this.handleResizeEnd);
  };

  private handleMessage = (event: MessageEvent): void => {
    // 安全检查
    if (!event.data || !event.data.type) return;
    if (this.config.baseUrl && event.origin !== new URL(this.config.baseUrl).origin) return;

    const { type, data } = event.data;

    switch (type) {
      case 'COAPIS_READY':
        this.config.onReady?.();
        break;

      case 'COAPIS_MESSAGE_RECEIVED':
        this.config.onMessage?.(data?.message || '');
        break;

      case 'COAPIS_MESSAGE_SENT':
        this.config.onMessageSent?.(data?.message || '');
        break;

      case 'COAPIS_ERROR':
        this.config.onError?.(data?.error || '未知错误');
        break;

      case 'COAPIS_CLOSE_REQUEST':
        this.close();
        break;
    }
  };

  // 公共 API

  /**
   * 发送消息
   */
  public sendMessage(message: string): void {
    if (!this.iframe?.contentWindow) return;
    
    this.iframe.contentWindow.postMessage({
      type: 'COAPIS_SEND_MESSAGE',
      payload: { message },
    }, '*');
  }

  /**
   * 获取状态
   */
  public getState(): void {
    if (!this.iframe?.contentWindow) return;
    
    this.iframe.contentWindow.postMessage({
      type: 'COAPIS_GET_STATE',
    }, '*');
  }

  /**
   * 关闭窗口
   */
  public close(): void {
    if (this.isFloating && this.container) {
      this.container.style.display = 'none';
    }
    this.config.onClose?.();
  }

  /**
   * 销毁实例
   */
  public destroy(): void {
    window.removeEventListener('message', this.handleMessage);
    
    if (this.container) {
      if (this.isFloating) {
        document.body.removeChild(this.container);
      } else {
        this.container.innerHTML = '';
      }
    }

    this.iframe = null;
    this.container = null;
  }
}

// 导出
(window as any).CoApisChat = {
  /**
   * 初始化聊天窗口
   */
  init: (config: CoApisChatConfig): CoApisChatInstance => {
    return new CoApisChatSDK(config) as unknown as CoApisChatInstance;
  },

  /**
   * 快速打开聊天窗口（浮动模式）
   */
  open: (options: {
    baseUrl: string;
    token: string;
    sceneId?: string;
    sceneName?: string;
    width?: number;
    height?: number;
    onMessage?: (msg: string) => void;
    onClose?: () => void;
  }): CoApisChatInstance => {
    return new CoApisChatSDK({
      ...options,
      container: undefined, // 浮动模式
    }) as unknown as CoApisChatInstance;
  },
};

export default CoApisChatSDK;
