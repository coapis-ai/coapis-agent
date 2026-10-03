import React, { useState } from "react";
import { Button, Dropdown, Tag } from "antd";
import {
  PlusOutlined,
  CloseOutlined,
  CompressOutlined,
  ExpandOutlined,
  PushpinFilled,
  SwapOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import ChatSessionDropdown from "../ChatSessionDropdown";
import styles from "./index.module.less";

interface ChatSessionHeaderProps {
  /** 显示设置回调 */
  onShowDisplaySettings?: () => void;
  /** 是否嵌入模式 */
  isEmbeddedMode: boolean;
  /** 关闭回调（嵌入模式） */
  onClose?: () => void;
  /** 场景名称（嵌入模式） */
  sceneName?: string;
}

/**
 * 聊天会话顶部栏
 * 左侧：会话标题 + 会话快切（设计 §2.4，自旧工具栏迁入）
 * 右侧：新建聊天 / 嵌入控制 / 最小化
 */
const ChatSessionHeader: React.FC<ChatSessionHeaderProps> = ({
  isEmbeddedMode,
  onClose,
  sceneName,
}) => {
  const { t } = useTranslation();
  const [switcherOpen, setSwitcherOpen] = useState(false);

  return (
    <div className={styles.chatSessionHeader}>
      {/* 左侧：会话信息 + 快切 */}
      <div className={styles.leftSection}>
        <span className={styles.sessionTitle}>
          {sceneName || t("chat.newChat")}
        </span>
        {sceneName && (
          <Tag icon={<PushpinFilled />} color="gold" className={styles.pinned}>
            {t("chat.pinned")}
          </Tag>
        )}
        {/* 会话快切（设计 §2.4：位于会话标题旁） */}
        <Dropdown
          open={switcherOpen}
          onOpenChange={setSwitcherOpen}
          placement="bottomLeft"
          trigger={["click"]}
          popupRender={() => (
            <div style={{ width: 320, height: 460, padding: 8 }}>
              <ChatSessionDropdown
                open
                onClose={() => setSwitcherOpen(false)}
                showSearch
              />
            </div>
          )}
        >
          <Button
            type="text"
            size="small"
            icon={<SwapOutlined />}
            title={t("chat.header.switchSession")}
            className={styles.switchBtn}
          />
        </Dropdown>
      </div>

      {/* 右侧：操作按钮 */}
      <div className={styles.rightSection}>
        {/* 新建聊天按钮 */}
        <Button
          type="primary"
          size="small"
          icon={<PlusOutlined />}
          className={styles.newChatBtn}
        >
          {t("chat.newChat")}
        </Button>

        {/* 嵌入模式控制按钮 */}
        {isEmbeddedMode && (
          <>
            {onClose && (
              <Button
                type="text"
                size="small"
                icon={<CloseOutlined />}
                onClick={onClose}
                className={styles.embeddedControlBtn}
                title={t("common.close")}
              />
            )}
            <Button
              type="text"
              size="small"
              icon={<ExpandOutlined />}
              className={styles.embeddedControlBtn}
              title={t("chat.expand")}
            />
            <Button
              type="text"
              size="small"
              icon={<CompressOutlined />}
              className={styles.embeddedControlBtn}
              title={t("chat.minimize")}
            />
          </>
        )}
      </div>
    </div>
  );
};

export default ChatSessionHeader;
