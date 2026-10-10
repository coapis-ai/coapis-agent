import React, { useRef, useState } from "react";
import { Popover } from "antd";
import { IconButton } from "@agentscope-ai/design";
import {
  SparkPlusLine,
  SparkAttachmentLine,
  SparkBookLine,
} from "@agentscope-ai/icons";
import { FolderOpenOutlined } from "@agentscope-ai/icons-override-antd";
import { useTranslation } from "react-i18next";
import { isEnterpriseEdition } from "@/lib/edition";
import styles from "./resource.module.less";

/** 台账行（本会话文件）—— 与 /myfiles/records 的返回字段对齐 */
export interface SessionFile {
  path: string;
  name: string;
  size?: number;
  source: string;
  created_at?: string | number | null;
  mime_type?: string;
}

export interface ResourcePlusMenuProps {
  /** 上传文件（点击隐藏的原始上传 trigger） */
  onUploadClick: () => void;
  /** 我的空间 → 文件树（弹窗） */
  onMySpaceClick: () => void;
  /** 我的空间 → 最近使用（弹窗，台账视图） */
  onRecentClick: () => void;
  /** 我的空间 → 本会话（弹窗，台账视图 + chat_id 过滤） */
  onSessionModalClick: () => void;
  /** 附加知识（仅企业版显示） */
  onKnowledgeClick: () => void;
  /** 本会话文件列表（按 chat_id 过滤的台账行） */
  sessionFiles: SessionFile[];
  /** 勾选/取消勾选（D4：点一下即生效，无确认按钮） */
  onToggleSessionFile: (f: SessionFile) => void;
  /** 已选路径集合，用于渲染勾选态 */
  selectedPaths: Set<string>;
  disabled?: boolean;
}

/**
 * M4/T4.1：输入框左下角 "+" 资源菜单（取代原回形针）。
 *
 * 设计原则（v2.2.4 两级菜单）：本菜单只放"输入类资源"，两级 + 勾选。
 * - 一级：本会话文件 / 我的空间 / 关联知识（企业版）。
 * - 二级（本会话文件）：勾选列表（点一下即加入/移出会话引用，D4）
 *   + 底部「＋ 上传新文件」行。
 * - 二级（我的空间）：最近使用 / 本会话 / 全部文件 —— 三项都打开弹窗，
 *   因为文件树浏览、搜索、大量条目勾选在下拉菜单里做不好（D3）。
 * - MCP / 技能：已删除（D6）。入口代码与弹窗一并移除，不再保留开关。
 * - 切换场景：归顶部按钮（AppstoreOutlined），菜单里取消，避免两个入口。
 * - 模型：归语音按钮左侧芯片，菜单里不再有入口。
 * 会话管理（历史、新聊天）归顶部按钮；显示设置归右上角个人菜单。
 *
 * 注意：本组件整体位于 Sender 的 attachments.trigger 插槽内（被 antd Upload 包裹）。
 * - 「上传」快捷按钮与「＋ 上传新文件」行【不能】stopPropagation，
 *   点击会冒泡到外层 antd Upload，从而打开原生文件选择（保留 Sender 原生上传流）。
 * - 其余可点元素（+ 按钮、菜单项、勾选行）一律 stopPropagation，
 *   避免误触发文件选择对话框。
 */
const SOURCE_LABEL: Record<string, string> = {
  upload: "上传",
  write_file: "生成",
  edit_file: "编辑",
  append_file: "追加",
  reconcile: "对账",
};

function sizeLabel(n?: number): string {
  if (!n) return "";
  if (n < 1024) return `${n}B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)}K`;
  return `${(n / 1024 / 1024).toFixed(1)}M`;
}

export default function ResourcePlusMenu(props: ResourcePlusMenuProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [sub, setSub] = useState<null | "session" | "space">(null);
  const showKnowledge = isEnterpriseEdition();
  // 「上传」入口的包装节点：菜单里的上传行通过程序化点击它来触发原生上传
  const attachRef = useRef<HTMLSpanElement>(null);

  const stop = (e: React.MouseEvent) => e.stopPropagation();

  const close = () => {
    setOpen(false);
    setSub(null);
  };

  const row = (
    label: string,
    icon: React.ReactNode,
    onClick: () => void,
    extra?: React.ReactNode,
    allowBubble = false,
  ) => (
    <div
      className={styles.pickRow}
      role="menuitem"
      tabIndex={0}
      onClick={(e) => {
        if (!allowBubble) stop(e);
        onClick();
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          if (!allowBubble) e.stopPropagation();
          onClick();
        }
      }}
    >
      <span className={styles.menuItemIcon}>{icon}</span>
      <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>
        {label}
      </span>
      {extra}
    </div>
  );

  const backRow = (
    <div
      className={styles.pickRow}
      style={{ color: "var(--color-text-tertiary, rgba(0,0,0,0.45))" }}
      role="menuitem"
      tabIndex={0}
      onClick={(e) => {
        stop(e);
        setSub(null);
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.stopPropagation();
          setSub(null);
        }
      }}
    >
      <span className={styles.menuItemIcon}>←</span>
      <span>{t("resourceMenu.back")}</span>
    </div>
  );

  const divider = (
    <div
      style={{
        height: 1,
        background: "var(--color-border-secondary, rgba(0,0,0,0.06))",
        margin: "6px 0",
      }}
    />
  );

  const level1 = (
    <>
      {row(
        t("resourceMenu.sessionFiles"),
        <SparkAttachmentLine />,
        () => setSub("session"),
        props.sessionFiles.length > 0 ? (
          <span style={{ color: "var(--color-text-tertiary, rgba(0,0,0,0.45))", fontSize: 12 }}>
            {props.sessionFiles.length}
          </span>
        ) : null,
      )}
      {row(t("resourceMenu.mySpace"), <FolderOpenOutlined />, () => setSub("space"))}
      {showKnowledge &&
        row(t("resourceMenu.knowledge"), <SparkBookLine />, () => {
          close();
          props.onKnowledgeClick();
        })}
    </>
  );

  const sessionPanel = (
    <>
      {backRow}
      {divider}
      {props.sessionFiles.length === 0 ? (
        <div
          style={{
            padding: "8px 12px",
            color: "var(--color-text-tertiary, rgba(0,0,0,0.45))",
            fontSize: 12,
          }}
        >
          {t("resourceMenu.noSessionFiles")}
        </div>
      ) : (
        <div style={{ maxHeight: 220, overflowY: "auto" }}>
          {props.sessionFiles.map((f) => {
            const checked = props.selectedPaths.has(f.path);
            return (
              <div
                key={f.path}
                className={styles.pickRow}
                role="checkbox"
                aria-checked={checked}
                tabIndex={0}
                onClick={(e) => {
                  stop(e);
                  props.onToggleSessionFile(f);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.stopPropagation();
                    props.onToggleSessionFile(f);
                  }
                }}
              >
                <span
                  style={{
                    width: 14,
                    height: 14,
                    borderRadius: 3,
                    border: checked
                      ? "1px solid transparent"
                      : "1px solid var(--color-border, rgba(0,0,0,0.15))",
                    background: checked
                      ? "var(--color-primary, #1677ff)"
                      : "transparent",
                    flexShrink: 0,
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    color: "#fff",
                    fontSize: 10,
                  }}
                >
                  {checked ? "✓" : ""}
                </span>
                <span
                  style={{
                    flex: 1,
                    minWidth: 0,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}
                  title={f.path}
                >
                  {f.name}
                </span>
                <span
                  style={{
                    color: "var(--color-text-tertiary, rgba(0,0,0,0.45))",
                    fontSize: 11,
                    flexShrink: 0,
                  }}
                >
                  {SOURCE_LABEL[f.source] ?? f.source}
                  {sizeLabel(f.size) ? ` · ${sizeLabel(f.size)}` : ""}
                </span>
              </div>
            );
          })}
        </div>
      )}
      {divider}
      {/* 不能 stopPropagation：点击需冒泡到外层 antd Upload 打开原生文件选择 */}
      {row(
        t("resourceMenu.uploadNew"),
        <SparkAttachmentLine />,
        () => {
          setOpen(false);
          attachRef.current?.click();
        },
        null,
        true,
      )}
    </>
  );

  const spacePanel = (
    <>
      {backRow}
      {divider}
      {row(t("resourcePicker.recent"), <SparkBookLine />, () => {
        setOpen(false);
        props.onRecentClick();
      })}
      {row(t("resourceMenu.sessionFiles"), <SparkAttachmentLine />, () => {
        setOpen(false);
        props.onSessionModalClick();
      })}
      {row(t("resourceMenu.mySpaceAll"), <FolderOpenOutlined />, () => {
        setOpen(false);
        props.onMySpaceClick();
      })}
    </>
  );

  const menuContent = (
    <div style={{ width: 240, padding: "6px 0" }}>
      {sub === null ? level1 : sub === "session" ? sessionPanel : spacePanel}
    </div>
  );

  return (
    <span className={styles.cluster}>
      <Popover
        content={menuContent}
        trigger="click"
        placement="topLeft"
        open={open}
        onOpenChange={(v) => {
          setOpen(v);
          if (!v) setSub(null);
        }}
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
