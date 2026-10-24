import React, { useMemo } from "react";
import { Dropdown, Tag, Tooltip } from "antd";
import {
  DownloadOutlined,
  EyeOutlined,
  FileImageOutlined,
  FileTextOutlined,
  GlobalOutlined,
  SwapOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import type { ChatResourceItem } from "../../../api/modules/chat";
import {
  toLedgerRelPath,
  getPreviewKind,
  downloadFile,
  previewFile,
} from "../../../utils/webPreview";
import styles from "./CoApisChatResources.module.css";

/**
 * 本轮产出资源形状 —— 两条通道用两套字段词汇，这里全部兼容：
 *  - 实时 completed 事件：{name, type, url, source, size}
 *  - 台账 / 历史持久化（后端 _turn_resources_from_ledger）：{kind, path, title, role}
 * 只认前者会让刷新后的产出卡与资源条整块消失（历史回放没有 completed 事件）。
 */
export interface LiveResource {
  name?: string;
  type?: string;
  url?: string;
  source?: string;
  size?: number;
  /** 台账/持久化字段 */
  kind?: string;
  path?: string;
  title?: string;
  role?: string;
}

interface Props {
  /** 本轮资源列表（消息 metadata 里的 resources） */
  resources?: LiveResource[];
  /** 会话级抽屉（批次 B2）：传入时预览走抽屉，不退化成新窗口 */
  onPreview?: (target: {
    path: string;
    name: string;
    source: "produced" | "reference";
  }) => void;
  /** 台账 meta 反查（方案 §12.4 L1：大小 / 更新时间 / 交付版本） */
  metaOf?: (path: string) => ChatResourceItem | undefined;
  /** 「查看全部」→ 打开会话资源抽屉（L3） */
  onShowAll?: () => void;
}

const KIND_ICON: Record<string, React.ReactNode> = {
  file: <FileTextOutlined />,
  web: <GlobalOutlined />,
  image: <FileImageOutlined />,
};

const fmtSize = (n?: number | string | null) => {
  const b = Number.isFinite(Number(n)) ? Number(n) : 0;
  if (b <= 0) return "";
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / 1024 / 1024).toFixed(1)} MB`;
};

const fmtWhen = (ts?: number | string | null) => {
  const t = Number(ts);
  if (!Number.isFinite(t) || t <= 0) return "";
  const d = new Date(t * 1000);
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  return sameDay
    ? d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString(undefined, { month: "2-digit", day: "2-digit" });
};

/**
 * 会话内资源卡（方案 §3.2 L1 / §12.4，批次 B1）
 * ---------------------------------------------------------------------------
 * 挂在官方 `chat-resources` 插件位（本部署即 response.append，order 11），
 * 数据源是消息 metadata 里的 `resources` —— 后端在智能体产出文件/链接后随
 * 事件下发，前端只负责呈现，不自己猜路径。
 *
 * 呈现（方案 §12.4 L1）：名称 + 类型图标 + **大小 · 更新时间 · 交付版本徽标**
 * + [预览] [下载] [转格式▾ docx/pdf]；预览走会话级抽屉（B2）。
 * 本轮没有资源时整卡不渲染。
 */
const CoApisChatResources: React.FC<Props> = ({
  resources,
  onPreview,
  metaOf,
  onShowAll,
}) => {
  const { t } = useTranslation();

  const items = useMemo(() => {
    if (!resources?.length) return [];
    const out: Array<{
      key: string;
      kind: string;
      name: string;
      path: string;
      meta?: ChatResourceItem;
    }> = [];
    const seen = new Set<string>();
    for (const r of resources) {
      // 两套字段词汇：实时 completed 事件 {url|source, type}；台账/持久化 {path, kind}。
      const path = String(r.path || r.url || r.source || "");
      if (!path) continue;
      const kind =
        r.kind === "url" || r.type === "url"
          ? "web"
          : r.kind || r.type || "file";
      const key = `${kind}:${path}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({
        key,
        kind,
        name:
          r.title ||
          r.name ||
          (kind === "web" ? path : path.split("/").pop() || path),
        path,
        meta: metaOf?.(path),
      });
    }
    return out;
  }, [resources, metaOf]);

  // 台账刷新由会话级 resourceRefresh 驱动（响应完成事件里已自增），
  // 本卡只负责呈现，不发副作用。

  if (!items.length) return null;

  const doPreview = (item: (typeof items)[number]) => {
    if (item.kind === "web") {
      window.open(item.path, "_blank", "noopener,noreferrer");
      return;
    }
    const path = toLedgerRelPath(item.path);
    if (getPreviewKind(path) === "unsupported") {
      downloadFile(item.path, item.name, item.kind);
      return;
    }
    if (onPreview) {
      onPreview({ path, name: item.name, source: "produced" });
      return;
    }
    previewFile(path, item.name);
  };

  const convertMenu = (item: (typeof items)[number]) => ({
    items: [
      {
        key: "docx",
        label: t("chat.preview.convertDocx", "Word (docx)"),
        onClick: () => downloadFile(item.path, `${item.name}.docx`, "docx", item.kind),
      },
      {
        key: "pdf",
        label: t("chat.preview.convertPdf", "PDF"),
        onClick: () => downloadFile(item.path, `${item.name}.pdf`, "pdf", item.kind),
      },
    ],
  });

  return (
    <div className={styles.card}>
      <div className={styles.header}>
        <span className={styles.title}>
          {t("chat.resources.producedTitle", "本轮产出")}
        </span>
        <span className={styles.count}>{items.length}</span>
        {onShowAll && (
          <a className={styles.showAll} onClick={onShowAll}>
            {t("chat.resources.viewAll", "查看全部")}
          </a>
        )}
      </div>
      <div className={styles.list}>
        {items.map((item) => {
          const size = fmtSize(item.meta?.size ?? item.meta?.size);
          const when = fmtWhen(item.meta?.updated_at || item.meta?.last_seen_at);
          const version = Number(item.meta?.version || 1);
          const dead = !!item.meta?.deleted || item.meta?.exists === false;
          return (
            <div
              key={item.key}
              className={`${styles.item} ${dead ? styles.itemDead : ""}`}
              title={item.path}
            >
              <span className={styles.kind}>
                {KIND_ICON[item.kind] || KIND_ICON.file}
              </span>
              <span className={styles.nameWrap}>
                <span
                  className={styles.name}
                  onClick={() => !dead && doPreview(item)}
                >
                  {item.name}
                </span>
                {/* 方案 §12.4 L1：大小 · 更新时间 · 交付版本徽标 */}
                <span className={styles.meta}>
                  {size ? <span>{size}</span> : null}
                  {when ? <span>{when}</span> : null}
                  {version > 1 ? (
                    <Tag className={styles.versionTag} color="blue">
                      {t("chat.resources.version", {
                        n: version,
                        defaultValue: "v{{n}}",
                      })}
                    </Tag>
                  ) : null}
                </span>
              </span>
              {/* 软删/失效项：灰显 + 标注「已删除」（方案 §3.2 / 核查 R3）。
                  状态词一律用后端真实词表，不自造前端词。 */}
              {dead ? (
                <Tag className={styles.tag} color="red">
                  {t("chat.resources.statusDeleted")}
                </Tag>
              ) : (
                <Tag className={styles.tag} color="green">
                  {t("chat.resources.produced")}
                </Tag>
              )}
              <span className={styles.actions}>
                <Tooltip
                  title={
                    dead ? t("chat.resources.statusMissing") : t("chat.resources.preview")
                  }
                >
                  <EyeOutlined
                    onClick={() => !dead && doPreview(item)}
                    style={{ cursor: dead ? "not-allowed" : "pointer" }}
                  />
                </Tooltip>
                {item.kind !== "web" ? (
                  <>
                    <Tooltip title={t("chat.resources.download")}>
                      <DownloadOutlined
                        onClick={() =>
                          downloadFile(item.path, item.name, item.kind)
                        }
                      />
                    </Tooltip>
                    <Dropdown menu={convertMenu(item)} trigger={["click"]}>
                      <Tooltip title={t("chat.resources.convert")}>
                        <SwapOutlined style={{ cursor: "pointer" }} />
                      </Tooltip>
                    </Dropdown>
                  </>
                ) : null}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default CoApisChatResources;
