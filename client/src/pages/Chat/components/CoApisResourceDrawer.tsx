import React, { useCallback, useEffect, useRef, useState } from "react";
import { Button, Drawer, Space, Tooltip } from "antd";
import { Maximize2, Minimize2, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import useIsMobile from "../../../hooks/useIsMobile";
import { getChatGlobals } from "../../../lib/chatGlobals";
import styles from "./CoApisResourceDrawer.module.less";
import ChatSessionResources from "./ChatSessionResources";
import type { ResourcePreviewRequest } from "./CoApisChatResourceBar";

interface Props {
  open: boolean;
  chatId: string | undefined;
  onClose: () => void;
  refreshSignal?: number;
  onPreview?: (req: ResourcePreviewRequest) => void;
  /**
   * 锚定容器（方案 §F1）：传主内容区节点时，抽屉铺满**主内容区**而不是
   * 整个浏览器窗口 —— 与预览抽屉同一口径，侧栏与顶栏保持可见可用。
   */
  getContainer?: () => HTMLElement;
}

/** 抽屉默认宽度（与预览抽屉同一口径：480px，左缘可拖拽调宽）。 */
const DEFAULT_WIDTH = 480;
/** 拖拽下限：再窄「类型/时间」下拉与搜索框就挤成一坨。 */
const MIN_WIDTH = 360;
/** 宽度记忆键：拖完写 localStorage，下次打开保持。 */
const WIDTH_KEY = "coapis.resourceDrawer.width";

function savedWidth(): number {
  try {
    const v = Number(localStorage.getItem(WIDTH_KEY));
    return Number.isFinite(v) && v >= MIN_WIDTH ? v : DEFAULT_WIDTH;
  } catch {
    return DEFAULT_WIDTH;
  }
}

/**
 * 会话资源抽屉（方案 §3.2 L3 / §12.4）
 * ---------------------------------------------------------------------------
 * 右侧抽屉，全量清单：类型筛选 / 关键词搜索 / 时间排序 / 分页尾巴，
 * 状态标签（已发布·未发布·已迁移·已删除·已失效），「在我的空间定位」。
 *
 * 入口两个（方案原文）：会话右上角「资源」图标、本轮资源条尾部「查看全部」。
 *
 * 2026-10-27 三项体验收口（小蜜蜂实测反馈）：
 *  1. 点抽屉外任意处直接关闭 —— 不开遮罩（遮罩会把聊天区盖成不可交互的
 *     暗层，预览一个文件等于把会话关掉），改成「弹层语义」：document 上挂
 *     mousedown，落点在抽屉外就关。触发「查看全部」的入口自己负责开/关，
 *     这里让位，避免「关掉又立刻重开」的闪动。
 *  2. 左缘拖拽调宽 + 头部「铺满/还原」，宽度写 localStorage 记忆 —— 与
 *     预览抽屉完全同一套手势，同一个功能不在两处各长一个样。
 *  3. 名称列不再吞掉全路径（列宽口径见 ChatSessionResources/index.tsx）。
 */
const CoApisResourceDrawer: React.FC<Props> = ({
  open,
  chatId,
  onClose,
  refreshSignal = 0,
  onPreview,
  getContainer,
}) => {
  const { t } = useTranslation();
  const isMobile = useIsMobile();
  const embedded = getChatGlobals().mode === "embedded";

  const [width, setWidth] = useState<number>(savedWidth);
  const [maximized, setMaximized] = useState(false);
  const [dragging, setDragging] = useState(false);
  const draggingRef = useRef(false);

  const hostOf = useCallback(
    () => (getContainer ? getContainer() : null) as HTMLElement | null,
    [getContainer],
  );

  const drawerWidth =
    isMobile || embedded || maximized ? "100%" : width;

  // ── 点抽屉外关闭（无遮罩的弹层语义）────────────────────────────────
  useEffect(() => {
    if (!open) return;
    const onDown = (ev: MouseEvent) => {
      const node = ev.target as HTMLElement | null;
      if (!node) return;
      // 「查看全部」这类入口自己 toggle：这里抢关会让它关掉又立刻重开
      if (node.closest("[data-coapis-res-trigger]")) return;
      const panel = document.querySelector(
        ".coapis-res-drawer-root .coapis-drawer-content-wrapper",
      );
      if (panel && panel.contains(node)) return;
      // 抽屉里的类型/时间下拉、Tooltip 挂在 body 上，点它们不算「点外面」
      if (
        node.closest(
          '[class*="select-dropdown"],[class*="picker-dropdown"],[class*="tooltip"],[class*="popover"],[class*="modal"]',
        )
      )
        return;
      onClose();
    };
    document.addEventListener("mousedown", onDown, true);
    return () => document.removeEventListener("mousedown", onDown, true);
  }, [open, onClose]);

  // ── 左缘拖拽调宽（360px ~ 容器 90%），松手写 localStorage ──────────
  const startResize = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      const host = hostOf();
      const right = host?.getBoundingClientRect?.().right ?? window.innerWidth;
      draggingRef.current = true;
      setDragging(true);
      document.body.style.userSelect = "none";
      document.body.style.cursor = "col-resize";
      const onMove = (ev: MouseEvent) => {
        if (!draggingRef.current) return;
        const max = Math.max(
          MIN_WIDTH,
          (host?.clientWidth ?? window.innerWidth) * 0.9,
        );
        setMaximized(false);
        setWidth(
          Math.round(Math.min(max, Math.max(MIN_WIDTH, right - ev.clientX))),
        );
      };
      const onUp = () => {
        draggingRef.current = false;
        setDragging(false);
        document.body.style.userSelect = "";
        document.body.style.cursor = "";
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        setWidth((w) => {
          try {
            localStorage.setItem(WIDTH_KEY, String(w));
          } catch {
            /* 隐私模式下 localStorage 会抛，忽略 */
          }
          return w;
        });
      };
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    },
    [hostOf],
  );

  // ── 铺满 / 还原（容器内 100% 宽，主区缩放时跟随）───────────────────
  const toggleMaximize = useCallback(() => {
    setMaximized((m) => {
      const host = hostOf();
      if (!m && host) {
        setWidth(Math.max(MIN_WIDTH, host.clientWidth - 8));
      } else {
        setWidth(savedWidth());
      }
      return !m;
    });
  }, [hostOf]);

  useEffect(() => {
    if (!maximized) return;
    const host = hostOf();
    if (!host) return;
    const onResize = () => setWidth(Math.max(MIN_WIDTH, host.clientWidth - 8));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [maximized, hostOf]);

  return (
    <Drawer
      title={t("chat.resources.drawerTitle", "会话资源")}
      placement="right"
      width={drawerWidth}
      open={open}
      onClose={onClose}
      destroyOnClose
      /* 不开遮罩（方案 D5「浮层可关」）：遮罩会把聊天区盖成不可交互的暗层。
         关闭改由「点抽屉外」+ Esc + 头部关闭按钮三条路。 */
      mask={false}
      maskClosable={false}
      closable={false}
      extra={
        <Space size={4}>
          <Tooltip
            title={
              maximized ? t("chat.preview.restore") : t("chat.preview.maximize")
            }
          >
            <Button
              size="small"
              type="text"
              icon={maximized ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
              onClick={toggleMaximize}
            />
          </Tooltip>
          <Tooltip title={t("common.close", "关闭")}>
            <Button
              size="small"
              type="text"
              icon={<X size={14} />}
              onClick={onClose}
            />
          </Tooltip>
        </Space>
      }
      styles={{
        body: { padding: "12px 16px" },
        wrapper: dragging ? { transition: "none" } : undefined,
        content: { overflow: "hidden" },
      }}
      getContainer={getContainer ? getContainer : undefined}
      /* 第二个类名是给「点外面关闭」用的稳定锚点：CSS Module 会把
         styles[...] 哈希成 CoApisResourceDrawer-module__xxx，DOM 查询认不得。 */
      rootClassName={`${styles["coapis-resource-drawer"]} coapis-res-drawer-root`}
    >
      {open && chatId ? (
        <ChatSessionResources
          chatId={chatId}
          refreshSignal={refreshSignal}
          onPreview={onPreview}
        />
      ) : null}
      {/* 左缘拖拽把手（360px ~ 容器 90%，松手写 localStorage） */}
      {!isMobile && !embedded && !maximized && (
        <div
          className={styles["coapis-resource-resize-handle"]}
          onMouseDown={startResize}
          title={t("chat.preview.resize", "拖拽调整宽度")}
        />
      )}
    </Drawer>
  );
};

export default CoApisResourceDrawer;
