/**
 * 版本更新通知的浏览器侧状态（单一实现）
 *
 * 为什么 localStorage 而不是后端用户偏好：
 * 「更新」的作用对象是**这台浏览器所安装的本地包**（升级/重启在部署端完成），
 * 与跨设备的用户账号无关——「这个浏览器见过 v1.2.28」天然是浏览器级状态。
 * 后端只负责回答「有无最新版」（/api/updates），已读/免打扰留在本地。
 */

const SEEN_KEY = "coapis_update_seen_version";
const SILENCE_KEY = "coapis_update_silence_until";
const ENABLED_KEY = "coapis_update_notice_enabled";

/** 更新弹窗是否开启（默认开） */
export function isNoticeEnabled(): boolean {
  return localStorage.getItem(ENABLED_KEY) !== "0";
}

export function setNoticeEnabled(on: boolean): void {
  localStorage.setItem(ENABLED_KEY, on ? "1" : "0");
}

/** 已经弹过的最新版本号（每个版本只自动弹一次） */
export function getSeenVersion(): string {
  return localStorage.getItem(SEEN_KEY) ?? "";
}

export function markSeenVersion(version: string): void {
  localStorage.setItem(SEEN_KEY, version);
}

/** 免打扰截止时间戳（毫秒）；0 = 未设置 */
export function getSilenceUntil(): number {
  return Number(localStorage.getItem(SILENCE_KEY) ?? 0) || 0;
}

export function silenceFor(ms: number): number {
  const until = Date.now() + ms;
  localStorage.setItem(SILENCE_KEY, String(until));
  return until;
}

export function clearSilence(): void {
  localStorage.removeItem(SILENCE_KEY);
}

export function isSilenced(now = Date.now()): boolean {
  return getSilenceUntil() > now;
}
