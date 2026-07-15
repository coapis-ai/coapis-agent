import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  // Empty = same-origin; frontend and backend served together, no hardcoded host.
  // Use a dedicated Vite-prefixed key so unrelated shell BASE_URL values don't leak into the build.
  const apiBaseUrl = env.VITE_API_BASE_URL ?? "";

  return {
    envPrefix: ['VITE', 'TOKEN'],
    define: {
      VITE_API_BASE_URL: JSON.stringify(apiBaseUrl),
      TOKEN: JSON.stringify(env.TOKEN || ""),
      MOBILE: false,
    },
    plugins: [react()],
    css: {
      modules: {
        localsConvention: "camelCase",
        generateScopedName: "[name]__[local]__[hash:base64:5]",
      },
      preprocessorOptions: {
        less: {
          javascriptEnabled: true,
        },
      },
    },
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
    },
    server: {
      host: "0.0.0.0",
      port: 5173,
      proxy: {
        "/api": {
          target: env.VITE_DEV_PROXY_TARGET || "http://localhost:8000",
          changeOrigin: true,
        },
        "/config": {
          target: env.VITE_DEV_PROXY_TARGET || "http://localhost:8000",
          changeOrigin: true,
        },
        "/auth": {
          target: env.VITE_DEV_PROXY_TARGET || "http://localhost:8000",
          changeOrigin: true,
        },
        "/ws": {
          target: (env.VITE_DEV_PROXY_TARGET || "http://localhost:8000").replace("http://", "ws://"),
          ws: true,
        },
      },
    },
    optimizeDeps: {
      include: [
        "diff",
        // 代码高亮语言包（解决动态导入失败问题）
        "react-syntax-highlighter/dist/esm/languages/prism/javascript",
        "react-syntax-highlighter/dist/esm/languages/prism/typescript",
        "react-syntax-highlighter/dist/esm/languages/prism/jsx",
        "react-syntax-highlighter/dist/esm/languages/prism/tsx",
        "react-syntax-highlighter/dist/esm/languages/prism/python",
        "react-syntax-highlighter/dist/esm/languages/prism/bash",
        "react-syntax-highlighter/dist/esm/languages/prism/json",
        "react-syntax-highlighter/dist/esm/languages/prism/css",
        "react-syntax-highlighter/dist/esm/languages/prism/markdown",
        "react-syntax-highlighter/dist/esm/languages/prism/yaml",
        "react-syntax-highlighter/dist/esm/languages/prism/sql",
        "react-syntax-highlighter/dist/esm/languages/prism/java",
        "react-syntax-highlighter/dist/esm/languages/prism/c",
        "react-syntax-highlighter/dist/esm/languages/prism/cpp",
        "react-syntax-highlighter/dist/esm/languages/prism/go",
        "react-syntax-highlighter/dist/esm/languages/prism/rust",
      ],
    },
    build: {
      // Output to the console directory,
      // so we don't need to copy files manually after build.
      // outDir: path.resolve(__dirname, "../src/console"),
      // emptyOutDir: true,
      cssCodeSplit: true,
      sourcemap: mode !== "production",
      chunkSizeWarningLimit: 1000,
      rollupOptions: {
        output: {
          manualChunks(id) {
            // React core
            if (
              id.includes("node_modules/react/") ||
              id.includes("node_modules/react-dom/") ||
              id.includes("node_modules/react-router-dom/") ||
              id.includes("node_modules/scheduler/")
            ) {
              return "react-vendor";
            }
            // Ant Design core + icons + AgentScope design (merged to avoid
            // circular deps and broken module resolution across chunks)
            if (
              id.includes("node_modules/antd/") ||
              id.includes("node_modules/antd-style/") ||
              id.includes("node_modules/@ant-design/") ||
              id.includes("node_modules/@agentscope-ai/")
            ) {
              return "ui-vendor";
            }
            // i18n
            if (
              id.includes("node_modules/i18next/") ||
              id.includes("node_modules/react-i18next/")
            ) {
              return "i18n-vendor";
            }
            // Markdown rendering
            if (
              id.includes("node_modules/react-markdown/") ||
              id.includes("node_modules/remark-gfm/") ||
              id.includes("node_modules/rehype") ||
              id.includes("node_modules/remark") ||
              id.includes("node_modules/unified/") ||
              id.includes("node_modules/mdast") ||
              id.includes("node_modules/hast") ||
              id.includes("node_modules/micromark")
            ) {
              return "markdown-vendor";
            }
            // Drag and drop
            if (id.includes("node_modules/@dnd-kit/")) {
              return "dnd-vendor";
            }
            // Utilities (dayjs, zustand, ahooks, etc.)
            if (
              id.includes("node_modules/dayjs/") ||
              id.includes("node_modules/zustand/") ||
              id.includes("node_modules/ahooks/") ||
              id.includes("node_modules/@vvo/tzdb/")
            ) {
              return "utils-vendor";
            }
          },
        },
        onwarn(warning, warn) {
          // Suppress circular chunk warnings from antd-icons / ui-vendor split
          // Rollup handles circular chunks at runtime without issues
          if (warning.code === "CIRCULAR_DEPENDENCY" && warning.message?.includes("antd-icons-vendor")) return;
          warn(warning);
        },
      },
    },
  };
});
