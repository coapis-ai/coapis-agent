import { RefreshCw } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import ChatSessionResources from "./ChatSessionResources";
import FloatingWindow from "./FloatingWindow";
import styles from "./CoApisResourceDrawer.module.less";
import type { ResourcePreviewRequest } from "./CoApisChatResourceBar";

/**
 * 会话资源浮窗（B4，PRD v2.2.2 §2.3「会话文件面板」）。
 *
 * 浮窗几何、头部拖动、八向缩放、位置尺寸记忆、铺满/还原、Esc/点外关闭全部由
 * 共用骨架 FloatingWindow 提供（与预览窗同一套行为，G1=A）；本文件只负责「会
 * 话资源」这件事：标题、刷新、内容。
 */
interface CoApisResourceDrawerProps {
  open: boolean;
  chatId?: string | null;
  /** v17 · F4：作用域 —— "chat"=当前聊天；"session"=当前会话（跨聊天）。
   *  由右侧资源条那块决定，抽屉标题跟着走，绝不"条显示会话、抽屉显示聊天"。 */
  scope?: "chat" | "session";
  /** 台账写入后父组件自增，触发列表刷新。 */
  refreshSignal?: number;
  onClose: () => void;
  onPreview: (req: ResourcePreviewRequest) => void;
  /** 浮窗锚定的宿主容器（与预览窗同口径：铺满主内容区）。 */
  getContainer?: () => HTMLElement | null;
}

export default function CoApisResourceDrawer({
  open,
  chatId,
  scope = "chat",
  refreshSignal,
  onClose,
  onPreview,
  getContainer,
}: CoApisResourceDrawerProps) {
  const { t } = useTranslation();
  // 父组件的 refreshSignal 只在台账写入时自增；用户手动刷新靠本地 tick
  const [tick, setTick] = useState(0);
  // v17 · F5（小蜜蜂「左侧栏的组标题没有显示」）：标题 = 组标题 + 资源名，
  // 一眼知道"这是哪一组"。上半区=当前会话，下半区=当前聊天。
  const groupTitle =
    scope === "session"
      ? t("chat.resources.groupSession", "当前会话")
      : t("chat.resources.groupChat", "当前聊天");
  const winTitle = `${groupTitle} · ${t("chat.resources.drawerTitle", "会话资源")}`;

  return (
    <FloatingWindow
      open={open}
      storageKey="resourceWin"
      getContainer={getContainer}
      label={winTitle}
      closeTip={t("chat.resources.close", "关闭")}
      defaultWidth={480}
      defaultHeight={640}
      minWidth={360}
      minHeight={320}
      onClose={onClose}
      closeOnClickOutside
      outsideIgnoreSelector="[data-coapis-res-trigger]"
      title={
        <>
          <span className={styles["coapis-res-title"]} title={winTitle}>
            {winTitle}
          </span>
        </>
      }
      extra={
        <button
          type="button"
          className={styles["coapis-res-btn"]}
          onClick={() => setTick((v) => v + 1)}
          title={t("chat.resources.refresh", "刷新")}
          aria-label={t("chat.resources.refresh", "刷新")}
        >
          <RefreshCw size={13} />
        </button>
      }
      bodyClassName={styles["coapis-res-body"]}
    >
      <ChatSessionResources
        chatId={chatId ?? undefined}
        scope={scope}
        refreshSignal={(refreshSignal ?? 0) + tick}
        onPreview={onPreview}
      />
    </FloatingWindow>
  );
}
