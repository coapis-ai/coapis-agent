/**
 * SSO 弹窗登录工具（模型A）。
 *
 * 为什么用"真浏览器弹窗"而不是 iframe：
 *   绝大多数外部登录页带 X-Frame-Options: DENY 或 CSP frame-ancestors，
 *   会拒绝在 iframe 里加载——真 OA 基本全挂。window.open 弹窗不受此限制，
 *   是"登录用第三方"的标准做法（类似 Google 登录弹窗）。
 *
 * 流程：
 *   主窗口（登录页） window.open 外部系统登录页（弹窗）。
 *   用户在弹窗里完成外部系统登录 → 外部系统 302 回本应用 /login/callback
 *   （此时 callback 页运行在**弹窗**内）。落地页检测到自己在弹窗里
 *   （window.opener 存在），调用 {@link reportSsoResult} 把结果：
 *     1) 写入 localStorage（同源共享，最可靠的兜底通道）
 *     2) postMessage 发给 opener（实时加速通道）
 *   主窗口同时监听这两条通道，任一到达即完成登录、关弹窗、跳主界面。
 *
 * 容错（全部覆盖）：
 *   - 弹窗被浏览器拦截（window.open 返回 null）→ code "blocked"
 *   - 用户登录前关闭弹窗（popup.closed）        → code "cancelled"
 *   - 超时（默认 120s，外部不回调/用户卡住）     → code "timeout"
 *   - 落地页验签失败/未绑定（真实错误）           → code "failed" + error
 */

/** 落地页写入、主窗口消费的同源结果 key（localStorage 兜底通道） */
export const SSO_RESULT_KEY = "coapis_sso_result";
/** 落地页 → 主窗口 的 postMessage 消息类型 */
export const SSO_MSG_TYPE = "coapis_sso_result";
/** 等待外部系统回调的默认超时（毫秒） */
export const SSO_POPUP_TIMEOUT_MS = 120_000;
/** 主窗口轮询 localStorage / popup.closed 的间隔（毫秒） */
const POLL_INTERVAL_MS = 500;
/** 简洁登录弹窗尺寸 */
const POPUP_W = 480;
const POPUP_H = 700;

export type SsoPopupErrorCode = "blocked" | "cancelled" | "timeout" | "failed";

export type SsoPopupResult =
  | { ok: true; payload: any }
  | { ok: false; code: SsoPopupErrorCode; error?: string };

/**
 * 落地页（运行在弹窗内）调用：把登录结果送回主窗口。
 * 双通道：localStorage（兜底，同源共享）+ postMessage（实时，校验 origin）。
 * 即便外部系统登录过程中的某次跳转丢了 window.opener，localStorage 也能兜住。
 */
export function reportSsoResult(result: any): void {
  try {
    localStorage.setItem(SSO_RESULT_KEY, JSON.stringify(result));
  } catch {
    /* 忽略（隐私模式下 localStorage 可能不可用） */
  }
  try {
    if (window.opener && typeof window.opener.postMessage === "function") {
      window.opener.postMessage(
        { type: SSO_MSG_TYPE, result },
        window.location.origin,
      );
    }
  } catch {
    /* 忽略 */
  }
}

/** 读取并消费 localStorage 兜底结果（落地页写入的）。 */
function readLocalResult(): any | null {
  try {
    const raw = localStorage.getItem(SSO_RESULT_KEY);
    if (!raw) return null;
    localStorage.removeItem(SSO_RESULT_KEY); // 一次性消费，避免陈旧结果
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

/** 把落地页发回的任意对象规范化为 SsoPopupResult。 */
function normalize(raw: any): SsoPopupResult {
  if (!raw || typeof raw !== "object") {
    return { ok: false, code: "failed", error: "invalid sso result" };
  }
  if (raw.ok && raw.payload) {
    return { ok: true, payload: raw.payload };
  }
  return { ok: false, code: raw.code || "failed", error: raw.error };
}

export interface SsoPopupOptions {
  /** 等待外部系统回调的超时（毫秒），默认 {@link SSO_POPUP_TIMEOUT_MS} */
  timeoutMs?: number;
}

/**
 * 打开 SSO 登录弹窗并等待结果。
 *
 * @param loginUrl 外部系统登录页 URL（由 /external/login-state 签发，
 *                 其 redirect 已渲染为本应用 /login/callback 的绝对地址）。
 */
export function openSsoPopup(
  loginUrl: string,
  opts: SsoPopupOptions = {},
): Promise<SsoPopupResult> {
  const timeoutMs = opts.timeoutMs ?? SSO_POPUP_TIMEOUT_MS;

  return new Promise<SsoPopupResult>((resolve) => {
    // 开弹窗。刻意**不**加 noopener：需要保留 window.opener 让落地页能
    // postMessage 回来。落地页是同源的 /login/callback（可信）；主窗口只
    // 接受 event.origin === 本站 的消息，外部站点即便能 post 也无效。
    let popup: Window | null = null;
    try {
      const left = Math.max(0, Math.round((window.screen.width - POPUP_W) / 2));
      const top = Math.max(0, Math.round((window.screen.height - POPUP_H) / 2));
      const features = `popup=yes,width=${POPUP_W},height=${POPUP_H},left=${left},top=${top}`;
      popup = window.open(loginUrl, "coapis_sso_login", features);
    } catch {
      popup = null;
    }

    // 被浏览器拦截 → 立即失败（不留死局）
    if (popup === null) {
      resolve({ ok: false, code: "blocked" });
      return;
    }

    let settled = false;
    let pollTimer: number | null = null;
    let timeoutTimer: number | null = null;

    const finish = (result: SsoPopupResult) => {
      if (settled) return;
      settled = true;
      window.removeEventListener("message", onMessage);
      if (pollTimer) window.clearInterval(pollTimer);
      if (timeoutTimer) window.clearTimeout(timeoutTimer);
      try {
        if (popup && !popup.closed) popup.close();
      } catch {
        /* 忽略跨域 close 失败 */
      }
      resolve(result);
    };

    // 通道1：postMessage（实时加速）。只认本站 origin，防外部站点伪造。
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin) return;
      if (!event.data || event.data.type !== SSO_MSG_TYPE) return;
      finish(normalize(event.data.result));
    };
    window.addEventListener("message", onMessage);

    // 通道2：localStorage 兜底（同源共享；opener 丢失也能兜住）。
    // 同时在这里检测"用户登录前关弹窗"→ 取消。
    pollTimer = window.setInterval(() => {
      if (popup && popup.closed) {
        const local = readLocalResult();
        if (local) finish(normalize(local));
        else finish({ ok: false, code: "cancelled" });
        return;
      }
      const local = readLocalResult();
      if (local) finish(normalize(local));
    }, POLL_INTERVAL_MS);

    // 超时：外部系统不回调 / 用户卡住 → 提示可改用直登。
    timeoutTimer = window.setTimeout(() => {
      finish({ ok: false, code: "timeout" });
    }, timeoutMs);
  });
}
