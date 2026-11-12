import { useEffect } from 'react';
import i18n from '@/i18n';

/**
 * 厂商写死英文标题的显示层补丁（2026-11-12）。
 *
 * 厂商思考卡片的标题是编译进包里写死的（@agentscope-ai/chat/lib/.../Response/Reasoning.js
 * 里 title="Thinking"），options 没有注入口——但它只是**显示文字**，不值得为它动依赖
 * （不引 patch-package、不改 node_modules）。这里把当前语言的文案写成 CSS 变量，
 * 由 index.module.less 在显示层替换；语言切换时同步更新，切语言立刻跟着变。
 *
 * CSS 选择器命中不到时（老浏览器不支持 :has()）退回厂商原文，功能不受影响。
 */
const CSS_VAR_KEYS: Array<{ key: string; labelKey: string; fallback: string }> = [
  { key: '--coapis-thinking-label', labelKey: 'chat.deepThinking', fallback: 'Thinking' },
];

/** 被 CSS 隐藏原文的那批标题节点（配合 index.module.less 的选择器） */
const TITLE_SELECTOR =
  '.coapis-operate-card:has([class*="spark-memory-line"]) .coapis-operate-card-header-title,' +
  '.coapis-operate-card:has([class*="spark-loading-line"]) .coapis-operate-card-header-title';

export function useVendorLabels(): void {
  useEffect(() => {
    const sync = () => {
      const root = document.documentElement;
      let label = i18n.t(CSS_VAR_KEYS[0].labelKey);
      for (const { key, labelKey, fallback } of CSS_VAR_KEYS) {
        const text = i18n.t(labelKey);
        label = text && text !== labelKey ? text : fallback;
        root.style.setProperty(key, JSON.stringify(label));
      }
      // 无障碍：原文只是视觉上看不到，DOM 里还在，读屏软件会读到英文 "Thinking"。
      // 给这些节点补 aria-label，让辅助技术读到的和眼睛看到的一致。
      document.querySelectorAll(TITLE_SELECTOR).forEach((el) => {
        el.setAttribute('aria-label', label);
      });
    };

    // 卡片是流式渲染出来的，语言切换时不一定重渲染 → 用 MutationObserver 补挂。
    // 流式输出时 DOM 每秒变化几十次，sync 要节流：同一帧内只做一次。
    let queued = false;
    const queueSync = () => {
      if (queued) return;
      queued = true;
      requestAnimationFrame(() => {
        queued = false;
        sync();
      });
    };

    sync();
    i18n.on('languageChanged', sync);
    const observer = new MutationObserver(queueSync);
    observer.observe(document.body, { childList: true, subtree: true });
    return () => {
      i18n.off('languageChanged', sync);
      observer.disconnect();
    };
  }, []);
}
