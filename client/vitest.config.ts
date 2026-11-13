/// Vitest 配置 —— 前端测试底座（方案 B0 / D1：vitest + Testing Library + jsdom）
///
/// 与 vite.config.ts 的关系：构建配置**不合并**到这里。这里只跑测试，
/// 刻意保持最小：不引 proxy、不引 optimizeDeps、不引 manualChunks，
/// 免得测试环境和生产构建互相污染。别名与 CSS Modules 命名口径必须和
/// vite.config.ts 一致，否则组件里的 `@/...` 导入与 `styles.xxx` 会解析不到。
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  // 组件里 `import styles from "./x.module.css"` 在 jsdom 下取不到真实类名，
  // 这是刻意的：测试**不锁 CSS 类名**（方案 §6 的边界），锁的是行为与状态。
  css: false,
  // 与 vite.config.ts 的 define 保持一致：@agentscope-ai/chat 的入口里直接引用
  // 这些裸标识符，测试环境不给定义就会 "cannot find module/ReferenceError"，
  // 报出来的错和真实缺陷混在一起。口径必须与构建一致（构建时空串=同源）。
  define: {
    VITE_API_BASE_URL: JSON.stringify(""),
    TOKEN: JSON.stringify(""),
    MOBILE: false,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      "@enterprise": path.resolve(__dirname, "./src/enterprise"),
      "@coapis-c2a/renderer": path.resolve(
        __dirname,
        "./vendor/coapis-c2a/typescript/c2a-renderer-react/src",
      ),
      // 这两个包只写了 "module" 字段、没写 "main"/"exports"：
      // Vite 构建走 module，Node 解析（vitest 的执行侧）走 main → 解析不到入口，
      // 报 "Failed to resolve entry for package"。构建侧不用动，测试侧显式指到 lib。
      "@agentscope-ai/chat": path.resolve(
        __dirname,
        "./node_modules/@agentscope-ai/chat/lib/index.js",
      ),
      "@agentscope-ai/design": path.resolve(
        __dirname,
        "./node_modules/@agentscope-ai/design/lib/index.js",
      ),
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    exclude: [
      "**/node_modules/**",
      "**/dist/**",
      "vendor/**",
      "node_modules/**",
      // 该文件是 node:test 风格写的，vitest 收为"无测试文件"空套件会红。
      // B4/B5 把它重写为 vitest 用例后从 exclude 摘掉。
      "src/pages/Settings/Models/components/modals/testConnectionMessage.test.ts",
    ],
    // 单文件独立进程在 CI 上更容易OOM，线程池足够且更省内存
    pool: "threads",
    restoreMocks: true,
    // @agentscope-ai/* 只暴露 "module" 字段（无 main），Node 直接 require 不到；
    // 交给 Vite 变换链内联处理，与构建口径一致。
    server: {
      deps: {
        inline: [/@agentscope-ai\//, /antd/, /@ant-design\//],
      },
    },
    coverage: {
      provider: "v8",
      reporter: ["text", "html", "json-summary"],
      // 报告口径（D3）：CI 只 gate `npm run test:run`，覆盖率只出报告不卡门槛。
      // 前端的真实尺子在后端（server 的 fail_under），这里不做双重门槛自杀。
      include: ["src/pages/Chat/**", "src/locales/**", "src/utils/**"],
      exclude: ["**/*.test.ts", "**/*.test.tsx", "**/*.d.ts"],
      reportsDirectory: "./coverage",
    },
  },
});
