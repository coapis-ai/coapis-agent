import React from "react";
import { Button, Tag } from "antd";
import {
  PlusOutlined,
  HistoryOutlined,
  CloseOutlined,
  PushpinFilled,
  AppstoreOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
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
  /** 打开历史会话（左侧按钮） */
  onHistoryClick?: () => void;
  /** 新建聊天（左侧按钮） */
  onNewChat?: () => void;
  /** 切换场景（最左侧按钮：打开场景选择面板） */
  onSwitchScene?: () => void;
  /** 浮窗固定状态（嵌入模式：右侧钉子按钮，开=点击外部不关闭） */
  isPinned?: boolean;
  /** 切换浮窗固定状态（嵌入模式） */
  onTogglePin?: () => void;
}

/**
 * 聊天会话顶部栏（v2.2.2 §2.4 对齐）
 * 左侧依次为：「切换场景」按钮（最左）、「历史」按钮、「新聊天」按钮、聊天标题
 * 右侧：嵌入模式（浮窗）控制按钮 —— 钉子（固定开关）+ 关闭
 * 注：模型切换与显示设置在右上角个人下拉菜单；历史会话列表在左侧浮层；
 *     「切换场景」按钮打开 ScenePickerModal（选择场景 → 进入其会话）；
 *     浮窗的展开/最小化按钮已取消，钉子默认开启（点击外部不关闭）。
 */
const ChatSessionHeader: React.FC<ChatSessionHeaderProps> = ({
  isEmbeddedMode,
  onClose,
  sceneName,
  onHistoryClick,
  onNewChat,
  onSwitchScene,
  isPinned,
  onTogglePin,
}) => {
  const { t } = useTranslation();

  return (
    <div className={styles.chatSessionHeader}>
      {/* 左侧：切换场景（最左）+ 历史 + 新聊天 + 标题 */}
      <div className={styles.leftSection}>
        {/* 切换场景（v2.2 修正：会话切换已在历史浮层，顶部按钮=场景选择） */}
        <Button
          type="text"
          size="small"
          icon={<AppstoreOutlined />}
          title={t("chat.header.switchScene")}
          onClick={onSwitchScene}
          className={styles.switchBtn}
        />
        <Button
          type="text"
          size="small"
          icon={<HistoryOutlined />}
          title={t("chat.header.history")}
          onClick={onHistoryClick}
          className={styles.headerActionBtn}
        />
        {/* 新聊天：普通按钮（不默认选中/高亮） */}
        <Button
          type="text"
          size="small"
          icon={<PlusOutlined />}
          title={t("chat.newChat")}
          onClick={onNewChat}
          className={styles.newChatBtn}
        />
        <span className={styles.sessionTitle}>
          {sceneName || t("chat.newChat")}
        </span>
        {sceneName && !isEmbeddedMode && (
          <Tag icon={<PushpinFilled />} color="gold" className={styles.pinned}>
            {t("chat.pinned")}
          </Tag>
        )}
      </div>

      {/* 右侧：嵌入模式控制按钮（钉子 + 关闭） */}
      <div className={styles.rightSection}>
        {isEmbeddedMode && (
          <>
            {/* 钉子：浮窗固定（开=点击外部不关闭），位于「关闭」左边 */}
            {onTogglePin && (
              <Button
                type={isPinned ? "primary" : "text"}
                size="small"
                icon={<PushpinFilled />}
                onClick={onTogglePin}
                className={styles.embeddedControlBtn}
                title={t("chat.pinned")}
              />
            )}
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
          </>
        )}
      </div>
    </div>
  );
};

export default ChatSessionHeader;
