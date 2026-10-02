/**
 * 版本探测：判断当前部署是否加载了企业插件。
 *
 * 企业插件（main.enterprise.tsx）通过 window.CoApis.registerRoutes('enterprise', ...)
 * 注册 /knowledge 等路由；pluginSystem 会把所有插件路由平铺存储，可通过
 * window.__pluginSystem.getRoutes() 读取。社区版没有这些路由，返回 false。
 */
export function isEnterpriseEdition(): boolean {
  if (typeof window === "undefined") return false;
  try {
    const ps = (window as any).__pluginSystem;
    const routes: Array<{ path?: string }> = ps?.getRoutes?.() ?? [];
    return routes.some(
      (r) => typeof r?.path === "string" && r.path.startsWith("/knowledge"),
    );
  } catch {
    return false;
  }
}
