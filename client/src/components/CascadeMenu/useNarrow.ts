import { useEffect, useState } from "react";

/**
 * 窄屏判定（D11）——级联列在窄屏退化为单列下钻。
 *
 * 只在真实浏览器里读 `window.innerWidth`，随 resize 更新。SSR/测试环境无
 * window 时返回 false（桌面态），不会崩。
 */
export function useNarrow(breakpoint = 768): boolean {
  const [narrow, setNarrow] = useState(
    () => typeof window !== "undefined" && window.innerWidth < breakpoint,
  );

  useEffect(() => {
    if (typeof window === "undefined") return;
    const onResize = () => setNarrow(window.innerWidth < breakpoint);
    onResize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [breakpoint]);

  return narrow;
}
