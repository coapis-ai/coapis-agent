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
  refreshSignal,
  onClose,
  onPreview,
  getContainer,
}: CoApisResourceDrawerProps) {
  const { t } = useTranslation();
  // 父组件的 refreshSignal 只在台账写入时自增；用户手动刷新靠本地 tick
  const [tick, setTick] = useState(0);

  return (
    <FloatingWindow
      open={open}
      storageKey="resourceWin"
      getContainer={getContainer}
      label={t("chat.resources.drawerTitle", "会话资源")}
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
          <span className={styles["coapis-res-title"]}>
            {t("chat.resources.drawerTitle", "会话资源")}
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
        refreshSignal={(refreshSignal ?? 0) + tick}
        onPreview={onPreview}
      />
    </FloatingWindow>
  );
}
