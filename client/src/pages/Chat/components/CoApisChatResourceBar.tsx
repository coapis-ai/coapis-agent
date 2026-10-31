import React, { useMemo, useState } from "react";
import { Dropdown, Tag, Tooltip } from "antd";
import type { MenuProps } from "antd";
import {
  AppstoreOutlined,
  AimOutlined,
  DownloadOutlined,
  DownOutlined,
  EyeOutlined,
  FileTextOutlined,
  GlobalOutlined,
  RightOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import type { ChatResourceItem } from "../../../api/modules/chat";
import {
  displayName,
  stemName,
} from "./ChatSessionResources/helpers";
import {
  toLedgerRelPath,
  getPreviewKind,
  convertTargetsFor,
  downloadFile,
  previewFile,
} from "../../../utils/webPreview";
import styles from "./CoApisChatResourceBar.module.css";

const KIND_ICON: Record<string, React.ReactNode> = {
  file: <FileTextOutlined />,
  web: <GlobalOutlined />,
  kb: <FileTextOutlined style={{ color: "#722ed1" }} />,
  mcp: <FileTextOutlined style={{ color: "#fa8c16" }} />,
  db: <FileTextOutlined style={{ color: "#13c2c2" }} />,
};

/** 状态词表（与 L3 完全一致，方案 §3.2 / §12.4 验收项 1） */
const STATUS_META: Record<string, { label: string; color: string }> = {
  official: { label: "statusPublished", color: "green" },
  draft: { label: "statusDraft", color: "default" },
  orphan: { label: "statusMoved", color: "orange" },
  archived: { label: "statusArchived", color: "purple" },
  deleted: { label: "statusDeleted", color: "red" },
  missing: { label: "statusMissing", color: "red" },
};

/**
 * 只有「出事了」的状态才渲染标签。
 *
 * 台账的 `draft` 是产出物的**出厂默认**（用户确认/投递后才升 official），
 * `orphan` 是「已不被任何会话引用」的常态——dev 实测 346 行台账里
 * draft 105 + orphan 214 + official 0，给它们打标签等于每一行都挂个
 * 「未发布」，用户读成「这东西没做好」，纯噪音。
 * 因此 L2/L3 统一：archived / deleted / missing 才出标签。
 */
export const TAGGED_STATUSES: ReadonlySet<string> = new Set([
  "archived",
  "deleted",
  "missing",
]);

/** 一行资源现在算什么状态：软删 > 磁盘失效 > 台账状态。 */
export function resourceStatusOf(item: ChatResourceItem): string {
  if (item.deleted || item.status === "deleted") return "deleted";
  if (item.kind === "file" && item.exists === false) return "missing";
  return item.status || "draft";
}

export interface ResourcePreviewRequest {
  path: string;
  name: string;
  source: "produced" | "reference";
}

interface Props {
  /**
   * 本轮资源（方案 §3.2 L2 = 答案气泡末尾的**本轮**引用+产出摘要）。
   * 由消息 metadata 提供，台账 meta 合并进来（大小/时间/版本/状态）。
   */
  items: ChatResourceItem[];
  /** 会话级抽屉（方案 §12.4）：预览走抽屉，不退化成新窗口 */
  onPreview?: (req: ResourcePreviewRequest) => void;
  /** 「查看全部」→ 打开会话资源抽屉（L3） */
  onShowAll?: () => void;
  /** 「判断」→ 打开判断中枢浮窗（v14 §5.2：本轮判断台账 + 判官开关） */
  onJudgment?: () => void;
  /** 「定位到消息」：滚到产出这条资源的那一轮（方案 §3.2 产出动作） */
  onLocate?: (messageId: string) => void;
}

/** 每组最多 8 行，其余折叠成「展开其余 N 项」（方案 §3.2 L2）。 */
const GROUP_CAP = 8;

/**
 * 本轮资源条（方案 §3.2 L2 / §12.4）
 * ---------------------------------------------------------------------------
 * 挂在**答案气泡末尾**（`chat-resources` 插件位，order 14），显示本轮全部
 * 引用 + 产出：分角色计数、引用/产出分组、每组 8 行 +「展开其余 N 项」、
 * 来源标签、状态标签、行右侧 [预览]/[下载]/[转格式]，尾部「查看全部」。
 * 默认折叠成单行摘要（方案：默认折叠，单行 28px）；本轮无资源时整条不渲染。
 */
const CoApisChatResourceBar: React.FC<Props> = ({
  items,
  onPreview,
  onShowAll,
  onJudgment,
  onLocate,
}) => {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);

  const produced = useMemo(
    () => items.filter((i) => i.role === "producer" || i.role === "export"),
    [items],
  );
  const referenced = useMemo(
    () => items.filter((i) => i.role !== "producer" && i.role !== "export"),
    [items],
  );

  const doPreview = (item: ChatResourceItem) => {
    if (item.kind === "web") {
      window.open(item.path, "_blank", "noopener,noreferrer");
      return;
    }
    const path = toLedgerRelPath(item.path);
    // 名字口径统一走 helpers（含扩展名）：预览标题与下载文件名都该带上扩展名
    const name = displayName(item) || path;
    if (getPreviewKind(path) === "unsupported") {
      downloadFile(item.path, name, item.kind);
      return;
    }
    if (onPreview) {
      onPreview({
        path,
        name,
        source: item.role === "producer" ? "produced" : "reference",
      });
      return;
    }
    previewFile(path, name);
  };

  // F2：下载是动作 —— 原文 + 全部转换目标收进一个下拉，不再单列 ⇄ 图标
  const downloadMenu = (item: ChatResourceItem) => {
    const items: NonNullable<MenuProps["items"]> = [
      {
        key: "raw",
        label: t("chat.preview.downloadOriginal"),
        onClick: () => downloadFile(item.path, displayName(item) || item.path),
      },
    ];
    if (item.kind === "file") {
      const targets = convertTargetsFor(item.path);
      if (targets.length) {
        items.push({ type: "divider" });
        for (const target of targets) {
          items.push({
            key: `conv-${target}`,
            label: t("chat.preview.convertTo", { fmt: target.toUpperCase() }),
            onClick: () =>
              // 转换命名：去掉原扩展名再拼新格式（`a.txt`+pdf → `a.pdf`）
              downloadFile(
                item.path,
                `${stemName(item)}.${target}`,
                target,
                item.kind,
              ),
          });
        }
      }
    }
    return { items };
  };

  const renderGroup = (
    label: string,
    list: ChatResourceItem[],
    source: "produced" | "reference",
  ) => {
    if (!list.length) return null;
    const shown = expanded ? list : list.slice(0, GROUP_CAP);
    const rest = list.length - shown.length;
    return (
      <div className={styles.group}>
        <div className={styles.groupHead}>
          {label}
          <span className={styles.groupCount}>{list.length}</span>
        </div>
        {shown.map((item) => {
          const st = resourceStatusOf(item);
          const dead = st === "deleted" || st === "missing";
          return (
            <div
              key={`${item.kind}:${item.path}`}
              className={`${styles.row} ${dead ? styles.rowDead : ""}`}
              title={item.path}
            >
              <span className={styles.kind}>{KIND_ICON[item.kind]}</span>
              <span
                className={styles.name}
                onClick={() => !dead && doPreview(item)}
              >
                {displayName(item) || item.path}
              </span>
              <Tag className={styles.tag} color={source === "produced" ? "green" : "blue"}>
                {source === "produced"
                  ? t("chat.resources.produced")
                  : t("chat.resources.reference")}
              </Tag>
              {TAGGED_STATUSES.has(st) ? (
                <Tag className={styles.tag} color={STATUS_META[st]?.color}>
                  {t(`chat.resources.${STATUS_META[st]?.label ?? "statusDraft"}`)}
                </Tag>
              ) : null}
              {source === "produced" && item.messageId && onLocate ? (
                <Tooltip title={t("chat.resources.locateMessage")}>
                  <AimOutlined
                    className={styles.action}
                    onClick={() => onLocate(item.messageId as string)}
                  />
                </Tooltip>
              ) : null}
              <span className={styles.actions}>
                <Tooltip title={dead ? t("chat.resources.statusMissing") : t("chat.resources.preview")}>
                  <EyeOutlined
                    onClick={() => !dead && doPreview(item)}
                    style={{ cursor: dead ? "not-allowed" : "pointer" }}
                  />
                </Tooltip>
                {item.kind === "file" && !dead ? (
                  <Dropdown
                    menu={downloadMenu(item)}
                    trigger={["click"]}
                  >
                    <Tooltip title={t("chat.resources.download")}>
                      <DownloadOutlined style={{ cursor: "pointer" }} />
                    </Tooltip>
                  </Dropdown>
                ) : null}
              </span>
            </div>
          );
        })}
        {rest > 0 && (
          <a className={styles.expand} onClick={() => setExpanded(true)}>
            {t("chat.resources.expandRest", {
              n: rest,
              defaultValue: "展开其余 {{n}} 项",
            })}
          </a>
        )}
      </div>
    );
  };

  if (!items.length) return null;

  // 「定位到消息」的 DOM 锚点：本条资源条属于哪一轮，就标在哪
  const anchorMessageId = produced.find((i) => i.messageId)?.messageId;

  return (
    <div
      className={styles.bar}
      data-coapis-resource-msg={anchorMessageId}
      data-coapis-resource-bar=""
    >
      {/* 折叠态：单行摘要（方案：默认折叠，单行 28px） */}
      <div className={styles.header}>
        <span className={styles.title}>
          <AppstoreOutlined /> {t("chat.resources.barTitle", "会话资源")}
        </span>
        <span className={styles.groups}>
          <span className={styles.groupChip}>
            {t("chat.resources.reference")} {referenced.length}
          </span>
          <span className={styles.groupChip}>
            {t("chat.resources.produced")} {produced.length}
          </span>
        </span>
        <span className={styles.spacer} />
        <a className={styles.collapse} onClick={() => setExpanded((v) => !v)}>
          {expanded ? (
            <DownOutlined />
          ) : (
            <RightOutlined />
          )}
          {expanded
            ? t("chat.resources.collapse", "收起")
            : t("chat.resources.expand", "展开")}
        </a>
        {onShowAll && (
          <a
            className={styles.showAll}
            onClick={onShowAll}
            /* 抽屉「点外面就关」认这个标记：入口自己 toggle，抢关会关掉又立刻重开 */
            data-coapis-res-trigger=""
          >
            {t("chat.resources.viewAll", "查看全部")}
          </a>
        )}
        {onJudgment && (
          <a
            className={styles.showAll}
            onClick={onJudgment}
            /* 本轮判断台账入口（v14 §5.2）：判没判、判成什么，一轮一行 */
            title={t("decision.entryTip", "本轮判断台账")}
            data-coapis-res-trigger=""
          >
            {t("decision.entry", "判断")}
          </a>
        )}
      </div>
      {expanded && (
        <>
          {renderGroup(t("chat.resources.groupReference"), referenced, "reference")}
          {renderGroup(t("chat.resources.groupProduced"), produced, "produced")}
        </>
      )}
    </div>
  );
};

export default CoApisChatResourceBar;
