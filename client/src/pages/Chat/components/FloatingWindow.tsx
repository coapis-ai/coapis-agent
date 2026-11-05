/**
 * 聊天区「真浮窗」骨架 —— 预览窗与会话资源抽屉共用的唯一一份实现（G1=A）。
 *
 * 为什么要有这个文件：预览窗先做成了浮窗（挂在聊天主内容区里、可拖头部、
 * 四边四角都能拖大小、位置尺寸记忆、铺满/还原），而会话资源抽屉当时还是
 * antd Drawer —— 贴右缘一块、只有左边界一条把手能拖宽。两个"窗口"长得不一
 * 样、行为不一样，用户直接指出"预览窗口那几个优化在资源抽屉上没实现"。
 * 骨架抽出来之后，聊天区里弹出的窗口共用同一套外观与交互，不会再出现
 * "改了一个忘了另一个"的偏差。
 *
 * 能力（两个窗口都白拿）：
 *   · 挂在宿主容器内的绝对定位真浮窗（createPortal，不撑开聊天布局）
 *   · 拖头部移动；拖 8 个把手（四边 + 四角）缩放
 *   · 铺满 / 还原（铺满时隐藏把手与拖移）
 *   · 位置与尺寸写 localStorage（按 storageKey 各记各的，刷新后回到原位）
 *   · 宿主尺寸变化（浏览器拉窄、左栏折叠）时把窗口夹回可视范围
 *   · 窄屏（useIsMobile）与企微内嵌（body.coapis-embedded）：占满宿主、
 *     禁拖禁缩放 —— 触屏上拖窗没有意义
 *   · Esc 关闭、点窗口外关闭（各自可关：资源抽屉要，预览窗不要，避免误触丢预览）
 *
 * 约定：`open=false` 时整块不渲染；卸载即清理全局监听与 body 上的临时样式。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { Button, Tooltip } from "antd";
import { Maximize2, Minimize2, Minus, Pin, PinOff, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import useIsMobile from "../../../hooks/useIsMobile";
import styles from "./FloatingWindow.module.less";

export type FloatingRect = { x: number; y: number; w: number; h: number };

const EDGES = ["n", "s", "e", "w", "nw", "ne", "sw", "se"] as const;

/**
 * 最小化后的窗高 = 只剩头部一行（v17 · F9）。
 *
 * 「最小化」不是「关掉」：文件看到一半要腾地方，一会儿还要回来。关窗等于把
 * 选中的文件、滚动位置、转换视图全部清掉；最小化只收正文，头部留着当记号，
 * 点一下原样还原 —— `rect` 全程不动，还原零漂移。
 */
const HEAD_H = 40;
type Edge = (typeof EDGES)[number];

export type FloatingWindowProps = {
  open: boolean;
  /** 持久化命名空间：localStorage 记作 coapis.<storageKey>.{w,h,x,y} */
  storageKey: string;
  /** 宿主容器（聊天主内容区）。返回 null 时挂到 document.body。 */
  getContainer?: () => HTMLElement | null;
  /** 头部左侧内容（图标 + 标题/文件切换器等） */
  title?: ReactNode;
  /** 头部右侧附加按钮（预览窗的下载、资源抽屉的定位等），排在 铺满/关闭 之前 */
  extra?: ReactNode;
  /** 内容区 */
  children: ReactNode;
  /** 底部条（路径、查看全部等） */
  footer?: ReactNode;
  onClose: () => void;
  /** 头部 aria-label */
  label?: string;
  closeTip?: string;
  showMaximize?: boolean;
  minWidth?: number;
  minHeight?: number;
  defaultWidth?: number;
  defaultHeight?: number;
  /** 点窗口外是否关闭 */
  closeOnClickOutside?: boolean;
  /** 点外关闭的豁免选择器（如触发按钮本身：点它是要切换开关，不是关窗） */
  outsideIgnoreSelector?: string;
  closeOnEsc?: boolean;
  /**
   * 定住（图钉）：为真时「点外面关闭」不生效。状态由调用方持有并持久化，
   * 骨架只负责渲染按钮与门控 —— 语义上「定住 = 不关闭窗口」。
   */
  pinned?: boolean;
  /** 提供时在头部渲染定住按钮（排在 铺满/关闭 之前） */
  onTogglePin?: () => void;
  pinTip?: string;
  unpinTip?: string;
  className?: string;
  bodyClassName?: string;
};

function isEmbedded(): boolean {
  return (
    typeof document !== "undefined" &&
    document.body.classList.contains("coapis-embedded")
  );
}

function clampNum(v: number, lo: number, hi: number): number {
  if (Number.isNaN(v)) return lo;
  return Math.min(Math.max(v, lo), hi);
}

function readNum(key: string): number | null {
  try {
    const raw = localStorage.getItem(key);
    if (raw === null) return null;
    const n = Number(raw);
    return Number.isFinite(n) ? n : null;
  } catch {
    return null;
  }
}

function safeSet(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* 隐私模式下 localStorage 会抛，忽略即可 */
  }
}

/**
 * 旧版两个浮窗各自留了一批「只记宽度」的键（resourceDrawer.width /
 * previewDrawer.width），骨架统一成 w/h/x/y 之后它们不再被读，留着就是垃圾。
 * 模块级跑一次，跑完立马拉闸，不在每次渲染里重复扫。
 */
let legacyPurged = false;
function purgeLegacyKeys(): void {
  if (legacyPurged) return;
  legacyPurged = true;
  try {
    ["coapis.resourceDrawer.width", "coapis.previewDrawer.width"].forEach((k) =>
      localStorage.removeItem(k),
    );
  } catch {
    /* 同上，隐私模式忽略 */
  }
}
purgeLegacyKeys();

export default function FloatingWindow({
  open,
  storageKey,
  getContainer,
  title,
  extra,
  children,
  footer,
  onClose,
  label,
  closeTip,
  showMaximize = true,
  minWidth = 340,
  minHeight = 260,
  defaultWidth = 560,
  defaultHeight = 560,
  closeOnClickOutside = false,
  outsideIgnoreSelector,
  closeOnEsc = true,
  pinned = false,
  onTogglePin,
  pinTip,
  unpinTip,
  className,
  bodyClassName,
}: FloatingWindowProps) {
  const { t } = useTranslation();
  const isMobile = useIsMobile();

  const [host, setHost] = useState<HTMLElement | null>(null);
  const [maximized, setMaximized] = useState(false);
  // v17 · F9：最小化（收正文、留头部）。与铺满互斥 —— 铺满时整窗已是全屏。
  const [minimized, setMinimized] = useState(false);
  const [interacting, setInteracting] = useState(false);
  const [rect, setRect] = useState<FloatingRect>({
    x: 24,
    y: 12,
    w: defaultWidth,
    h: defaultHeight,
  });

  const winRef = useRef<HTMLDivElement>(null);
  const rectRef = useRef(rect);
  rectRef.current = rect;
  const prevRectRef = useRef<FloatingRect | null>(null);
  const hostRef = useRef<HTMLElement | null>(null);
  // v17 · F9：Esc 处理器要读「当下」的开关态，闭包捕获读到的是旧值
  const minimizedRef = useRef(false);
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    minimizedRef.current = minimized;
    onCloseRef.current = onClose;
  }, [minimized, onClose]);
  const onMoveRef = useRef<((e: MouseEvent) => void) | null>(null);
  const endInteractionRef = useRef<(() => void) | null>(null);

  const sizeKeys = useCallback(
    () => ({
      w: `coapis.${storageKey}.w`,
      h: `coapis.${storageKey}.h`,
      x: `coapis.${storageKey}.x`,
      y: `coapis.${storageKey}.y`,
    }),
    [storageKey],
  );

  const persistRect = useCallback(
    (r: FloatingRect) => {
      const k = sizeKeys();
      safeSet(k.w, String(Math.round(r.w)));
      safeSet(k.h, String(Math.round(r.h)));
      safeSet(k.x, String(Math.round(r.x)));
      safeSet(k.y, String(Math.round(r.y)));
    },
    [sizeKeys],
  );

  /**
   * 铺满 / 最小化两个开关的记忆（v17 · F9）。
   *
   * 位置尺寸早逐次落盘了，这两个开关没人记 —— 用户铺满看完一份长文档，
   * 关掉再开又变回小窗，等于白铺（小蜜蜂：「记忆最近一次位置尺寸 +
   * 铺满记忆」）。
   */
  const persistFlags = useCallback(() => {
    if (!storageKey) return;
    safeSet(`coapis.${storageKey}.max`, maximized ? "1" : "0");
    safeSet(`coapis.${storageKey}.min`, minimized ? "1" : "0");
  }, [storageKey, maximized, minimized]);

  /** 打开时的初始矩形：记忆值优先，越界夹回宿主可视范围。 */
  const initialRect = useCallback(
    (hostEl: HTMLElement): FloatingRect => {
      const hostW = hostEl.clientWidth;
      const hostH = hostEl.clientHeight;
      const k = sizeKeys();
      const savedW = readNum(k.w);
      const savedH = readNum(k.h);
      const savedX = readNum(k.x);
      const savedY = readNum(k.y);
      const w = clampNum(
        savedW ?? Math.min(defaultWidth, hostW - 24),
        Math.min(minWidth, hostW),
        Math.max(minWidth, hostW - 16),
      );
      const h = clampNum(
        savedH ?? Math.min(defaultHeight, hostH - 24),
        Math.min(minHeight, hostH),
        Math.max(minHeight, hostH - 16),
      );
      const x = clampNum(
        savedX ?? hostW - w - 24,
        0,
        Math.max(0, hostW - w),
      );
      const y = clampNum(savedY ?? 12, 0, Math.max(0, hostH - h));
      return { x, y, w, h };
    },
    [sizeKeys, defaultWidth, defaultHeight, minWidth, minHeight],
  );

  const clampRect = useCallback(
    (r: FloatingRect, hostEl: HTMLElement): FloatingRect => {
      const hostW = hostEl.clientWidth;
      const hostH = hostEl.clientHeight;
      const w = clampNum(
        r.w,
        Math.min(minWidth, hostW),
        Math.max(minWidth, hostW - 16),
      );
      const h = clampNum(
        r.h,
        Math.min(minHeight, hostH),
        Math.max(minHeight, hostH - 16),
      );
      return {
        w,
        h,
        x: clampNum(r.x, 0, Math.max(0, hostW - w)),
        y: clampNum(r.y, 0, Math.max(0, hostH - h)),
      };
    },
    [minWidth, minHeight],
  );

  const endInteraction = useCallback(() => {
    const offMove = onMoveRef.current;
    if (offMove) window.removeEventListener("mousemove", offMove);
    onMoveRef.current = null;
    window.removeEventListener("mouseup", endInteraction);
    endInteractionRef.current = null;
    document.body.style.userSelect = "";
    document.body.style.cursor = "";
    setInteracting(false);
    persistRect(rectRef.current);
    persistFlags();
  }, [persistRect, persistFlags]);

  useEffect(() => {
    if (!open) return;
    persistFlags();
  }, [open, persistFlags]);

  const startDrag = useCallback(
    (e: React.MouseEvent, mode: "move" | Edge) => {
      const hostEl = hostRef.current;
      if (!hostEl) return;
      if (maximized || minimized || isMobile || isEmbedded()) return;
      // 头部里的按钮/下拉/输入框（标了 data-nodrag 的元素）不参与拖移
      if (
        mode === "move" &&
        (e.target as HTMLElement).closest(
          "[data-nodrag],button,a,input,textarea,select,.ant-select,.ant-segmented,.ant-btn",
        )
      ) {
        return;
      }
      e.preventDefault();
      const base = rectRef.current;
      const sx = e.clientX;
      const sy = e.clientY;
      const onMove = (ev: MouseEvent) => {
        const dx = ev.clientX - sx;
        const dy = ev.clientY - sy;
        const hostW = hostEl.clientWidth;
        const hostH = hostEl.clientHeight;
        if (mode === "move") {
          setRect({
            ...base,
            x: clampNum(base.x + dx, 0, Math.max(0, hostW - base.w)),
            y: clampNum(base.y + dy, 0, Math.max(0, hostH - base.h)),
          });
          return;
        }
        let { x, y, w, h } = base;
        if (mode.includes("e")) w = base.w + dx;
        if (mode.includes("s")) h = base.h + dy;
        if (mode.includes("w")) {
          w = base.w - dx;
          x = base.x + dx;
        }
        if (mode.includes("n")) {
          h = base.h - dy;
          y = base.y + dy;
        }
        w = clampNum(w, minWidth, Math.max(minWidth, hostW - x));
        h = clampNum(h, minHeight, Math.max(minHeight, hostH - y));
        x = clampNum(x, 0, Math.max(0, hostW - w));
        y = clampNum(y, 0, Math.max(0, hostH - h));
        setRect({ x, y, w, h });
      };
      onMoveRef.current = onMove;
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", endInteraction);
      endInteractionRef.current = endInteraction;
      document.body.style.userSelect = "none";
      document.body.style.cursor = mode === "move" ? "move" : "nwse-resize";
      setInteracting(true);
    },
    [maximized, isMobile, minWidth, minHeight, endInteraction],
  );

  const toggleMaximize = useCallback(() => {
    const hostEl = hostRef.current;
    if (!hostEl) return;
    setMinimized(false);
    setMaximized((m) => {
      if (!m) {
        prevRectRef.current = rectRef.current;
        setRect({ x: 0, y: 0, w: hostEl.clientWidth, h: hostEl.clientHeight });
      } else if (prevRectRef.current) {
        setRect(clampRect(prevRectRef.current, hostEl));
      }
      return !m;
    });
  }, [clampRect]);

  /**
   * 最小化 / 还原（v17 · F9）。`rect` 完全不动 —— 位置与宽高原样保留，只把
   * 渲染高度收成头部一行，还原时一寸不差回到原位。
   */
  const toggleMinimize = useCallback(() => {
    setMaximized(false);
    setMinimized((m) => !m);
  }, []);

  /** 打开时解析宿主（position:static 时补 relative，浮窗才有定位参照），并落初始矩形。 */
  useEffect(() => {
    if (!open) return;
    const el = getContainer?.() ?? document.body;
    hostRef.current = el;
    setHost(el);
    if (getComputedStyle(el).position === "static") {
      el.style.position = "relative";
    }
    // v17 · F9：铺满 / 最小化跨开窗恢复（位置尺寸由 initialRect 已恢复）。
    // 移动网页版与内嵌抽屉宿主本就整页铺满，不接管这两个记忆。
    const memorized = !isMobile && !isEmbedded() && !!storageKey;
    setMaximized(memorized && readNum(`coapis.${storageKey}.max`) === 1);
    setMinimized(memorized && readNum(`coapis.${storageKey}.min`) === 1);
    if (isMobile || isEmbedded()) {
      setRect({ x: 0, y: 0, w: el.clientWidth, h: el.clientHeight });
    } else {
      setRect(initialRect(el));
    }
  }, [open, getContainer, initialRect, isMobile]);

  /**
   * v17 · F9：把"收起 / 铺满"**写**回记忆。此前 `coapis.<key>.min/.max`
   * 只有读、没有写 —— 上面注释写着"跨开窗恢复"，实际每次开都回到默认态。
   * 移动网页版与内嵌抽屉本就整页铺满，不参与这两个记忆。
   */
  useEffect(() => {
    if (!open || isMobile || !storageKey) return;
    try {
      localStorage.setItem(`coapis.${storageKey}.min`, minimized ? "1" : "0");
      localStorage.setItem(`coapis.${storageKey}.max`, maximized ? "1" : "0");
    } catch {
      /* 隐私模式禁存储：记忆退化为"本次会话内生效" */
    }
  }, [open, storageKey, isMobile, minimized, maximized]);

  /** 宿主尺寸变化（浏览器拉窄、左栏折叠）→ 夹回可视范围，避免窗口跑到看不见的地方。 */
  useEffect(() => {
    if (!open || !host) return;
    const onResize = () => {
      const el = hostRef.current;
      if (!el) return;
      if (isMobile || isEmbedded()) {
        setRect({ x: 0, y: 0, w: el.clientWidth, h: el.clientHeight });
        return;
      }
      if (maximized) {
        setRect({ x: 0, y: 0, w: el.clientWidth, h: el.clientHeight });
        return;
      }
      setRect((prev) => clampRect(prev, el));
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [open, host, maximized, isMobile, clampRect]);

  /** Esc 关闭（定住时不生效）。 */
  useEffect(() => {
    if (!open || !closeOnEsc || pinned) return;
    const onKey = (e: KeyboardEvent) => {
      // v17 · F9：最小化态下 Esc 先还原正文，第二下才关窗 —— 一按就关会把
      // 用户选中的文件、滚动位置、转换视图一起清掉。读 ref（闭包里是旧值）。
      if (e.key === "Escape") {
        if (minimizedRef.current) setMinimized(false);
        else onCloseRef.current();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, closeOnEsc, onClose, pinned]);

  /**
   * 点窗口外关闭（资源抽屉沿用旧行为；预览窗默认不开，避免误触丢预览）。
   * outsideIgnoreSelector 豁免触发按钮：点按钮要的是「切换开关」，若也算点外，
   * 会先 mousedown 关窗、再 click 开窗，净效果是「点了没关」——故必须豁免。
   */
  useEffect(() => {
    if (!open || !closeOnClickOutside || pinned) return;
    const onDown = (e: MouseEvent) => {
      const el = winRef.current;
      if (!el || el.contains(e.target as Node)) return;
      const target = e.target as HTMLElement;
      if (outsideIgnoreSelector && target.closest(outsideIgnoreSelector)) return;
      onClose();
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open, closeOnClickOutside, onClose, outsideIgnoreSelector, pinned]);

  /** 卸载兜底：拖移中途组件消失也要摘掉监听、还原 body 样式。 */
  useEffect(
    () => () => {
      const offMove = onMoveRef.current;
      if (offMove) window.removeEventListener("mousemove", offMove);
      const offUp = endInteractionRef.current;
      if (offUp) window.removeEventListener("mouseup", offUp);
      document.body.style.userSelect = "";
      document.body.style.cursor = "";
    },
    [],
  );

  const freeform = !maximized && !isMobile && !isEmbedded();
  const style: React.CSSProperties = !freeform
    ? { left: 0, top: 0, width: "100%", height: "100%" }
    : minimized
    ? { left: rect.x, top: rect.y, width: rect.w, height: HEAD_H }
    : { left: rect.x, top: rect.y, width: rect.w, height: rect.h };

  if (!open) return null;

  return createPortal(
    <div
      ref={winRef}
      role="dialog"
      aria-label={label}
      className={[
        styles.window,
        freeform ? styles.freeform : "",
        interacting ? styles.interacting : "",
        minimized ? styles.minimized : "",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      style={style}
    >
      {freeform &&
        !minimized &&
        EDGES.map((edge) => (
          <span
            key={edge}
            className={styles[`rz-${edge}`]}
            onMouseDown={(e) => startDrag(e, edge)}
          />
        ))}
      {/* v17 · F9（小蜜蜂 2026-11-05 第 6 条「顶部拖不动」的直接病灶）：
          拖移热区 = 头部整行。**标题区此前挂着 `data-nodrag` 且 `flex:1 1 auto`
          吃满头部剩余宽度** —— 鼠标显示 `move`，按下去 `startDrag` 立刻
          `closest("[data-nodrag]")` 返回，等于整条头部 100% 不可拖。
          现在标题区参与拖移，`data-nodrag` 只留给头部里的**交互控件**
          （附加按钮区/下拉/输入框）。双击头部 = 铺满/还原。 */}
      <div
        className={styles.header}
        onMouseDown={(e) => startDrag(e, "move")}
        onDoubleClick={() => {
          if (freeform && showMaximize) toggleMaximize();
        }}
      >
        <div className={styles["head-title"]}>{title}</div>
        {extra ? (
          <div className={styles["head-extra"]} data-nodrag>
            {extra}
          </div>
        ) : null}
        {onTogglePin && !isMobile && !isEmbedded() ? (
          <Tooltip title={pinned ? unpinTip : pinTip}>
            <Button
              type="text"
              size="small"
              className={`${styles["header-btn"]} ${
                pinned ? styles["header-btn-on"] : ""
              }`}
              icon={pinned ? <Pin size={14} /> : <PinOff size={14} />}
              onClick={onTogglePin}
              aria-label={pinned ? unpinTip : pinTip}
            />
          </Tooltip>
        ) : null}
        {showMaximize && !isMobile && !isEmbedded() && (
          <Tooltip
            title={
              minimized
                ? t("chat.previewWinRestore", "还原窗口")
                : t("chat.previewWinMinimize", "最小化")
            }
          >
            <Button
              type="text"
              size="small"
              className={`${styles["header-btn"]} ${
                minimized ? styles["header-btn-on"] : ""
              }`}
              icon={<Minus size={14} />}
              onClick={toggleMinimize}
              aria-label={
                minimized
                  ? t("chat.previewWinRestore", "还原窗口")
                  : t("chat.previewWinMinimize", "最小化")
              }
            />
          </Tooltip>
        )}
        {showMaximize && !isMobile && !isEmbedded() && (
          <Tooltip
            title={
              maximized ? t("chat.preview.restore") : t("chat.preview.maximize")
            }
          >
            <Button
              type="text"
              size="small"
              className={styles["header-btn"]}
              icon={maximized ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
              onClick={toggleMaximize}
              aria-label={
                maximized ? t("chat.preview.restore") : t("chat.preview.maximize")
              }
            />
          </Tooltip>
        )}
        <Tooltip title={closeTip || t("common.close")}>
          <Button
            type="text"
            size="small"
            className={styles["header-btn"]}
            icon={<X size={14} />}
            onClick={onClose}
            aria-label={t("common.close")}
          />
        </Tooltip>
      </div>
      {/* v17 · F9：最小化只留头部一行。正文/页脚**不渲染**而不是 display:none
          —— 预览窗正文里挂着图片和 iframe，display:none 照样占内存、照样发请求。 */}
      {!minimized && (
        <div className={[styles.body, bodyClassName].filter(Boolean).join(" ")}>
          {children}
        </div>
      )}
      {!minimized && footer ? <div className={styles.footer}>{footer}</div> : null}
    </div>,
    host ?? document.body,
  );
}
