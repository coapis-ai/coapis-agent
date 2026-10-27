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
import { Maximize2, Minimize2, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import useIsMobile from "../../../hooks/useIsMobile";
import styles from "./FloatingWindow.module.less";

export type FloatingRect = { x: number; y: number; w: number; h: number };

const EDGES = ["n", "s", "e", "w", "nw", "ne", "sw", "se"] as const;
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
  className,
  bodyClassName,
}: FloatingWindowProps) {
  const { t } = useTranslation();
  const isMobile = useIsMobile();

  const [host, setHost] = useState<HTMLElement | null>(null);
  const [maximized, setMaximized] = useState(false);
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
  }, [persistRect]);

  const startDrag = useCallback(
    (e: React.MouseEvent, mode: "move" | Edge) => {
      const hostEl = hostRef.current;
      if (!hostEl) return;
      if (maximized || isMobile || isEmbedded()) return;
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

  /** 打开时解析宿主（position:static 时补 relative，浮窗才有定位参照），并落初始矩形。 */
  useEffect(() => {
    if (!open) return;
    const el = getContainer?.() ?? document.body;
    hostRef.current = el;
    setHost(el);
    if (getComputedStyle(el).position === "static") {
      el.style.position = "relative";
    }
    setMaximized(false);
    if (isMobile || isEmbedded()) {
      setRect({ x: 0, y: 0, w: el.clientWidth, h: el.clientHeight });
    } else {
      setRect(initialRect(el));
    }
  }, [open, getContainer, initialRect, isMobile]);

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

  /** Esc 关闭。 */
  useEffect(() => {
    if (!open || !closeOnEsc) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, closeOnEsc, onClose]);

  /**
   * 点窗口外关闭（资源抽屉沿用旧行为；预览窗默认不开，避免误触丢预览）。
   * outsideIgnoreSelector 豁免触发按钮：点按钮要的是「切换开关」，若也算点外，
   * 会先 mousedown 关窗、再 click 开窗，净效果是「点了没关」——故必须豁免。
   */
  useEffect(() => {
    if (!open || !closeOnClickOutside) return;
    const onDown = (e: MouseEvent) => {
      const el = winRef.current;
      if (!el || el.contains(e.target as Node)) return;
      const target = e.target as HTMLElement;
      if (outsideIgnoreSelector && target.closest(outsideIgnoreSelector)) return;
      onClose();
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open, closeOnClickOutside, onClose, outsideIgnoreSelector]);

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
  const style: React.CSSProperties = freeform
    ? { left: rect.x, top: rect.y, width: rect.w, height: rect.h }
    : { left: 0, top: 0, width: "100%", height: "100%" };

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
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      style={style}
    >
      {freeform &&
        EDGES.map((edge) => (
          <span
            key={edge}
            className={styles[`rz-${edge}`]}
            onMouseDown={(e) => startDrag(e, edge)}
          />
        ))}
      <div className={styles.header} onMouseDown={(e) => startDrag(e, "move")}>
        <div className={styles["head-title"]} data-nodrag>
          {title}
        </div>
        {extra ? (
          <div className={styles["head-extra"]} data-nodrag>
            {extra}
          </div>
        ) : null}
        {showMaximize && !isMobile && !isEmbedded() && (
          <Tooltip
            title={
              maximized ? t("chat.preview.restore") : t("chat.preview.maximize")
            }
          >
            <Button
              type="text"
              size="small"
              icon={maximized ? <Minimize2 /> : <Maximize2 />}
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
            icon={<X />}
            onClick={onClose}
            aria-label={t("common.close")}
          />
        </Tooltip>
      </div>
      <div className={[styles.body, bodyClassName].filter(Boolean).join(" ")}>
        {children}
      </div>
      {footer ? <div className={styles.footer}>{footer}</div> : null}
    </div>,
    host ?? document.body,
  );
}
