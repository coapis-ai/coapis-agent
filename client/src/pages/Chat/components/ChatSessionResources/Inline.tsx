/**
 * 左栏「当前会话」的资源下拉（B1/B2）。
 *
 * 设计口径（小蜜蜂 2026-11-21 定稿，推翻 2026-11-13 的平铺形态）：
 *  - 资源挂在**当前会话标题下方**，随会话选中态出现；未选中的会话不显示资源。
 *  - 结构 = **一行控制条** + 展开位（2026-11-21 用户第 2 次纠正定稿）：
 *      这一行：「会话资源 N」「引用 N ▾」「产出 N ▾」「查看全部」；
 *      引用/产出是行上的两枚下拉开关，点哪个展开哪个、再点收起，
 *      两组互不影响；「查看全部」= 打开 L3 完整抽屉。
 *  - **不再**底部挂「会话全部资源」大按钮，也**不再**让「引用」「产出」
 *    各自占一行组头——都在「会话资源」这一行里。
 *  - 分组尺子与聊天本轮资源条同源：`splitResourcesByRole`
 *    （producer/export → 产出，其余 → 引用），三处一把尺子。
 *  - 行首图标按类别出形状（Word/Excel/PDF/图片/网页…各有各的形，颜色按大类），
 *    行尾来源标签四类（产出 / 知识库 / 网页 / 引用），尺子在 ../resourceDisplay.tsx
 *    —— 与聊天里同源，同一条资源在两处的形状与标签一致。
 *  - 面板限高 240px 内部滚动，不撑破左栏。
 *  - 预览走页面级预览抽屉；不可预览的类型退化成下载。
 *
 * 数据源是台账消费端点 `GET /chats/{chatId}/resources`（B2）：只返回
 * status=active 的行，按 path 去重取最新版。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  canInlinePreview,
  downloadFile,
  previewFile,
  toLedgerRelPath,
} from "../../../../utils/webPreview";
import { formatResMeta, splitFileName } from "./resourceFormat";
import type { ChatResourceItem } from "../../../../api/modules/chat";
import { categoryIconOf, SOURCE_LABEL_KEY, sourceOf } from "../resourceDisplay";
import { splitResourcesByRole } from "../CoApisChatResourceBar";
import { getChatResourcesShared } from "../useChatResourceLedger";
import { displayName } from "./helpers";
import styles from "./inline.module.less";

/** 用户拍板（2026-11-21）：一组默认只渲染最近 PANEL_PAGE 条，点「更多」
    再放 10 条，以此类推 —— 不再一次性把整组铺满左栏。 */
const PANEL_PAGE = 10;

/** 「按实际倒序」的尺子：行上显示的是更新时间，就按更新时间倒序。
    取序 updated_at → last_seen_at，与后端 updated_at 的兜底口径一致，
    避免出现「上面写 3 天前、下面写 1 小时前」的两把尺子。 */
function resTime(item: ChatResourceItem): number {
  const pick = (v: number | string | null | undefined): number => {
    if (typeof v === "number" && Number.isFinite(v)) return v;
    if (typeof v === "string") {
      const parsed = Date.parse(v);
      return Number.isNaN(parsed) ? 0 : parsed;
    }
    return 0;
  };
  return pick(item.updated_at) || pick(item.last_seen_at);
}

/** 时间倒序（最新在最上面）。同刻保持后端返回的顺序：Array#sort 是稳定的。 */
function byTimeDesc(a: ChatResourceItem, b: ChatResourceItem): number {
  return resTime(b) - resTime(a);
}

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
   * 打开 L3 资源抽屉。入口是标题行的「查看」（2026-11-21 收口：
   * 底部大按钮「会话全部资源」被用户判废，入口从底部挪到标题行）。
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
  // v25 · P5（第 3 条「计数口径」）：标题行的数字用**后端 total**，不是面板
  // 渲染条数。面板只铺最近 10 条（点「更多」逐页放）、共享缓存上限 200；此前
  // 数字取 items.length → 台账有 55 条时左栏写 40、抽屉写 55、本轮条写 55，
  // 同一个数三处不一（小蜜蜂 2026-11-06 第 1 条量出来的老毛病）。
  const [total, setTotal] = useState(0);
  // 每组已渲染多少条（v28 拍板：默认 10，点「更多」再 +10）。
  // 按组分开记：展开 / 收起另一组不会互相影响。
  const [visible, setVisible] = useState<Record<string, number>>({});
  // 2026-11-21 用户拍板：引用/产出是**下拉**，展开后必须能再收起。
  // 默认两组都展开（左栏资源必须抬眼可见，这是 v23 定过的盘）；点组头收起。
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const lastKeyRef = useRef<number | null>(null);

  const load = useCallback(
    async (force = false) => {
      if (!chatId) {
        setItems([]);
        setTotal(0);
        return;
      }
      try {
        // 共享缓存（实施细则 B4「切会话减负」①）：与台账钩子合并成一次请求，
        // 面板从同一份结果里切片，不再各发一次 limit=40 / limit=200。
        const entry = await getChatResourcesShared(chatId, force);
        // v28：这里不再按面板上限截断 —— 缓存里留全量（共享缓存上限 200），
        // 面板自己按 visible 切片，「更多」才不会点到一半没货。
        setItems(entry.items);
        setTotal(entry.total ?? entry.items.length);
      } catch {
        // 资源是附属信息，取不到不该在左栏报错——静默降级为空面板。
        setItems([]);
        setTotal(0);
      }
    },
    [chatId],
  );

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

  // 换会话时清掉折叠记忆：上个会话「收起引用」的选择不该带过来。
  useEffect(() => {
    setCollapsed({});
    setVisible({});
  }, [chatId]);

  const toggleGroup = useCallback((key: string) => {
    setCollapsed((prev) => ({ ...prev, [key]: !prev[key] }));
  }, []);

  // 下拉列表本体（2026-11-21 用户第 2 次纠正后）：组头已上移到「会话资源」
  // 那一行，这里只出条目；收起状态由行上的 chip 决定，不再自己占一行。
  const renderList = (key: string, all: ChatResourceItem[]) => {
    if (all.length === 0 || collapsed[key]) return null;
    // 「默认只显示最近的 10 条（按实际倒序）」：组内先按时间倒序，再按
    // visible 切片；点「更多」把这一组再放 10 条，以此类推，不一次铺满。
    const rows = [...all].sort(byTimeDesc);
    const cap = visible[key] ?? PANEL_PAGE;
    const shown = rows.slice(0, cap);
    const rest = rows.length - shown.length;
    return (
      <ul className={styles.list} key={key} data-group={key}>
        {shown.map((item) => {
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
              data-coapis-res-row={item.resource_key}
              title={`${rel || name}${
                previewable
                  ? ""
                  : ` · ${t(
                      "chat.resDownloadOnly",
                      "该格式无法在线预览，仅可下载",
                    )}`
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
                  <span className={styles.rowIcon}>{categoryIconOf(item)}</span>
                  <span className={styles.rowStem}>{stem}</span>
                  {ext ? <span className={styles.rowExt}>{ext}</span> : null}
                </span>
                <span className={styles.rowMeta}>
                  {meta}
                  {previewable
                    ? null
                    : ` · ${t("chat.resDownloadOnlyShort", "仅下载")}`}
                  <span
                    className={styles.rowTag}
                    data-src={sourceOf(item)}
                    title={t(SOURCE_LABEL_KEY[sourceOf(item)])}
                  >
                    {t(SOURCE_LABEL_KEY[sourceOf(item)])}
                  </span>
                </span>
              </button>
            </li>
          );
        })}
        {rest > 0 && (
          <li className={styles.moreRow}>
            <button
              type="button"
              className={styles.more}
              data-coapis-more={key}
              onClick={() =>
                setVisible((prev) => ({ ...prev, [key]: cap + PANEL_PAGE }))
              }
            >
              {t("chat.resources.moreBtn", "更多")}
            </button>
            <span className={styles.moreRest}>
              {t("chat.resources.moreRest", { n: rest })}
            </span>
          </li>
        )}
      </ul>
    );
  };

  if (!chatId) return null;

  const { produced, referenced } = splitResourcesByRole(items);

  // 引用在前、产出在后（与聊天本轮资源条、chip 顺序一致）；空组不出开关。
  const groups = [
    {
      key: "referenced",
      label: t("chat.resourceGroupReferenced", "引用"),
      rows: referenced,
    },
    {
      key: "produced",
      label: t("chat.resourceGroupProduced", "产出"),
      rows: produced,
    },
  ].filter((g) => g.rows.length > 0);

  return (
    <div className={styles.wrap}>
      {items.length > 0 && (
        /* 一行控制条（2026-11-21 用户第 2 次纠正）：「会话资源」这一行同时装下
           「引用 N」「产出 N」「查看全部」。引用/产出各是一枚下拉开关，点哪个
           展开哪个、再点一下收起，两组互不影响；「查看」进 L3 抽屉。
           data-coapis-res-trigger 是给抽屉「点外面就关」认的标记，别丢。 */
        <div className={styles.bar} data-coapis-res-bar="">
          <span className={styles.barTitle}>
            {t("chat.resources.barTitle", "会话资源")}
            <span className={styles.barCount}>{total}</span>
          </span>
          {groups.map((g) => (
            <button
              key={g.key}
              type="button"
              className={styles.chip}
              data-group={g.key}
              aria-expanded={!collapsed[g.key]}
              onClick={() => toggleGroup(g.key)}
            >
              <span className={styles.chipLabel}>{g.label}</span>
              <span className={styles.chipCount}>{g.rows.length}</span>
              <span
                className={styles.chipCaret}
                data-collapsed={!!collapsed[g.key]}
              >
                ▾
              </span>
            </button>
          ))}
          {onShowAll && (
            <button
              type="button"
              className={styles.viewAll}
              onClick={() => onShowAll(chatId ?? undefined)}
              title={t(
                "chat.resources.viewAllTip",
                "打开本会话全部资源（含历史轮次）",
              )}
              data-coapis-res-trigger=""
            >
              {t("chat.resources.viewAll", "查看全部")}
            </button>
          )}
        </div>
      )}
      <div className={styles.body} ref={bodyRef}>
        {items.length === 0 ? (
          <div className={styles.empty}>
            {t("chat.sidebar.noResources", "本会话暂无资源")}
          </div>
        ) : (
          <>
            {renderList("referenced", referenced)}
            {renderList("produced", produced)}
          </>
        )}
      </div>
    </div>
  );
}

export default ChatSessionResourcesInline;
