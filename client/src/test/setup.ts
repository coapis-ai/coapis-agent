/**
 * Vitest 全局 setup —— jsdom 环境补齐
 * ---------------------------------------------------------------------------
 * jsdom 不提供 antd / @agentscope-ai 组件在浏览器里依赖的那几样东西
 * （matchMedia、ResizeObserver、IntersectionObserver、scrollIntoView），
 * 缺一个就会让组件在测试里抛 TypeError，报出来的错和真实缺陷混在一起，
 * 读测试的人分不清"是组件坏了"还是"环境没补齐"。这里一次性补齐。
 */
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
// 组件里到处是 useTranslation()，i18n 未初始化时 react-i18next 只会警告并把
// key 原样吐回来 —— 测试断言会对着 "chat.resources.produced" 这种字面量通过，
// 等于什么都没测。这里加载真实的四语言资源，并把基准语言钉成 zh（产品默认）。
import i18n from "../i18n";

void i18n.changeLanguage("zh");

// ---------------------------------------------------------------------------
// matchMedia —— antd 的响应式断点、ThemeContext 都吃它
// ---------------------------------------------------------------------------
if (typeof window !== "undefined" && !window.matchMedia) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
}

// ---------------------------------------------------------------------------
// ResizeObserver / IntersectionObserver —— antd Table、Collapse 动画会用到
// ---------------------------------------------------------------------------
class NObs {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
if (typeof window !== "undefined") {
  if (!("ResizeObserver" in window)) {
    (window as unknown as Record<string, unknown>).ResizeObserver = NObs;
  }
  if (!("IntersectionObserver" in window)) {
    (window as unknown as Record<string, unknown>).IntersectionObserver =
      class extends NObs {};
  }
  // jsdom 不实现 scrollIntoView；聊天页的定位逻辑会调它
  Element.prototype.scrollIntoView = vi.fn();
}

afterEach(() => {
  cleanup();
});
