import React from "react";
import { Drawer } from "antd";
import { useTranslation } from "react-i18next";
import ChatSessionResources from "./ChatSessionResources";
import type { ResourcePreviewRequest } from "./CoApisChatResourceBar";

interface Props {
  open: boolean;
  chatId: string | undefined;
  onClose: () => void;
  refreshSignal?: number;
  onPreview?: (req: ResourcePreviewRequest) => void;
}

/**
 * 会话资源抽屉（方案 §3.2 L3 / §12.4）
 * ---------------------------------------------------------------------------
 * 右侧抽屉，全量清单：类型筛选 / 关键词搜索 / 时间排序 / 分页尾巴，
 * 状态标签（已发布·未发布·已迁移·已删除·已失效），「在我的空间定位」。
 *
 * 入口两个（方案原文）：会话右上角「资源」图标、本轮资源条尾部「查看全部」。
 */
const CoApisResourceDrawer: React.FC<Props> = ({
  open,
  chatId,
  onClose,
  refreshSignal = 0,
  onPreview,
}) => {
  const { t } = useTranslation();
  return (
    <Drawer
      title={t("chat.resources.drawerTitle", "会话资源")}
      placement="right"
      width={640}
      open={open}
      onClose={onClose}
      destroyOnClose
      styles={{ body: { padding: "12px 16px" } }}
    >
      {open && chatId ? (
        <ChatSessionResources
          chatId={chatId}
          refreshSignal={refreshSignal}
          onPreview={onPreview}
        />
      ) : null}
    </Drawer>
  );
};

export default CoApisResourceDrawer;
