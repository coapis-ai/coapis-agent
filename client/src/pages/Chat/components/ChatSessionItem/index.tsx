import React from "react";
import { Tooltip } from "antd";
import {
  SparkDeleteLine,
  SparkEditLine,
  SparkMarkFill,
  SparkMarkLine,
} from "@agentscope-ai/icons";
import { useTranslation } from "react-i18next";
import styles from "./index.module.less";

interface ChatSessionItemProps {
  /** Backend chat id (UUID) when the session is backed by a real chat. */
  sessionId: string;
  name: string;
  /** Compact time string, formatted by the list (time today, day, date). */
  time: string;
  /** Raw channel key, used to look up the channel icon. */
  channelKey?: string;
  /** Localized channel label shown in the tag. */
  channelLabel?: string;
  /** Chat running status: running / idle / failed. */
  chatStatus?: string;
  /** True while this chat is generating a response. */
  generating?: boolean;
  /**
   * Raw creation timestamp, only for the title tooltip — the row shows the
   * compact `time` string.
   */
  createdAt?: string | null;
  /**
   * 批次 B2：标题行末尾的插槽。当前会话行放「展开会话资源」的 caret。
   * 非当前会话传 undefined —— 没有资源面板的行不该有可点的控件。
   */
  expandSlot?: React.ReactNode;
  active: boolean;
  editing: boolean;
  editValue?: string;
  pinned: boolean;
  onClick: (sessionId: string) => void;
  onEdit: (sessionId: string, currentName: string) => void;
  onDelete: (sessionId: string) => void;
  onPin: (sessionId: string) => void;
  onEditChange: (value: string) => void;
  onEditSubmit: () => void;
  onEditCancel: () => void;
  /** 右键菜单（编辑/删除/置顶），替代原来挤在标题上的图标 */
  onContextMenu?: (sessionId: string, event: React.MouseEvent) => void;
}

/** 紧凑时间：今天 "14:29"，本年 "10-23 14:29"，跨年 "2025-10-23"。 */
export function formatCreatedAt(
  iso: string | null | undefined,
): string | undefined {
  if (!iso) return undefined;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return undefined;
  const pad = (n: number) => String(n).padStart(2, "0");
  const time = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  if (sameDay) return time;
  const md = `${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  return d.getFullYear() === today.getFullYear() ? `${md} ${time}` : md;
}

/** Full timestamp for the title tooltip. */
function fullTime(iso: string | null | undefined): string | undefined {
  if (!iso) return undefined;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return undefined;
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}`
  );
}

const ChatSessionItem: React.FC<ChatSessionItemProps> = (props) => {
  const { t } = useTranslation();

  // Running status dot: green pulse = generating, green = active, red = failed.
  const statusClass =
    props.chatStatus === "running" || props.generating
      ? styles.statusDotRunning
      : props.chatStatus === "failed"
      ? styles.statusDotFailed
      : props.active
      ? styles.statusDotActive
      : styles.statusDotIdle;

  const statusTip =
    props.chatStatus === "running" || props.generating
      ? t("chat.statusRunning", "生成中")
      : props.chatStatus === "failed"
      ? t("chat.statusFailed", "失败")
      : t("chat.statusIdle", "空闲");

  const stop = (e: React.MouseEvent) => e.stopPropagation();

  const titleTip = props.createdAt
    ? `${props.name} · ${fullTime(props.createdAt)}`
    : props.name;

  return (
    <div
      className={`${styles.chatSessionItem} ${
        props.active ? styles.active : ""
      } ${props.editing ? styles.editing : ""}`}
      onClick={() => !props.editing && props.onClick(props.sessionId)}
      onContextMenu={(e) => {
        if (props.editing) return;
        e.preventDefault();
        props.onContextMenu?.(props.sessionId, e);
      }}
    >
      <div className={styles.iconPlaceholder} />

      <div className={styles.content}>
        {/* 第一行：标题 + 状态点 +（当前会话）展开 caret */}
        <div className={styles.titleRow}>
          <Tooltip title={titleTip} mouseEnterDelay={0.6}>
            <span className={styles.name}>{props.name}</span>
          </Tooltip>
          <span className={styles.statusWrap} onClick={stop}>
            <Tooltip title={statusTip} mouseEnterDelay={0.4}>
              <span className={`${styles.statusDot} ${statusClass}`} />
            </Tooltip>
          </span>
          {props.expandSlot}
        </div>

        {/* 第二行：日期 + 渠道标签 */}
        <div className={styles.metaRow}>
          <span className={styles.time}>{props.time}</span>
          {props.channelKey && (
            <span className={styles.channelTag} onClick={stop}>
              <span className={styles.channelTagText}>
                {props.channelLabel || props.channelKey}
              </span>
            </span>
          )}
        </div>

        {/* 第三行（批次 B3）：置顶 + 编辑 + 删除独占一行。
            之前是 position:absolute 叠在标题右上角 —— 用户反馈"按钮重叠在
            标题上"。常驻占位（opacity 0）保证行高恒定，hover 才显色。 */}
        <div className={styles.actionRow} onClick={stop}>
          <Tooltip
            title={
              props.pinned
                ? t("chat.unpinSession", "取消置顶")
                : t("chat.pinSession", "置顶")
            }
            mouseEnterDelay={0.5}
          >
            <span
              className={`${styles.pinIcon} ${
                props.pinned ? styles.pinnedIcon : ""
              }`}
              role="button"
              aria-label={
                props.pinned
                  ? t("chat.unpinSession", "取消置顶")
                  : t("chat.pinSession", "置顶")
              }
              onClick={(e) => {
                e.stopPropagation();
                props.onPin(props.sessionId);
              }}
            >
              {props.pinned ? <SparkMarkFill /> : <SparkMarkLine />}
            </span>
          </Tooltip>
          <div className={styles.actions}>
            <Tooltip
              title={t("chat.renameTooltip", "重命名")}
              mouseEnterDelay={0.5}
            >
              <button
                type="button"
                className={styles.actionBtn}
                aria-label={t("chat.renameTooltip", "重命名")}
                onClick={(e) => {
                  e.stopPropagation();
                  props.onEdit(props.sessionId, props.name);
                }}
              >
                <SparkEditLine />
              </button>
            </Tooltip>
            <Tooltip
              title={t("chat.deleteTooltip", "删除")}
              mouseEnterDelay={0.5}
            >
              <button
                type="button"
                className={`${styles.actionBtn} ${styles.dangerBtn}`}
                aria-label={t("chat.deleteTooltip", "删除")}
                onClick={(e) => {
                  e.stopPropagation();
                  props.onDelete(props.sessionId);
                }}
              >
                <SparkDeleteLine />
              </button>
            </Tooltip>
          </div>
        </div>
      </div>

      {props.editing && (
        <input
          autoFocus
          className={styles.editInput}
          value={props.editValue ?? ""}
          onClick={stop}
          onChange={(e) => props.onEditChange(e.target.value)}
          onBlur={props.onEditSubmit}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              props.onEditSubmit();
            } else if (e.key === "Escape") {
              e.preventDefault();
              props.onEditCancel();
            }
          }}
        />
      )}
    </div>
  );
};

export default ChatSessionItem;
