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
  canInlinePreview,
  downloadFile,
  previewFile,
  toLedgerRelPath,
} from "../../../../utils/webPreview";
import { formatResMeta, splitFileName } from "./resourceFormat";
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
 *
 * v25 · P2（第 1 条「和聊天界面里类似」）：产出 = producer **或 export**。
 * 本轮资源条的筛选（CoApisChatResourceBar:510）、L3 抽屉的绿标签
 * （ChatSessionResources/index.tsx）、台账 v25 新增的 role 筛选，三处都是
 * `producer|export`；左栏此前只认 producer → 导出（export）行在左栏落进
 * 「引用」组、在抽屉里顶着绿色「产出」标签，同一行两处口径打架。
 */
const PRODUCED_ROLES: ReadonlySet<string> = new Set(["producer", "export"]);

/** 与上面这把尺子同源的判定（左栏分组 / 计数共用）。 */
const isProducedRole = (role?: string): boolean =>
  PRODUCED_ROLES.has(role || "");

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
 *
 * v25 · P2（小蜜蜂 2026-11-09 第 1 条「和聊天界面里类似」）三处收口：
 *  ① 网页类（kind=web）的 `path` 是 URL：此前当成「我的空间相对路径」喂给预览
 *     抽屉 → 抽屉按扩展名判类型判不出 → 点开是空白页。本轮资源条与 L3 抽屉
 *     对网页类都是 `window.open`，左栏补齐同一行为。
 *  ② 标签与动作用**同一把尺子**：行尾写「仅下载」的行，点开必须真的下载。
 *     尺子取 `canInlinePreview` —— 预览抽屉自己的开门条件就是这一把
 *     （CoApisPreviewDrawer.tsx:200），v17 · F3 定的也是它。此前标签用它、
 *     动作无条件进抽屉，`.doc/.xls/.ppt` 这类标签写「仅下载」点开却开抽屉。
 *  ③ 名字用 `displayName`（含扩展名）：与抽屉/本轮条一字不差（此前用
 *     `item.title`，台账历史行登记的是 `Path(p).stem`，扩展名被抹掉）。
 */
function openResource(
  item: ChatResourceItem,
  onPreview?: (path: string, title: string) => void,
): void {
  const title = displayName(item) || item.path;
  if (item.kind === "web") {
    if (/^https?:\/\//i.test(item.path)) {
      window.open(item.path, "_blank", "noopener,noreferrer");
    }
    return;
  }
  const rel = toLedgerRelPath(item.path);
  if (!rel) return;
  if (!canInlinePreview(rel)) {
    void downloadFile(rel, title, item.kind);
    return;
  }
  if (onPreview) {
    onPreview(rel, title);
    return;
  }
  void previewFile(rel, title);
}

export function ChatSessionResourcesInline({
  chatId,
  refreshKey = 0,
  onPreview,
  onShowAll,
}: ChatSessionResourcesInlineProps) {
  const { t } = useTranslation();
  const [items, setItems] = useState<ChatResourceItem[]>([]);
  // v25 · P5（第 3 条「计数口径」）：折叠行的数字用**后端 total**，不是面板
  // 渲染条数。面板上限 PANEL_LIMIT=40、共享缓存上限 200，超过就切片；此前
  // 「查看全部 · N」取 items.length → 台账有 55 条时左栏写 40、抽屉写 55、
  // 本轮条写 55，同一个数三处不一（小蜜蜂 2026-11-06 第 1 条量出来的老毛病，
  // 当时只把「去重」统一了，切片这层没管）。
  const [total, setTotal] = useState(0);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const lastKeyRef = useRef<number | null>(null);

  const load = useCallback(async (force = false) => {
    if (!chatId) {
      setItems([]);
      setTotal(0);
      return;
    }
    try {
      // 共享缓存（实施细则 B4「切会话减负」①）：与台账钩子合并成一次请求，
      // 面板从同一份结果里切片，不再各发一次 limit=40 / limit=200。
      const entry = await getChatResourcesShared(chatId, force);
      setItems(entry.items.slice(0, PANEL_LIMIT));
      setTotal(entry.total ?? entry.items.length);
    } catch {
      // 资源是附属信息，取不到不该在左栏报错——静默降级为空面板。
      setItems([]);
      setTotal(0);
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

  const produced = items.filter((it) => isProducedRole(it.role));
  const referenced = items.filter((it) => !isProducedRole(it.role));

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
              // v17 · F3：预览能力只由 canInlinePreview 一处说了算
              // （此前这里看 `getPreviewKind !== "unsupported"`，抽屉看
              // `canInlinePreview`，两张表必然分裂 → 行上写着"可预览"、
              // 点进去抽屉说"不支持预览"）。
              const previewable = rel ? canInlinePreview(rel) : false;
              const { stem, ext } = splitFileName(name);
              const meta = formatResMeta(item.size, item.updated_at);
              return (
                <li
                  key={`${item.resource_key}:${item.version}`}
                  className={styles.row}
                  title={`${rel || name}${
                    previewable
                      ? ""
                      : ` · ${t("chat.resDownloadOnly", "该格式无法在线预览，仅可下载")}`
                  }`}
                >
                  {/* v17 · F8（小蜜蜂 2026-11-05 第 5 条，三件事一起收）：
                      ① 行内**不再挂下载按钮** —— 一行一枚 ↓ 把左栏变成了
                         下载栏，还与"点行=预览"抢语义；下载收进 L3 抽屉。
                      ② 名称**拆两段**：主干可截、扩展名保尾。旧写法整串
                         ellipsis 从右往左吃，面板一窄先被吃掉的就是 `.docx`，
                         用户看到"报表-季度…"分不清格式。
                      ③ 补第二行小字 **大小 · 时间** —— 左栏此前压根没有时间。 */}
                  <button
                    type="button"
                    className={styles.rowMain}
                    disabled={!rel}
                    onClick={() => openResource(item, onPreview)}
                  >
                    <span className={styles.rowName}>
                      <span className={styles.rowStem}>{stem}</span>
                      {ext ? <span className={styles.rowExt}>{ext}</span> : null}
                    </span>
                    <span className={styles.rowMeta}>
                      {meta}
                      {previewable
                        ? null
                        : ` · ${t("chat.resDownloadOnlyShort", "仅下载")}`}
                    </span>
                  </button>
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
              t("chat.resourceGroupProduced", "产出"),
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
            {/* v25 · P5：数字 = 后端 total（与 L3 抽屉「共 N 条」、本轮条
                「会话全部资源 · N」同一把尺子）；面板内的分组计数是切片后
                的计数，两者不是一回事。 */}
            {t("chat.sidebar.showAll", "会话全部资源")} · {total}
          </span>
        </button>
      )}
    </div>
  );
}

export default ChatSessionResourcesInline;
