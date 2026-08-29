import { createRoot } from "react-dom/client";
import App from "./App.tsx";
import "./i18n";
import { installHostExternals } from "./plugins/hostExternals";
import { registerHostModulesEager } from "./plugins/dynamicModuleRegistry";
import { initLanguages } from "./utils/preloadLanguages";
import { initEnterprise } from "@enterprise/enterprise-entry";

// Expose host dependencies (React, antd, etc.) on window
// so that plugin UI modules can use them without bundling their own copies.
installHostExternals();

// Dynamic module registration - no generated files needed!
// Automatically discovers all modules in src/pages at build time
registerHostModulesEager();

// Preload syntax highlighter languages
// This fixes dynamic import failures in @ant-design/x CodeHighlighter
initLanguages();

// 注入企业版扩展（社区版为空，企业版注册路由等）
initEnterprise?.();

if (typeof window !== "undefined") {
  const originalError = console.error;
  const originalWarn = console.warn;

  console.error = function (...args: unknown[]) {
    const msg = args[0]?.toString() || "";
    if (msg.includes(":first-child") || msg.includes("pseudo class")) {
      return;
    }
    originalError.apply(console, args as []);
  };

  console.warn = function (...args: unknown[]) {
    const msg = args[0]?.toString() || "";
    if (
      msg.includes(":first-child") ||
      msg.includes("pseudo class") ||
      msg.includes("potentially unsafe")
    ) {
      return;
    }
    originalWarn.apply(console, args as []);
  };
}

createRoot(document.getElementById("root")!).render(<App />);
