/**
 * 右侧栏「资源条」（v17 · F4，小蜜蜂 2026-11-05）。
 *
 * 需求原话：在会话窗口右侧加一列 200px 宽度 —— 上半部分表示**当前会话**的
 * 内容，下面部分表示**当前聊天**；点条目直接预览；点「查看全部」打开 L3
 * 抽屉。上半区因此走台账的 `scope=session`（跨聊天），下半区走 `scope=chat`。
 *
 * 口径：
 *  - 数据只有一个来源：共享台账缓存（useScopedResources），本组件不自己发请求。
 *  - 排序与列表同尺：按更新时间倒序（`updated_at`），显示的时间就是排序的
 *    时间 —— 两把尺子（显示 created/排序 updated）的老毛病不再复发。
 *  - 标题保留扩展名（`splitFileName`），不再出现"名字没了后缀"。
 *  - 无 chatId → 整块不渲染（不留空骨架占位）。
 *  - 预览统一走聊天页的预览抽屉（`onPreview`），不用 window.open。
 */
import { memo, useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ChatResourceItem } from "../../../api/modules/chat";
import { downloadFile } from "../../../utils/webPreview";
import {
  formatResSize,
  formatResTime,
  splitFileName,
  toEpochMs,
} from "./ChatSessionResources/resourceFormat";
import { useScopedResources, type ResourceStripScope } from "./useScopedResources";
import styles from "./CoApisResourceStrip.module.less";

export type { ResourceStripScope };

export interface ResourcePreviewTarget {
  path: string;
  name: string;
  kind?: string;
  source?: string;
}

export interface CoApisResourceStripProps {
  /** chat=当前聊天；session=当前会话（跨聊天） */
  scope: ResourceStripScope;
  chatId: string | undefined;
  /** 条内最多显示几条（默认 6，其余走「查看全部」） */
  maxItems?: number;
  /** 无资源时是否显示占位（默认显示一行空态；左栏可传 false 保持安静） */
  showEmpty?: boolean;
  /** 预览（聊天页抽屉） */
  onPreview: (target: ResourcePreviewTarget) => void;
  /** 「查看全部」→ 打开 L3 抽屉 */
  onOpenAll?: () => void;
  /** 外部刷新信号（自增即强制刷新） */
  refreshSignal?: number;
  className?: string;
}

/** 排序尺子：更新时间倒序；同值再按引用强度倒序，保证顺序稳定不跳。 */
export function sortResourcesByUpdated(rows: ChatResourceItem[]): ChatResourceItem[] {
  return [...rows].sort((a, b) => {
    // 台账时间字段可空（历史行），缺时刻的行沉到最底，不参与"谁更新"之争
    const au = (toEpochMs(b.updated_at) ?? 0) - (toEpochMs(a.updated_at) ?? 0);
    if (au !== 0) return au;
    return (b.ref_count ?? 0) - (a.ref_count ?? 0);
  });
}

/** 台账里的文件名（去掉目录，保留扩展名）。 */
export function resourceFileName(path: string): string {
  const p = String(path ?? "");
  const slash = p.lastIndexOf("/");
  const backslash = p.lastIndexOf("\\");
  const i = Math.max(slash, backslash);
  return i >= 0 ? p.slice(i + 1) : p;
}

/**
 * 显示名：台账给的 title 优先，其次文件名。
 *
 * v17 · F4（小蜜蜂第 4 条「标题不规范」）：**扩展名永远保留** —— 之前用
 * `splitFileName(stem)` 只取主干，xlsx/doc 这类文件在列表里看不出是什么，
 * 用户认不出自己刚生成的那张表。
 */
export function formatResourceTitle(item: ChatResourceItem): string {
  const raw = String(item.title || "").trim();
  // title 有时被写成整条路径：取它的文件名，别把目录当标题
  const base = raw ? resourceFileName(raw) : resourceFileName(item.path);
  return base || item.path;
}

type Translate = (key: string, defaultValue: string, options?: Record<string, unknown>) => string;

function kindLabel(kind: string | undefined, t: Translate): string {
  switch (kind) {
    case "file":
      return t("chat:resources.kindFile", "文件");
    case "web":
      return t("chat:resources.kindWeb", "网页");
    case "kb":
      return t("chat:resources.kindKb", "知识库");
    case "mcp":
      return t("chat:resources.kindMcp", "MCP");
    case "db":
      return t("chat:resources.kindDb", "数据库");
    default:
      return kind || "";
  }
}

function CoApisResourceStripBase({
  scope,
  chatId,
  maxItems = 6,
  showEmpty = true,
  onPreview,
  onOpenAll,
  refreshSignal = 0,
  className,
}: CoApisResourceStripProps) {
  const { t } = useTranslation();
  const { items, total, loading } = useScopedResources(chatId, scope, refreshSignal);
  const [expanded, setExpanded] = useState(false);

  // 会话切换时收起"展开更多"，避免新会话沿用旧的展开态
  useEffect(() => setExpanded(false), [chatId, scope]);

  const sorted = useMemo(() => sortResourcesByUpdated(items), [items]);
  const shown = useMemo(
    () => (expanded ? sorted : sorted.slice(0, maxItems)),
    [expanded, sorted, maxItems],
  );

  const groupTitle =
    scope === "session"
      ? t("chat:resources.groupSession", "当前会话")
      : t("chat:resources.groupChat", "当前聊天");

  const handlePick = useCallback(
    (item: ChatResourceItem) => {
      onPreview({
        path: item.path,
        name: formatResourceTitle(item),
        kind: item.kind,
        source: scope,
      });
    },
    [onPreview, scope],
  );

  const handleDownload = useCallback((item: ChatResourceItem) => {
    void downloadFile(item.path, formatResourceTitle(item));
  }, []);

  const lastTs = useMemo(() => {
    const ms = toEpochMs(sorted[0]?.updated_at);
    return ms ? formatResTime(sorted[0]?.updated_at) : "";
  }, [sorted]);

  const empty = items.length === 0 && !loading;
  if (!chatId) return null;

  return (
    <section
      className={[styles.strip, className].filter(Boolean).join(" ")}
      aria-label={groupTitle}
    >
      <header className={styles.head}>
        <span className={styles.headTitle} title={groupTitle}>
          {groupTitle}
        </span>
        <span className={styles.headCount}>
          {t("chat:resources.count", "共 {{n}} 项", { n: total })}
        </span>
      </header>

      {empty ? (
        showEmpty ? (
          <p className={styles.empty}>{t("chat:resources.empty", "本轮没有资源")}</p>
        ) : null
      ) : (
        <ul className={styles.list}>
          {shown.map((item) => {
            const title = formatResourceTitle(item);
            const { ext } = splitFileName(resourceFileName(item.path));
            return (
              <li key={item.resource_key} className={styles.item}>
                <button
                  type="button"
                  className={styles.itemMain}
                  title={item.path}
                  onClick={() => handlePick(item)}
                >
                  <span className={styles.itemKind}>
                    {kindLabel(item.kind, t)}
                  </span>
                  <span className={styles.itemName}>{title}</span>
                  <span className={styles.itemMeta}>
                    {ext ? <em className={styles.itemExt}>{ext}</em> : null}
                    {formatResSize(item.size)}
                    {(item.version ?? 0) > 1 ? ` · ${t("chat:resources.version", "v{{n}}", { n: item.version ?? 1 })}` : ""}
                  </span>
                  <span className={styles.itemTime}>{formatResTime(item.updated_at)}</span>
                </button>
                {item.kind === "file" ? (
                  <button
                    type="button"
                    className={styles.itemDl}
                    title={t("chat:resources.download", "下载")}
                    onClick={() => handleDownload(item)}
                  >
                    ↓
                  </button>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}

      <footer className={styles.foot}>
        {sorted.length > maxItems ? (
          <button
            type="button"
            className={styles.footBtn}
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded
              ? t("chat:resources.collapse", "收起")
              : t("chat:resources.expandRest", "展开其余 {{n}} 项", { n: sorted.length - maxItems })}
          </button>
        ) : null}
        {onOpenAll ? (
          <button
            type="button"
            className={styles.footBtn}
            title={lastTs ? `${t("chat:resources.time", "更新时间")} ${lastTs}` : undefined}
            onClick={onOpenAll}
          >
            {t("chat:resources.viewAll", "查看全部")}
          </button>
        ) : null}
      </footer>
    </section>
  );
}

export const CoApisResourceStrip = memo(CoApisResourceStripBase);
export default CoApisResourceStrip;
