/**
 * Enterprise Edition Frontend Entry Point
 * 
 * Based on community edition, loaded with enterprise plugins.
 */

import { createRoot } from "react-dom/client";
import App from "./App.tsx";
import "./i18n";
import { installHostExternals } from "./plugins/hostExternals";
import { registerHostModulesEager } from "./plugins/dynamicModuleRegistry";
import { initLanguages } from "./utils/preloadLanguages";

// Expose host dependencies (React, antd, etc.) on window
installHostExternals();

// Dynamic module registration - discovers all modules in src/pages at build time
registerHostModulesEager();

// Preload syntax highlighter languages for @ant-design/x CodeHighlighter
initLanguages();

/**
 * Enterprise plugin definition — uses PluginRouteDeclaration format:
 * { path, component: ComponentType, label, icon?, priority? }
 */
const enterprisePlugin = {
  id: 'enterprise',
  name: 'CoApis Enterprise',
  version: '1.0.0',

  routes: [
    // ✅ PluginRouteDeclaration format (NOT React Router RouteObject!)
    {
      path: '/ent/knowledge-bases',
      component: () => import("@enterprise/pages/KnowledgeBaseList/index").then(m => m.default),
      label: '知识库列表 📚',
      icon: '📚',
      priority: 10,
    },
    {
      path: '/ent/knowledge-bases/create',
      component: () => import("@enterprise/pages/KnowledgeBaseCreate/index").then(m => m.default),
      label: '创建知识库 ✏️',
      icon: '+',
      priority: 10, // Same level as list page — appears in same menu group
    },
  ],

  menuItems: [
    { key: '/ent/knowledge-bases', path: '/ent/knowledge-bases' as any } as any,
  ],
};

// Register enterprise plugin routes with the host's PluginSystem singleton
import type { PluginRouteDeclaration } from "./plugins/hostExternals";

const registerEnterpriseRoutes = () => {
  if (typeof window !== 'undefined' && typeof window.CoApis?.registerRoutes === 'function') {
    // Use dynamic import to avoid tree-shaking and ensure components are loaded at runtime
    Promise.all(enterprisePlugin.routes.map((route: PluginRouteDeclaration) => 
      route.component() as any
    )).then(components => {
      const registered = enterprisePlugin.routes.map((r, i) => ({
        ...r,
        component: (components[i] || r.component), // fallback to original if dynamic import failed
      }));

      window.CoApis.registerRoutes('enterprise', registered);
      console.log('[Enterprise Plugin] ✅ Registered routes:', registered.length);
    }).catch(err => {
      console.error('[Enterprise Plugin] ❌ Failed to register routes:', err);
    });
  } else {
    console.warn('[Enterprise Plugin] ⚠️ window.CoApis.registerRoutes not available');
  }
};

// Register plugin after host externals are installed (after App mounts)
registerHostModulesEager(); // ensures sidebar is ready to render routes
setTimeout(() => registerEnterpriseRoutes(), 50);

if (typeof window !== "undefined") {
  const originalError = console.error;
  const originalWarn = console.warn;

  console.error = function (...args: unknown[]) {
    const msg = args[0]?.toString() || "";
    if (!msg.includes(":first-child") && !msg.includes("pseudo class")) {
      return originalError.apply(console, args as []); // only show non-antd warnings
    }
  };

  console.warn = function (...args: unknown[]) {
    const msg = args[0]?.toString() || "";
    if (!msg.includes(":first-child") && !msg.includes("pseudo class")) {
      return originalWarn.apply(console, args as []); // only show non-antd warnings
    }
  };
}

createRoot(document.getElementById("root")!).render(<App />);
