// 记录最近一次访问的非聊天路由（M3/T3.1：全屏 ⇄ 浮窗双向联动，
// “关闭全屏 = 回到原页面” 需要知道原页面是哪个路由）。

let lastNonChatPath = '/workbench';

/** 由 MainLayout 在路由变化时调用：非聊天路由时记录 */
export function recordNonChatPath(pathname: string): void {
  if (!/^\/(chat)(\/|$|\?)/.test(pathname) && !/^\/$/.test(pathname)) {
    lastNonChatPath = pathname;
  }
}

/** 取最近一次非聊天路由（默认工作台） */
export function getLastNonChatPath(): string {
  return lastNonChatPath;
}
