import React, { useMemo, useRef, useState } from "react";
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
import CascadeMenu from "@/components/CascadeMenu/CascadeMenu";
import type { CascadeNode } from "@/components/CascadeMenu/CascadeMenu";
import { useNarrow } from "@/components/CascadeMenu/useNarrow";
import {
  cascadeLoad,
  SESSION_ROOT_KEY,
  SPACE_ROOT_KEY,
  KB_ROOT_KEY,
} from "./cascadeAdapters";
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
  /** 打开浮层（跨目录搜索 / 知识库选择） */
  onOpenModal: (mode: "files" | "knowledge") => void;
  /** 勾选集合：文件用后端全路径，知识库用 `kb:<id>` */
  checked: Set<string>;
  /** 勾选/取消勾选（D4：点一下即生效，无确认按钮） */
  onToggle: (node: CascadeNode) => void;
  chatId?: string;
  sessionCount: number;
  disabled?: boolean;
}

/**
 * M4/T4.1：输入框左下角 "+" 资源菜单。
 *
 * 一级行（点击才展开，D1）：本会话文件 / 我的空间 / 关联知识（企业版）。
 * 点击后在【右侧】以列式级联展开目录结构（hover 200ms 预展开，D5），
 * 目录行可勾选 = 目录引用（D2），文件行点行即加入/移出会话引用（D4）。
 * 「＋ 上传新文件」行点击冒泡到外层 antd Upload，走原生文件选择。
 * 「🔍 搜索全部文件…」打开浮层——跨目录检索在浮层做，菜单层不做（D3）。
 * 菜单里不显示台账（台账是账本视图，属于浮层）。
 *
 * 注意：本组件整体位于 Sender 的 attachments.trigger 插槽内（被 antd Upload 包裹）。
 * - 「上传」快捷按钮与「＋ 上传新文件」行【不能】stopPropagation，
 *   点击会冒泡到外层 antd Upload，从而打开原生文件选择（保留 Sender 原生上传流）。
 * - 其余可点元素（+ 按钮、菜单项、勾选行）一律 stopPropagation，
 *   避免误触发文件选择对话框。
 */
export default function ResourcePlusMenu(props: ResourcePlusMenuProps) {
  const { t } = useTranslation();
  const narrow = useNarrow();
  const [open, setOpen] = useState(false);
  // 「上传」入口的包装节点：菜单里的上传行通过程序化点击它来触发原生上传
  const attachRef = useRef<HTMLSpanElement>(null);
  const showKnowledge = isEnterpriseEdition();

  const stop = (e: React.MouseEvent) => e.stopPropagation();

  const roots = useMemo(() => {
    const rows: CascadeNode[] = [
      {
        key: SESSION_ROOT_KEY,
        name: t("resourceMenu.sessionFiles"),
        kind: "group",
        meta: props.sessionCount ? String(props.sessionCount) : undefined,
      },
      {
        key: SPACE_ROOT_KEY,
        name: t("resourceMenu.mySpace"),
        kind: "group",
      },
    ];
    if (showKnowledge) {
      rows.push({
        key: KB_ROOT_KEY,
        name: t("resourceMenu.knowledge"),
        kind: "group",
      });
    }
    rows.push({ key: "divider", name: "", kind: "divider" });
    // 上传行：bubble=true，点击冒泡到外层 Upload 打开原生文件选择
    rows.push({
      key: "action:upload",
      name: t("resourceMenu.uploadNew"),
      kind: "action",
      bubble: true,
      onAction: () => {
        setOpen(false);
        attachRef.current?.click();
      },
    });
    rows.push({
      key: "action:search",
      name: t("resourceMenu.searchAll"),
      kind: "action",
      onAction: () => {
        setOpen(false);
        props.onOpenModal("files");
      },
    });
    return rows;
  }, [t, showKnowledge, props.sessionCount, props.onOpenModal]);

  const load = useMemo(
    () =>
      (node: CascadeNode, force?: boolean) =>
        cascadeLoad(node, props.chatId, force),
    [props.chatId],
  );

  const menuContent = (
    <div style={{ padding: "4px 0" }}>
      <CascadeMenu
        roots={roots}
        load={load}
        checked={props.checked}
        onToggle={props.onToggle}
        height={narrow ? 260 : 320}
        rootWidth={narrow ? 150 : 168}
        narrow={narrow}
        portal
      />
    </div>
  );

  return (
    <span className={styles.cluster}>
      <Popover
        content={menuContent}
        trigger="click"
        placement="topLeft"
        open={open}
        onOpenChange={setOpen}
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
          props.onOpenModal("files");
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
            props.onOpenModal("knowledge");
          }}
          data-testid="chat-quick-knowledge"
        />
      )}
    </span>
  );
}
