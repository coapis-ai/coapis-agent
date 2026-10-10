import React, { useRef, useState } from "react";
import { Popover } from "antd";
import { IconButton } from "@agentscope-ai/design";
import {
  SparkPlusLine,
  SparkAttachmentLine,
  SparkBookLine,
  SparkApiLine,
} from "@agentscope-ai/icons";
import { FolderOpenOutlined, ThunderboltOutlined } from "@agentscope-ai/icons-override-antd";
import { useTranslation } from "react-i18next";
import { isEnterpriseEdition } from "@/lib/edition";
import styles from "./resource.module.less";

export interface ResourcePlusMenuProps {
  /** 上传文件（点击隐藏的原始上传 trigger） */
  onUploadClick: () => void;
  /** 从我的空间选择 */
  onMySpaceClick: () => void;
  /** 附加知识（仅企业版显示） */
  onKnowledgeClick: () => void;
  /** MCP 服务（引用为芯片） */
  onMcpClick: () => void;
  /** 指定技能（引用为芯片） */
  onSkillClick: () => void;
  disabled?: boolean;
}

/**
 * 技术门槛项开关（v2.2.3）：MCP / 技能 对普通用户太技术，暂时隐藏。
 * 入口代码（openPicker / MultiSelectPickerModal）全部保留，改 true 即恢复。
 * 后续方向：由聊天侧自动触发（自动挂载场景相关的 MCP/技能），不靠用户手选。
 */
const SHOW_TECH_ITEMS = false;

/**
 * M4/T4.1：输入框左下角 "+" 资源菜单（取代原回形针）。
 *
 * 设计原则（v2.2.3 修正）：本菜单只放"输入类资源"——
 * 上传文件 / 我的空间 / 关联知识（企业版）/ 聊天模型。
 * - 切换场景：归顶部按钮（AppstoreOutlined），菜单里取消，避免两个入口。
 * - MCP / 技能：对普通用户有技术门槛，暂时隐藏（见 SHOW_TECH_ITEMS），
 *   方向是聊天侧自动触发，不靠用户手选。
 * - 模型：菜单里保留入口（弹窗选择，写入用户全局偏好）；右上角个人菜单
 *   也有模型子菜单，两处写同一份偏好，不会互相打架。
 * 会话管理（历史、新聊天）归顶部按钮；显示设置归右上角个人菜单。
 *
 * 注意：本组件整体位于 Sender 的 attachments.trigger 插槽内（被 antd Upload 包裹）。
 * - 「上传」快捷按钮与菜单里的「上传文件」项【不能】stopPropagation，
 *   点击会冒泡到外层 antd Upload，从而打开原生文件选择（保留 Sender 原生上传流）。
 * - 其余可点元素（+ 按钮、我的空间、知识、菜单项）一律 stopPropagation，
 *   避免误触发文件选择对话框。
 */
export default function ResourcePlusMenu(props: ResourcePlusMenuProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const showKnowledge = isEnterpriseEdition();
  // 「上传」入口的包装节点：菜单里的「上传文件」项通过程序化点击它来触发原生上传
  const attachRef = useRef<HTMLSpanElement>(null);

  const stop = (e: React.MouseEvent) => e.stopPropagation();

  const menuItem = (
    label: string,
    icon: React.ReactNode,
    onClick: () => void,
  ) => (
    <div
      className={styles.pickRow}
      role="menuitem"
      tabIndex={0}
      onClick={(e) => {
        stop(e);
        setOpen(false);
        onClick();
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.stopPropagation();
          setOpen(false);
          onClick();
        }
      }}
    >
      <span className={styles.menuItemIcon}>{icon}</span>
      <span>{label}</span>
    </div>
  );

  const menuContent = (
    <div style={{ width: 220, padding: "6px 0" }}>
      <div
        className={styles.pickRow}
        role="menuitem"
        tabIndex={0}
        onClick={() => attachRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.stopPropagation();
            attachRef.current?.click();
          }
        }}
      >
        <span className={styles.menuItemIcon}>
          <SparkAttachmentLine />
        </span>
        <span>{t("resourceMenu.upload")}</span>
      </div>
      {menuItem(t("resourceMenu.mySpace"), <FolderOpenOutlined />, props.onMySpaceClick)}
      {showKnowledge &&
        menuItem(t("resourceMenu.knowledge"), <SparkBookLine />, props.onKnowledgeClick)}
      {SHOW_TECH_ITEMS && (
        <>
          <div style={{ height: 1, background: "var(--color-border-secondary, rgba(0,0,0,0.06))", margin: "6px 0" }} />
          {menuItem(t("resourceMenu.mcp"), <SparkApiLine />, props.onMcpClick)}
          {menuItem(t("resourceMenu.skill"), <ThunderboltOutlined />, props.onSkillClick)}
        </>
      )}
    </div>
  );

  return (
    <span
      className={styles.cluster}
    >
      <Popover
        content={menuContent}
        trigger="click"
        placement="topLeft"
        open={open}
        onOpenChange={(v) => setOpen(v)}
        overlayStyle={{ zIndex: 1200 }}
      >
        <IconButton
          bordered={false}
          size="small"
          className={styles.plusButton}
          icon={<SparkPlusLine />}
          disabled={props.disabled}
          onClick={stop}
          data-testid="chat-resource-plus"
        />
      </Popover>
      <span ref={attachRef}>
        <IconButton
          bordered={false}
          size="small"
          className={styles.quickButton}
          icon={<SparkAttachmentLine />}
          disabled={props.disabled}
          title={t("resourceMenu.upload")}
          onClick={() => props.onUploadClick()}
          data-testid="chat-quick-upload"
        />
      </span>
      <IconButton
        bordered={false}
        size="small"
        className={styles.quickButton}
        icon={<FolderOpenOutlined />}
        disabled={props.disabled}
        title={t("resourceMenu.mySpace")}
        onClick={(e) => {
          stop(e);
          props.onMySpaceClick();
        }}
        data-testid="chat-quick-myspace"
      />
      {showKnowledge && (
        <IconButton
          bordered={false}
          size="small"
          className={styles.quickButton}
          icon={<SparkBookLine />}
          disabled={props.disabled}
          title={t("resourceMenu.knowledge")}
          onClick={(e) => {
            stop(e);
            props.onKnowledgeClick();
          }}
          data-testid="chat-quick-knowledge"
        />
      )}
    </span>
  );
}
