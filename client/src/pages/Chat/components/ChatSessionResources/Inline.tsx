/**
 * 左栏「当前会话」的资源下拉（B1/B2）。
 *
 * 设计口径（小蜜蜂 2026-10-23 定稿）：
 *  - 资源挂在**当前会话标题下方**，随会话选中态出现；未选中的会话不显示资源。
 *  - 分「生成 / 引用」两组，组头可折叠；不显示"会话资源"这种标题头。
 *  - 面板限高 168px 内部滚动，不撑破左栏。
 *  - 预览走页面级预览抽屉；不可预览的类型退化成下载。
 *  - 顶栏资源按钮已下线（D3），这里留一条「查看全部」作为 L3 抽屉的常驻入口。
 *
 * 数据源是台账消费端点 `GET /chats/{chatId}/resources`（B2）：只返回
 * status=active 的行，按 path 去重取最新版。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FolderOpen } from "lucide-react";
import {
  downloadFile,
  getPreviewKind,
  previewFile,
  toLedgerRelPath,
} from "../../../../utils/webPreview";
import type { ChatResourceItem } from "../../../../api/modules/chat";
import { getChatResourcesShared } from "../useChatResourceLedger";
import { displayName } from "./helpers";
import styles from "./inline.module.less";

/**
 * 分组口径：用台账行的 `role`，不用类型名。
 *
 * 台账给文件类资源登记的 `kind` 恒为 "file"（foundation/file_ledger.py），
 * 按 report/pdf/image 这类名字分「生成/引用」会全部落进引用组——用户要的两组
 * 必须来自后端的 role（producer=本次会话产出，reference=读进来的）。
 */
const PRODUCER_ROLE = "producer";

/** 面板内最多渲染的行数：多于这个数走「查看全部」进抽屉，不在左栏堆。 */
const PANEL_LIMIT = 40;

interface ChatSessionResourcesInlineProps {
  /** 后端 chatId（UUID）；空则整块不渲染。 */
  chatId: string | null | undefined;
  /** 台账写入后自增，触发重取。 */
  refreshKey?: number;
  /**
   * 打开页面级预览抽屉。不传则组件自己调 previewFile（走全局预览器）。
   */
  onPreview?: (path: string, title: string) => void;
  /**
   * 打开 L3 资源抽屉。顶栏资源按钮已下线，左栏下拉是常驻入口；面板里必须
   * 留一条「查看全部」——否则台账里资源多于面板上限的会话，多出来的那些
   * 在本页没有任何入口。
   */
  onShowAll?: (chatId?: string) => void;
}

/**
 * 行内预览：优先用页面级回调（聊天页的预览抽屉），没有就退到全局预览器，
 * 再不行退化成下载。三层兜底，左栏不会出现"点了没反应"。
 */
function openResource(
  item: ChatResourceItem,
  onPreview?: (path: string, title: string) => void,
): void {
  const rel = toLedgerRelPath(item.path);
  if (!rel) return;
  const title = displayName(item) || rel;
  if (onPreview) {
    onPreview(rel, title);
    return;
  }
  if (getPreviewKind(rel) !== "unsupported") {
    previewFile(rel, title);
    return;
  }
  void downloadFile(rel, title);
}

export function ChatSessionResourcesInline({
  chatId,
  refreshKey = 0,
  onPreview,
  onShowAll,
}: ChatSessionResourcesInlineProps) {
  const { t } = useTranslation();
  const [items, setItems] = useState<ChatResourceItem[]>([]);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const lastKeyRef = useRef<number | null>(null);

  const load = useCallback(async (force = false) => {
    if (!chatId) {
      setItems([]);
      return;
    }
    try {
      // 共享缓存（实施细则 B4「切会话减负」①）：与台账钩子合并成一次请求，
      // 面板从同一份结果里切片，不再各发一次 limit=40 / limit=200。
      const entry = await getChatResourcesShared(chatId, force);
      setItems(entry.items.slice(0, PANEL_LIMIT));
    } catch {
      // 资源是附属信息，取不到不该在左栏报错——静默降级为空面板。
      setItems([]);
    }
  }, [chatId]);

  useEffect(() => {
    // 挂载时命中缓存即不发请求；只有刷新信号变化（本轮写了新文件）才强制穿透
    const force =
      lastKeyRef.current !== null && refreshKey !== lastKeyRef.current;
    lastKeyRef.current = refreshKey;
    void load(force);
  }, [load, refreshKey]);

  // B1：展开位切换后把面板滚进视野。左栏是定高滚动容器，新面板挂在
  // 列表末尾时完全在视口外，用户点了展开却看不到任何东西。
  useEffect(() => {
    if (!chatId || items.length === 0) return;
    bodyRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [chatId, items.length]);

  const produced = items.filter((it) => it.role === PRODUCER_ROLE);
  const referenced = items.filter((it) => it.role !== PRODUCER_ROLE);

  const toggleGroup = useCallback((key: string) => {
    setCollapsed((prev) => ({ ...prev, [key]: !prev[key] }));
  }, []);

  const renderGroup = (
    key: string,
    label: string,
    rows: ChatResourceItem[],
  ) => {
    if (rows.length === 0) return null;
    const isCollapsed = collapsed[key];
    return (
      <div className={styles.group} key={key}>
        <button
          type="button"
          className={styles.groupHead}
          onClick={() => toggleGroup(key)}
          aria-expanded={!isCollapsed}
        >
          <span className={styles.groupLabel}>{label}</span>
          <span className={styles.groupCount}>{rows.length}</span>
          <span className={styles.groupChevron} data-collapsed={isCollapsed}>
            ▾
          </span>
        </button>
        {!isCollapsed && (
          <ul className={styles.list}>
            {rows.slice(0, PANEL_LIMIT).map((item) => {
              const rel = toLedgerRelPath(item.path);
              const name = displayName(item) || rel;
              const previewable = rel
                ? getPreviewKind(rel) !== "unsupported"
                : false;
              return (
                <li
                  key={`${item.resource_key}:${item.version}`}
                  className={styles.row}
                  title={rel || name}
                >
                  <button
                    type="button"
                    className={styles.rowMain}
                    disabled={!rel}
                    onClick={() => openResource(item, onPreview)}
                  >
                    <span className={styles.rowName}>{name}</span>
                  </button>
                  {rel && (
                    <button
                      type="button"
                      className={styles.rowDl}
                      title={t("chat.resource.download", "下载")}
                      onClick={() => void downloadFile(rel, name)}
                    >
                      ↓
                    </button>
                  )}
                  {!previewable && rel && (
                    <span className={styles.rowTag} data-kind="plain">
                      {t("chat.resource.noPreview", "仅下载")}
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    );
  };

  if (!chatId) return null;

  return (
    <div className={styles.wrap}>
      <div className={styles.body} ref={bodyRef}>
        {items.length === 0 ? (
          <div className={styles.empty}>
            {t("chat.sidebar.noResources", "本会话暂无资源")}
          </div>
        ) : (
          <>
            {renderGroup(
              "produced",
              t("chat.resourceGroupProduced", "生成"),
              produced,
            )}
            {renderGroup(
              "referenced",
              t("chat.resourceGroupReferenced", "引用"),
              referenced,
            )}
          </>
        )}
      </div>

      {/* L3 入口：顶栏资源按钮已下线，左栏下拉是常驻入口。台账里多于面板
          上限的资源只能从这条进抽屉，缺了它那些文件在本页没有任何入口。 */}
      {onShowAll && items.length > 0 && (
        <button
          type="button"
          className={styles.showAll}
          onClick={() => onShowAll(chatId ?? undefined)}
          title={t("chat.sidebar.showAllTitle", "打开完整资源列表")}
          /* 抽屉「点外面就关」认这个标记：入口自己 toggle，抢关会关掉又立刻重开 */
          data-coapis-res-trigger=""
        >
          <FolderOpen size={11} />
          <span>
            {t("chat.sidebar.showAll", "查看全部")} · {items.length}
          </span>
        </button>
      )}
    </div>
  );
}

export default ChatSessionResourcesInline;
