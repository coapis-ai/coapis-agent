import React from "react";
import { Button, Tooltip } from "antd";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { useTranslation } from "react-i18next";
import ChatSessionDropdown from "../ChatSessionDropdown";
import ChatSessionResourcesInline from "../ChatSessionResources/Inline";
import styles from "./index.module.less";

interface Props {
  collapsed: boolean;
  onToggleCollapsed: (collapsed: boolean) => void;
  /** 当前会话的后端 chat id：判定哪一行是「当前会话」并挂它的资源下拉。 */
  currentBackendId?: string | null;
  /** 预览文件（走页面级预览抽屉）。 */
  onPreview?: (path: string, title: string) => void;
  /** 打开 L3 资源抽屉（左栏下拉里的「查看全部」）。 */
  onShowAll?: () => void;
  /** 台账写入后自增，让当前会话的资源下拉立刻重取。 */
  resourceRefresh?: number;
}

/**
 * 固定左栏（批次 D1/D2）—— 会话列表常驻在聊天区左侧。
 *
 * 取代原来的「顶栏历史按钮 → 绝对定位浮层盖在聊天区上」：浮层会挡住对话、
 * 关不掉就看不见会话，且没法把资源挂在会话名下。
 *
 * 资源的位置（批次 D2）：本会话的引用/生成清单挂在**当前会话那一行下方**的
 * 下拉里，与会话同属一体；左栏顶部不放资源入口——那会把资源和会话割裂成两块。
 * 未选中的会话不显示资源。逐条资源的完整表格在 L2 资源条「查看全部」打开的
 * 抽屉（L3）里，这里不重复做一套。
 */
const ChatSessionSidebar: React.FC<Props> = (props) => {
  const {
    collapsed,
    onToggleCollapsed,
    currentBackendId,
    onPreview,
    onShowAll,
    resourceRefresh = 0,
  } = props;
  const { t } = useTranslation();

  if (collapsed) {
    return (
      <aside className={styles.rail}>
        <Tooltip title={t("chat.sidebar.expand")} placement="right">
          <Button
            type="text"
            className={styles.collapseBtn}
            aria-label={t("chat.sidebar.expand")}
            icon={<PanelLeftOpen size={16} />}
            onClick={() => onToggleCollapsed(false)}
          />
        </Tooltip>
      </aside>
    );
  }

  return (
    <aside className={styles.sidebar}>
      <div className={styles.head}>
        <span className={styles.title}>{t("chat.sidebar.title")}</span>
        <span className={styles.headActions}>
          <Tooltip title={t("chat.sidebar.collapse")} placement="bottom">
            <Button
              type="text"
              size="small"
              className={styles.collapseBtn}
              aria-label={t("chat.sidebar.collapse")}
              icon={<PanelLeftClose size={15} />}
              onClick={() => onToggleCollapsed(true)}
            />
          </Tooltip>
        </span>
      </div>

      <div className={styles.body}>
        <ChatSessionDropdown
          variant="sidebar"
          currentBackendId={currentBackendId}
          renderItemExtra={(_session, backendId) => (
            <ChatSessionResourcesInline
              chatId={backendId}
              refreshKey={resourceRefresh}
              onPreview={onPreview}
              onShowAll={onShowAll}
            />
          )}
        />
      </div>
    </aside>
  );
};

export default ChatSessionSidebar;
