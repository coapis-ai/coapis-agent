import React, { useEffect, useMemo, useState } from "react";
import {
  Button,
  Empty,
  Input,
  Pagination,
  Select,
  Table,
  Tag,
  Tooltip,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  FileTextOutlined,
  GlobalOutlined,
  ReloadOutlined,
  EyeOutlined,
  DownloadOutlined,
  AimOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { chatApi } from "../../../../api/modules/chat";
import type { ChatResourceItem } from "../../../../api/modules/chat";
import {
  toLedgerRelPath,
  getPreviewKind,
  downloadFile,
  previewFile,
} from "../../../../utils/webPreview";
import { TAGGED_STATUSES } from "../CoApisChatResourceBar";
import { displayName, shortDir } from "./helpers";
import styles from "./index.module.less";

/** 名称单元格里「可被截断」的那一个：省略号在尾部，标签优先占位。 */
const NAME_CLIP: React.CSSProperties = {
  minWidth: 0,
  flex: "0 1 auto",
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
  display: "inline-block",
};

const PAGE_SIZE = 20;

const KIND_ICON: Record<string, React.ReactNode> = {
  file: <FileTextOutlined style={{ color: "#1677ff" }} />,
  web: <GlobalOutlined style={{ color: "#52c41a" }} />,
  kb: <FileTextOutlined style={{ color: "#722ed1" }} />,
  mcp: <FileTextOutlined style={{ color: "#fa8c16" }} />,
  db: <FileTextOutlined style={{ color: "#13c2c2" }} />,
};

/**
 * 状态词表（方案 §3.2 / §12.4，验收项 1）。
 *
 * 后端台账只有 draft / official / orphan / archived / deleted 五个值，前端
 * 曾经按一个后端从不存在的 "gone" 过滤整表 —— 这里把词表钉死成后端真实值，
 * 并把「文件已失效」独立出来（台账在、磁盘没了，由 sweep 标记）。
 */
const STATUS_META: Record<
  string,
  { label: string; color: string }
> = {
  official: { label: "statusPublished", color: "green" },
  draft: { label: "statusDraft", color: "default" },
  orphan: { label: "statusMoved", color: "orange" },
  archived: { label: "statusArchived", color: "purple" },
  deleted: { label: "statusDeleted", color: "red" },
  missing: { label: "statusMissing", color: "red" },
};

/** 一行资源现在到底算什么状态：软删 > 磁盘失效 > 台账状态。 */
function statusOf(item: ChatResourceItem): string {
  if (item.deleted || item.status === "deleted") return "deleted";
  if (item.kind === "file" && item.exists === false) return "missing";
  return item.status || "draft";
}

const fmtTime = (ts?: number | string | null) => {
  const t = Number(ts);
  return Number.isFinite(t) && t > 0
    ? new Date(t * 1000).toLocaleString()
    : "-";
};

const fmtSize = (n?: number | string | null) => {
  const b = Number.isFinite(Number(n)) ? Number(n) : 0;
  if (b <= 0) return "-";
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / 1024 / 1024).toFixed(1)} MB`;
};

interface Props {
  chatId: string | undefined;
  /** 外部传入的刷新信号（本轮产出落台账后自增） */
  refreshSignal?: number;
  /** 预览走会话级抽屉（方案 §12.4 L1）；不传则退化为新窗口 */
  onPreview?: (target: {
    path: string;
    name: string;
    source: "produced" | "reference";
  }) => void;
}

/**
 * 会话「资源」Tab（方案 §3.2 / §12.4 L3）
 *
 * 数据源是台账端点 GET /chats/{id}/resources（含软删行），不是消息里的
 * 实时资源列表。列：类型 / 名称 / 时间 / 大小 / 状态标签；工具条：类型筛选
 * + 关键词搜索 + 排序；行操作：预览 / 下载 / 定位到我的空间。
 */
const ChatSessionResources: React.FC<Props> = ({
  chatId,
  refreshSignal = 0,
  onPreview,
}) => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [items, setItems] = useState<ChatResourceItem[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [kind, setKind] = useState<string>("all");
  const [keyword, setKeyword] = useState("");
  const [sort, setSort] = useState<string>("time_desc");

  useEffect(() => {
    if (!chatId) {
      setItems([]);
      setTotal(0);
      return;
    }
    setLoading(true);
    chatApi
      .listChatResources(chatId, PAGE_SIZE, offset)
      .then((res) => {
        setItems(res.items || []);
        setTotal(res.total || 0);
      })
      .catch(() => {
        setItems([]);
        setTotal(0);
      })
      .finally(() => setLoading(false));
  }, [chatId, offset, refreshSignal]);

  const rows = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    let out = items.filter(
      (it) =>
        (kind === "all" || it.kind === kind) &&
        (!kw ||
          (it.title || "").toLowerCase().includes(kw) ||
          (it.path || "").toLowerCase().includes(kw) ||
          displayName(it).toLowerCase().includes(kw)),
    );
    out = [...out].sort((a, b) => {
      if (sort === "name") return displayName(a).localeCompare(displayName(b));
      const at = (x: ChatResourceItem) =>
        Number(x.updated_at ?? x.last_seen_at ?? 0) || 0;
      const sz = (x: ChatResourceItem) => Number(x.size ?? 0) || 0;
      if (sort === "size") return sz(b) - sz(a);
      if (sort === "time_asc") return at(a) - at(b);
      return at(b) - at(a);
    });
    return out;
  }, [items, kind, keyword, sort]);

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

  const doLocate = (item: ChatResourceItem) => {
    // 「定位到我的空间」：带 ?locate= 过去，由我的空间展开目录并高亮该行。
    navigate(
      `/workspace/myspace?locate=${encodeURIComponent(item.path)}`,
    );
  };

  const columns: ColumnsType<ChatResourceItem> = [
    {
      title: "",
      key: "kind",
      width: 36,
      render: (_, item) => KIND_ICON[item.kind] || KIND_ICON.file,
    },
    {
      title: t("chat.resources.name"),
      key: "name",
      // 名称列自己管两行的省略（antd 的 ellipsis 只认单行，套两行会把目录那行裁掉）
      render: (_, item) => {
        const st = statusOf(item);
        const dead = st === "deleted" || st === "missing";
        // 名字口径统一走 helpers：文件名**含扩展名**优先，title 只兜底
        const name = displayName(item) || item.path;
        const dir = shortDir(item); // 只留末尾两段，全路径在 title
        const link =
          item.kind === "web" ? (
            <a
              href={item.path}
              target="_blank"
              rel="noopener noreferrer"
              title={item.path}
              style={NAME_CLIP}
            >
              {name}
            </a>
          ) : dead ? (
            // 已删除 / 已失效：灰显、不给死链
            <span style={{ ...NAME_CLIP, color: "rgba(0,0,0,0.35)" }} title={item.path}>
              {name}
            </span>
          ) : (
            <a onClick={() => doPreview(item)} title={item.path} style={NAME_CLIP}>
              {name}
            </a>
          );
        return (
          <span style={{ display: "block", minWidth: 0, overflow: "hidden" }}>
            <span
              style={{
                display: "flex",
                gap: 4,
                alignItems: "center",
                minWidth: 0,
                ...(dead
                  ? {
                      textDecoration: "line-through",
                      color: "rgba(0,0,0,0.35)",
                    }
                  : {}),
              }}
            >
            {link}
            {item.role === "producer" || item.role === "export" ? (
              <Tag color="green" style={{ margin: 0, flexShrink: 0 }}>
                {t("chat.resources.produced")}
              </Tag>
            ) : null}
            {TAGGED_STATUSES.has(st) ? (
              <Tag
                color={STATUS_META[st]?.color}
                style={{ margin: 0, flexShrink: 0 }}
                title={
                  st === "deleted"
                    ? t("chat.resources.deletedHint")
                    : st === "missing"
                      ? t("chat.resources.missingHint")
                      : undefined
                }
              >
                {t(`chat.resources.${STATUS_META[st]?.label ?? "statusDraft"}`)}
              </Tag>
            ) : null}
            </span>
            {/* 第二行：所在目录。路径此前只藏在 tooltip 里，用户看一列名字
                认不出文件在哪个目录（方案 F2） */}
            {dir ? (
              <span
                title={item.path}
                style={{
                  display: "block",
                  fontSize: 12,
                  lineHeight: "16px",
                  color: "rgba(0,0,0,0.45)",
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {dir}
              </span>
            ) : null}
          </span>
        );
      },
    },
    {
      title: t("chat.resources.time"),
      key: "time",
      width: 112,
      render: (_, item) => fmtTime(item.updated_at || item.last_seen_at),
    },
    {
      title: t("chat.resources.size"),
      key: "size",
      width: 62,
      render: (_, item) => fmtSize(item.size),
    },
    {
      title: t("chat.resources.actions"),
      key: "actions",
      width: 88,
      render: (_, item) => {
        const st = statusOf(item);
        const dead = st === "deleted" || st === "missing";
        return (
          <span onClick={(e) => e.stopPropagation()}>
            <Tooltip title={dead ? t("chat.resources.statusMissing") : t("chat.resources.preview")}>
              <Button
                type="text"
                size="small"
                icon={<EyeOutlined />}
                disabled={dead && item.kind !== "web"}
                onClick={() => doPreview(item)}
              />
            </Tooltip>
            {item.kind === "file" ? (
              <>
                <Tooltip title={t("chat.resources.download")}>
                  <Button
                    type="text"
                    size="small"
                    icon={<DownloadOutlined />}
                    disabled={dead}
                    onClick={() =>
                      downloadFile(
                        item.path,
                        displayName(item) || item.path,
                        item.kind,
                      )
                    }
                  />
                </Tooltip>
                <Tooltip title={t("chat.resources.locate")}>
                  <Button
                    type="text"
                    size="small"
                    icon={<AimOutlined />}
                    disabled={dead}
                    onClick={() => doLocate(item)}
                  />
                </Tooltip>
              </>
            ) : null}
          </span>
        );
      },
    },
  ];

  return (
    <div className={styles.resourcesTab}>
      <div className={styles.toolbar}>
        <Select
          size="small"
          style={{ width: 110 }}
          getPopupContainer={(node) =>
            (node.parentElement as HTMLElement) ?? document.body
          }
          value={kind}
          onChange={setKind}
          options={[
            { value: "all", label: t("chat.resources.filterAll") },
            { value: "file", label: t("chat.resources.kindFile") },
            { value: "web", label: t("chat.resources.kindWeb") },
            { value: "kb", label: t("chat.resources.kindKb") },
            { value: "mcp", label: t("chat.resources.kindMcp") },
            { value: "db", label: t("chat.resources.kindDb") },
          ]}
        />
        <Input.Search
          size="small"
          allowClear
          style={{ width: 180 }}
          placeholder={t("chat.resources.searchPlaceholder")}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />
        <Select
          size="small"
          style={{ width: 120 }}
          getPopupContainer={(node) =>
            (node.parentElement as HTMLElement) ?? document.body
          }
          value={sort}
          onChange={setSort}
          options={[
            { value: "time_desc", label: t("chat.resources.sortTimeDesc") },
            { value: "time_asc", label: t("chat.resources.sortTimeAsc") },
            { value: "name", label: t("chat.resources.sortName") },
            { value: "size", label: t("chat.resources.sortSize") },
          ]}
        />
        <span className={styles.count}>
          {t("chat.resources.count", { n: total })}
        </span>
        <Button
          size="small"
          icon={<ReloadOutlined />}
          onClick={() => setOffset(0)}
        />
      </div>
      <Table
        rowKey={(r) => `${r.kind}:${r.path}`}
        size="small"
        tableLayout="fixed"
        loading={loading}
        columns={columns}
        dataSource={rows}
        pagination={false}
        locale={{
          emptyText: (
            <Empty
              description={t("chat.resources.empty")}
              image={Empty.PRESENTED_IMAGE_SIMPLE}
            />
          ),
        }}
      />
      {total > PAGE_SIZE && (
        <Pagination
          size="small"
          style={{ marginTop: 8, textAlign: "right" }}
          total={total}
          pageSize={PAGE_SIZE}
          current={Math.floor(offset / PAGE_SIZE) + 1}
          showSizeChanger={false}
          onChange={(page) => setOffset((page - 1) * PAGE_SIZE)}
        />
      )}
    </div>
  );
};

export default ChatSessionResources;
