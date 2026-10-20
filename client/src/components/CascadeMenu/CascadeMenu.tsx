import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Spin } from "antd";
import { useTranslation } from "react-i18next";
import { RightOutlined, FolderOutlined, FileTextOutlined } from "@ant-design/icons";
import styles from "./cascade.module.less";

/**
 * 通用级联菜单（Cascade Menu）—— 纯 UI 层，零领域知识。
 *
 * 三层契约：
 * 1. 数据契约 `CascadeNode`：调用方把任意数据源（文件树 / 知识库 / MCP 资源 /
 *    场景树…）映射成统一节点，组件不认「文件」「知识库」这些概念。
 * 2. 加载契约 `load`：调用方注入「给定节点 → 返回其子节点」的函数，组件负责
 *    缓存、懒加载、loading 态与列渲染，不关心数据从哪来。
 * 3. 选择契约 `checked` + `onToggle`：勾选语义（目录=单条引用、级联全选、
 *    仅叶子可选…）全部由调用方决定，组件只渲染勾选态并回调。
 *
 * 交互（按拍板 D1/D2/D5/D11）：
 * - 点击一级行才开始（roots 由调用方给出）；
 * - 光标移到某行 200ms（hover-intent）后在右侧展开下一级列，鼠标移出菜单
 *   不清空已展开的列（避免扫读时菜单抖动）；
 * - 每列上限 maxItems（默认 200），超出显示「…还有 N 项」尾巴；
 * - 展开即刷新（refreshOnOpen，默认开）：光标落到某行、点击展开、键盘 → 进入
 *   子列时强制重读该节点子项；旧清单在刷新期间保留，尾部标「刷新中…」；
 * - 窄屏（narrow）单列下钻 + 返回上级；
 * - 键盘：↑↓ 列内移动，→ 进入子列，← 回父列，空格/回车勾选，Esc 交父层。
 */

export interface CascadeNode {
  /** 稳定唯一键（文件路径 / 知识库 id / 资源 uri…） */
  key: string;
  name: string;
  /** group=可展开；item=叶子；action=纯动作行；divider=分隔线；
   *  more=「本列还有 N 项未加载」的计数占位（count 存 N，不渲染成行） */
  kind: "group" | "item" | "action" | "divider" | "more";
  /** 右侧灰色元信息（大小 / 来源 / 篇数…） */
  meta?: string;
  /**
   * 用法语义（设计 §3.1 要求，此前契约里没有这个字段）：
   * 说明该节点被引用后智能体怎么用——
   * working-path=工作路径（智能体可访问该目录下的文件），
   * reference=自动参考（读取文件内容），retrieval=检索（知识库）。
   * UI 据此在引用条图标与提示语分流，目录引用不再与文件引用长得一样。
   */
  usage?: "working-path" | "reference" | "retrieval";
  /** group 的子项总数（未加载时也能显示计数） */
  count?: number;
  /** 默认 true；false 时该行只展示不可勾选（如知识库文档） */
  selectable?: boolean;
  /** action 行的点击行为 */
  onAction?: () => void;
  /** true 时不阻止事件冒泡（用于「＋上传新文件」——点击冒泡到外层 Upload 触发原生文件选择） */
  bubble?: boolean;
  /** 调用方自带数据，回调时原样传回 */
  payload?: unknown;
}

export interface CascadeMenuProps {
  roots: CascadeNode[];
  /** 给定节点 → 其子节点。force=true 时调用方必须绕开自己的缓存真读数据源 */
  load: (node: CascadeNode, force?: boolean) => Promise<CascadeNode[]>;
  checked?: Set<string>;
  onToggle?: (node: CascadeNode) => void;
  /** 每列最多渲染条数（D5：200） */
  maxItems?: number;
  /** 单列最大高度 */
  height?: number;
  /** 窄屏：单列下钻 */
  narrow?: boolean;
  /** 一级列行宽 */
  rootWidth?: number;
  /** 一级列首行自动展开（搜索态：结果列直接呈现，不需要再点一下） */
  autoOpenRoot?: boolean;
  /**
   * 独立层模式（D1/D2/D3 拍板）：一级列留在宿主容器里，二级及以后渲染成
   * 脱离文档流的浮动面板（position:fixed，锚定在打开它的那一行右侧，越界左翻）。
   * 宿主容器尺寸恒定 → 弹层不会因新增列而重算位置（修「上蹿下跳」）。
   */
  portal?: boolean;
  /**
   * 展开即刷新（默认 true）：光标移到某行（hover-intent 命中）、点击展开、
   * 键盘 → 进入子列时，强制重新拉取该节点的子项。
   *
   * 为什么必须有：antd Popover 默认不销毁内容，菜单关闭后本组件仍然挂载，
   * `childrenRef` 缓存与 `openPath` 会一路活到页面卸载。缺了这一项，
   * 「在别处上传/生成文件 → 回到聊天打开菜单」永远看到旧清单
   * （实测：重开菜单 0 次 /myfiles/list 请求）。
   */
  refreshOnOpen?: boolean;
  /** 同一节点两次强制拉取的最小间隔（ms），防鼠标扫动把接口打爆 */
  refreshMinInterval?: number;
}

function sizeLabel(n?: number): string {
  if (!n) return "";
  if (n < 1024) return `${n}B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)}K`;
  return `${(n / 1024 / 1024).toFixed(1)}M`;
}

export default function CascadeMenu(props: CascadeMenuProps) {
  const {
    roots,
    load,
    checked,
    onToggle,
    maxItems = 200,
    height = 320,
    narrow,
    rootWidth = 200,
    autoOpenRoot,
    portal,
    refreshOnOpen = true,
    refreshMinInterval = 1200,
  } = props;
  const { t } = useTranslation();

  const [children, setChildren] = useState<Record<string, CascadeNode[]>>({});
  const [openPath, setOpenPath] = useState<string[]>([]);
  const [loadingKey, setLoadingKey] = useState<string | null>(null);
  // 有旧数据时的「后台刷新中」标记：与 loadingKey 分开，刷新期间旧清单不消失
  const [refreshingKey, setRefreshingKey] = useState<string | null>(null);
  const [filters, setFilters] = useState<Record<number, string>>({});
  const [focus, setFocus] = useState<{ level: number; index: number }>({
    level: 0,
    index: -1,
  });
  // 独立层面板的锚点：level（子列下标）→ 打开它的那一行的左右/顶部坐标
  const [anchors, setAnchors] = useState<Record<number, { left: number; top: number; right: number }>>({});
  // 用 ref 做「已加载」判定，避免 useCallback 依赖 state 造成闭包过期
  const childrenRef = useRef<Record<string, CascadeNode[]>>({});
  // 同一节点的并发拉取去重（hover 反复扫过同一行只发一次请求）
  const inflightRef = useRef<Record<string, Promise<CascadeNode[]>>>({});
  // 每个节点上次真读数据源的时间戳，配合 refreshMinInterval 做节流
  const lastFetchRef = useRef<Record<string, number>>({});
  const hoverTimer = useRef<number | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const colRefs = useRef<Record<number, HTMLDivElement | null>>({});

  useEffect(
    () => () => {
      if (hoverTimer.current) window.clearTimeout(hoverTimer.current);
    },
    [],
  );

  /**
   * 取某节点的子项。
   *
   * - 无缓存：必拉（整列 loading）。
   * - 有缓存 + force（展开动作）：默认必拉（整列保持旧清单，尾部标「刷新中」），
   *   只受 refreshMinInterval 节流与 inflight 去重约束。
   * - 有缓存 + 非 force（键盘预取）：直接吃缓存。
   */
  const ensure = useCallback(
    async (node: CascadeNode, force = false) => {
      if (node.kind !== "group") return;
      const key = node.key;
      const hasCache = !!childrenRef.current[key];
      const throttled =
        Date.now() - (lastFetchRef.current[key] ?? 0) < refreshMinInterval;
      if (hasCache && !(force && refreshOnOpen && !throttled)) return;
      const pending = inflightRef.current[key];
      if (pending) {
        await pending;
        return;
      }
      if (hasCache) setRefreshingKey(key);
      else setLoadingKey(key);
      const task = (async () => {
        let kids: CascadeNode[] = [];
        try {
          kids = await load(node, force && refreshOnOpen);
        } catch {
          // 刷新失败保留旧清单：宁可用旧数据，不要把用户的目录清空
          kids = childrenRef.current[key] ?? [];
        }
        childrenRef.current[key] = kids;
        lastFetchRef.current[key] = Date.now();
        setChildren({ ...childrenRef.current });
        return kids;
      })();
      inflightRef.current[key] = task;
      try {
        await task;
      } finally {
        delete inflightRef.current[key];
        // 只清自己那一次的标记，避免并发拉取互相抹掉 loading
        setLoadingKey((k) => (k === key ? null : k));
        setRefreshingKey((k) => (k === key ? null : k));
      }
    },
    [load, refreshOnOpen, refreshMinInterval],
  );

  const openAt = useCallback(
    (level: number, node: CascadeNode, rect?: { left: number; top: number; right: number }) => {
      setOpenPath((prev) => [...prev.slice(0, level), node.key]);
      // 收起比新列更深的层，并同步丢掉它们的锚点，避免残留面板定位到旧坐标
      setAnchors((prev) => {
        const next: Record<number, { left: number; top: number; right: number }> = {};
        for (let i = 1; i <= level; i++) if (prev[i]) next[i] = prev[i];
        if (rect) next[level + 1] = rect;
        return next;
      });
      void ensure(node, true);
    },
    [ensure],
  );

  // 搜索态：结果列直接展开，不需要再点一下
  useEffect(() => {
    if (!autoOpenRoot) return;
    const r = roots[0];
    if (r && r.kind === "group") {
      setOpenPath([r.key]);
      void ensure(r, true);
    }
  }, [autoOpenRoot, roots, ensure]);

  const rowRect = (e: React.MouseEvent) => {
    const el = e.currentTarget as HTMLDivElement;
    const b = el.getBoundingClientRect();
    return { left: b.left, top: b.top, right: b.right };
  };

  const handleEnter = (level: number, node: CascadeNode, e: React.MouseEvent) => {
    if (node.kind === "action") return;
    // 锚点必须同步取（事件结束后 currentTarget 可能已卸载）
    const rect = rowRect(e);
    if (hoverTimer.current) window.clearTimeout(hoverTimer.current);
    // hover-intent：200ms 才展开，斜着扫鼠标不会一路炸开子列
    hoverTimer.current = window.setTimeout(() => openAt(level, node, rect), 200);
  };

  const handleClick = (level: number, node: CascadeNode, e: React.MouseEvent) => {
    if (hoverTimer.current) window.clearTimeout(hoverTimer.current);
    if (node.kind === "action") {
      node.onAction?.();
      return;
    }
    openAt(level, node, rowRect(e));
    if (onToggle && node.kind === "item" && node.selectable !== false) {
      // 叶子：点行即勾选/取消（D4：点一下即生效）
      onToggle(node);
    }
  };

  const columns: CascadeNode[][] = useMemo(() => {
    const cols: CascadeNode[][] = [roots];
    for (const k of openPath) {
      const kids = children[k];
      if (!kids) break;
      cols.push(kids);
    }
    return cols;
  }, [roots, openPath, children]);

  const visibleCols = narrow ? columns.slice(-1) : columns;

  const onKeyDown = (e: React.KeyboardEvent) => {
    const level = Math.min(focus.level, columns.length - 1);
    const col = columns[level] ?? [];
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.stopPropagation();
      const delta = e.key === "ArrowDown" ? 1 : -1;
      const next = Math.min(Math.max(focus.index + delta, 0), col.length - 1);
      setFocus({ level, index: next });
      const node = col[next];
      if (node?.kind === "group") void ensure(node);
    } else if (e.key === "ArrowRight") {
      const node = col[focus.index];
      if (node?.kind === "group") {
        // 键盘没有鼠标锚点：用整列右边缘 + 行高估算锚点
        const b = colRefs.current[level]?.getBoundingClientRect();
        const rect = b
          ? { left: b.left, top: b.top + focus.index * 28, right: b.right }
          : undefined;
        openAt(level, node, rect);
        setFocus({ level: level + 1, index: 0 });
      }
    } else if (e.key === "ArrowLeft") {
      setFocus({ level: Math.max(level - 1, 0), index: 0 });
    } else if (e.key === " " || e.key === "Enter") {
      const node = col[focus.index];
      if (!node) return;
      e.stopPropagation();
      if (node.kind === "action") node.onAction?.();
      else if (node.kind === "group") {
        // 导航容器（有子级）：回车展开子列，不勾选容器本身
        const b = colRefs.current[level]?.getBoundingClientRect();
        openAt(
          level,
          node,
          b
            ? { left: b.left, top: b.top + focus.index * 28, right: b.right }
            : undefined,
        );
        setFocus({ level: level + 1, index: 0 });
      }
      // 键盘路径必须与鼠标路径一致：selectable:false 的节点（导航根节点）
      // 不允许勾选，否则会把容器本身当成引用对象传给后端
      else if (onToggle && node.selectable !== false) onToggle(node);
    }
  };

  const renderColumn = (items: CascadeNode[], level: number) => {
    const text = (filters[level] ?? "").trim().toLowerCase();
    // 「还有 N 项」计数节点（kind=more）不参与渲染与过滤，只把 N 累加进尾巴行。
    // 后端 /myfiles/list 每页上限 200，适配器把 total 折算成这个节点传进来，
    // 否则前端只看到 200 条、算出 hidden=0，尾巴行永远不出现。
    const moreNode = items.find((n) => n.kind === "more");
    const rest = items.filter((n) => n.kind !== "more");
    const matched = text
      ? rest.filter(
          (n) => n.kind === "group" || n.name.toLowerCase().includes(text),
        )
      : rest;
    const shown = matched.slice(0, maxItems);
    const hidden = matched.length - shown.length + (moreNode?.count ?? 0);
    const parentKey = level > 0 ? (openPath[level - 1] ?? "") : "";
    // 整列转圈只在「什么都没有」时出现；有旧数据时走 refreshing 尾巴，清单不闪空
    const loading = level > 0 && loadingKey === parentKey && rest.length === 0;
    const refreshing = level > 0 && refreshingKey === parentKey;
    const isRoot = level === 0;

    // 独立层：二级及以后脱离文档流，宿主容器尺寸恒定 → 弹层不重算位置
    const float = !!portal && level > 0 && !narrow;
    const colW = isRoot ? rootWidth : 220;
    let style: React.CSSProperties = {
      width: colW,
      maxHeight: height,
      borderRight: float
        ? "none"
        : level === visibleCols.length - 1
          ? "none"
          : "1px solid var(--color-border-secondary, rgba(0,0,0,0.06))",
    };
    if (float) {
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      const a = anchors[level] ?? (() => {
        const b = wrapRef.current?.getBoundingClientRect();
        return b ? { left: b.left, top: b.top, right: b.right } : { left: 0, top: 0, right: 0 };
      })();
      // D2：右侧空间不足时左翻，并 clamp 到视口
      let left = a.right;
      if (left + colW > vw - 8) left = Math.max(8, a.left - colW);
      let top = a.top;
      if (top + height > vh - 8) top = Math.max(8, vh - 8 - height);
      style = {
        ...style,
        position: "fixed",
        left,
        top,
        background: "var(--color-bg-container, #fff)",
        border: "1px solid var(--color-border-secondary, rgba(0,0,0,0.08))",
        borderRadius: 8,
        boxShadow: "0 4px 12px rgba(0,0,0,0.12)",
        zIndex: 1200 + level,
      };
    }

    return (
      <div
        key={`col-${level}`}
        ref={(el) => {
          colRefs.current[level] = el;
        }}
        className={`${styles.cascadeColumn} ${float ? styles.floatColumn : ""}`}
        style={style}
      >
        {level > 0 && items.length > 8 && (
          <input
            className={styles.cascadeFilter}
            value={filters[level] ?? ""}
            onChange={(e) =>
              setFilters((prev) => ({ ...prev, [level]: e.target.value }))
            }
            placeholder={t("cascade.filter", "过滤…")}
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.stopPropagation();
                setFocus({ level, index: 0 });
              }
            }}
          />
        )}
        {loading ? (
          <div style={{ padding: "10px 12px" }}>
            <Spin size="small" />
          </div>
        ) : shown.length === 0 ? (
          <div className={styles.cascadeEmpty}>
            {t("cascade.empty", "这里还没有内容")}
          </div>
        ) : (
          shown.map((node, index) => {
            if (node.kind === "divider") {
              return <div key={node.key} className={styles.cascadeDivider} />;
            }
            const isAction = node.kind === "action";
            const selectable = node.selectable !== false && !isAction;
            const isChecked = checked?.has(node.key);
            const isOpen = openPath[level] === node.key;
            const focused = focus.level === level && focus.index === index;
            return (
              <div
                key={node.key}
                className={`${styles.cascadeRow} ${focused ? styles.focused : ""}`}
                role={isAction ? "menuitem" : "checkbox"}
                aria-checked={selectable ? !!isChecked : undefined}
                title={node.name}
                onClick={(e) => {
                  if (!node.bubble) e.stopPropagation();
                  handleClick(level, node, e);
                }}
                onMouseEnter={(e) => handleEnter(level, node, e)}
              >
                {selectable ? (
                  <span
                    className={styles.tick}
                    style={{
                      background: isChecked
                        ? "var(--color-primary, #1677ff)"
                        : "transparent",
                      borderColor: isChecked
                        ? "transparent"
                        : "var(--color-border, rgba(0,0,0,0.2))",
                    }}
                    // 目录行：点行=展开（D1），点勾选框=勾选（D2：目录引用）
                    onClick={(e) => {
                      e.stopPropagation();
                      if (node.selectable !== false) onToggle?.(node);
                    }}
                  >
                    {isChecked ? "✓" : ""}
                  </span>
                ) : (
                  <span className={styles.tick} style={{ visibility: "hidden" }} />
                )}
                <span className={styles.rowIcon}>
                  {node.kind === "group" ? (
                    <FolderOutlined />
                  ) : node.kind === "action" ? (
                    <FileTextOutlined />
                  ) : (
                    <FileTextOutlined />
                  )}
                </span>
                <span className={styles.rowName}>{node.name}</span>
                <span className={styles.rowMeta}>
                  {node.meta ?? (node.count ? String(node.count) : "")}
                </span>
                {node.kind === "group" && isOpen ? (
                  <span className={styles.rowArrow}>
                    <RightOutlined />
                  </span>
                ) : null}
              </div>
            );
          })
        )}
        {hidden > 0 && (
          <div className={styles.cascadeTail}>
            {t("cascade.more", "…还有 {{n}} 项未显示", { n: hidden })}
          </div>
        )}
        {refreshing && (
          <div className={styles.cascadeTail}>
            {t("cascade.refreshing", "刷新中…")}
          </div>
        )}
        {narrow && columns.length > 1 && level === visibleCols.length - 1 && (
          <div
            className={styles.cascadeRow}
            role="menuitem"
            onClick={(e) => {
              e.stopPropagation();
              setOpenPath((prev) => prev.slice(0, -1));
            }}
          >
            <span className={styles.rowIcon}>←</span>
            <span className={styles.rowName}>
              {t("resourceMenu.back", "返回")}
            </span>
          </div>
        )}
      </div>
    );
  };

  return (
    <div
      ref={wrapRef}
      className={styles.cascadeWrap}
      role="menu"
      tabIndex={0}
      onKeyDown={onKeyDown}
      onMouseLeave={() => {
        if (hoverTimer.current) window.clearTimeout(hoverTimer.current);
      }}
    >
      {visibleCols.map((items, level) => renderColumn(items, level))}
    </div>
  );
}

export { sizeLabel };
