/**
 * 显示设置弹层的事件总线（M4/B3：显示设置入口移入个人下拉）。
 * ProfileButton（全局头部）发出请求；Chat 页监听并在本页打开 ChatDisplaySettings。
 * 若用户不在聊天页，先标记 pending，Chat 页挂载时消费。
 */
export const OPEN_DISPLAY_SETTINGS_EVENT = "coapis:open-display-settings";
const PENDING_FLAG = "coapis.pending-open-display-settings";

export function requestOpenDisplaySettings() {
  try {
    sessionStorage.setItem(PENDING_FLAG, "1");
  } catch {
    /* ignore */
  }
  window.dispatchEvent(new CustomEvent(OPEN_DISPLAY_SETTINGS_EVENT));
}

export function consumePendingDisplaySettings(): boolean {
  try {
    if (sessionStorage.getItem(PENDING_FLAG) === "1") {
      sessionStorage.removeItem(PENDING_FLAG);
      return true;
    }
  } catch {
    /* ignore */
  }
  return false;
}
