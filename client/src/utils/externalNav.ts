/**
 * externalNav.ts — 外部系统导航（出站身份断言 / outbound identity）
 *
 * 浏览器顶层导航无法携带自定义请求头（安全模型硬约束），因此访问已配置的外部
 * 系统时，身份断言通过 URL 签名参数承载：?caid=<username>&cas=<ts>.<sig>。
 *
 * 打开外部 URL 前先调用后端 signed-url 端点取得签名 URL：
 *   - 非外部系统 URL          → 后端原样返回，直接打开
 *   - 外部系统 + 已绑定账号   → 返回带签名参数的 URL，直接打开
 *   - 外部系统 + 未绑定账号   → 403，提示用户先完成绑定（不打开）
 *
 * 该函数作为 C2ARenderer 的导航拦截器（setUrlNavigate）被注入，覆盖行链接 /
 * 按钮 / 快捷建议等所有外部导航。
 */
import { getApiUrl, getApiToken } from "@/api/config";
import { message } from "antd";
import i18n from "@/i18n";

export interface NavigateOptions {
  openInNewTab?: boolean;
  fallbackAction?: () => void;
}

/** 直接打开（兜底路径：未绑定拦截 / 后端不可用 / 网络异常）。 */
function openDirectly(targetUrl: string, options?: NavigateOptions): void {
  if (options?.openInNewTab) {
    window.open(targetUrl, "_blank", "noopener,noreferrer");
  } else {
    window.location.href = targetUrl;
  }
}

/**
 * 打开外部 URL：先向后端换取签名 URL，再导航。
 * 供 C2ARenderer 的 setUrlNavigate 注入使用。
 */
export async function openExternalUrl(
  targetUrl: string,
  options?: NavigateOptions,
): Promise<void> {
  const token = getApiToken();

  try {
    const url = `${getApiUrl("/auth/external/signed-url")}?target_url=${encodeURIComponent(targetUrl)}`;
    const res = await fetch(url, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });

    // 403 — 外部系统 + 未绑定账号（安全默认：拒绝 + 明确提示）
    if (res.status === 403) {
      const err = await res.json().catch(() => ({}));
      const detail = (err as Record<string, unknown>)?.detail;
      const text = typeof detail === "string" && detail ? detail : undefined;
      message.warning(
        i18n.t("externalNav.bindingRequired", {
          defaultValue: text || "您尚未绑定该外部系统账号，暂无法访问，请先完成账号绑定。",
        }),
      );
      return;
    }

    // 401 — 未登录：兜底直接打开（不阻断，交由目标系统自行鉴权）
    // 5xx — 后端异常：兜底直接打开，避免导航被完全卡死
    if (!res.ok) {
      openDirectly(targetUrl, options);
      options?.fallbackAction?.();
      return;
    }

    const data = (await res.json()) as { data?: { url?: string } };
    const signedUrl = data?.data?.url || targetUrl;
    openDirectly(signedUrl, options);
  } catch {
    // 网络异常 / 解析失败 — 兜底直接打开
    openDirectly(targetUrl, options);
    options?.fallbackAction?.();
  }
}
