import { useState, useEffect } from "react";

const MOBILE_BREAKPOINT = 768;

/**
 * Detect whether the current viewport is mobile-sized (≤768px).
 * Uses matchMedia for efficient, event-based detection — no UA sniffing.
 */
export default function useIsMobile(
  breakpoint: number = MOBILE_BREAKPOINT,
): boolean {
  const [isMobile, setIsMobile] = useState(() =>
    typeof window !== "undefined"
      ? window.innerWidth <= breakpoint
      : false,
  );

  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${breakpoint}px)`);
    // Set initial value in case it changed between SSR and hydration
    setIsMobile(mq.matches);

    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [breakpoint]);

  return isMobile;
}
