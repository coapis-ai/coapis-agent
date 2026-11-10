import React, { useEffect, useMemo, useState } from "react";
import {
  Button,
  Empty,
  Input,
  message,
  Pagination,
  Popconfirm,
  Segmented,
  Select,
  Table,
  Tag,
  Tooltip,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import type { TableProps } from "antd";
import {
  FileTextOutlined,
  GlobalOutlined,
  ReloadOutlined,
  EyeOutlined,
  DownloadOutlined,
  AimOutlined,
} from "@ant-design/icons";
import { Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { chatApi } from "../../../../api/modules/chat";
import type { ChatResourceItem } from "../../../../api/modules/chat";
import {
  toLedgerRelPath,
  getPreviewKind,
  downloadFile,
  deleteWorkspaceFile,
  previewFile,
} from "../../../../utils/webPreview";
import { TAGGED_STATUSES } from "../CoApisChatResourceBar";
import { displayName, shortDir } from "./helpers";
import { formatResSize, formatResTime } from "./resourceFormat";
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

/**
 * 时间与体积的尺子只此一份：`./resourceFormat`（列表、资源条、顶栏共用）。
 *
 * 此前这里自己写了一份 toEpochMs/fmtTime/fmtSize —— 同一列在右侧资源条里
 * 显示 "19:41"、在列表里显示 "2026/11/5 19:41:52"，两把尺子（小蜜蜂
 * 2026-11-05 第 1 条「更新时间显示成 5 万年后」也是同一族问题）。
 */
const fmtTime = (ts?: number | string | null) => formatResTime(ts);

const fmtSize = (n?: number | string | null) => formatResSize(n);

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
  // v25 · P3（小蜜蜂 2026-11-09 第 2 条「引用 / 产出各看各的」）：抽屉补
  // 「引用 / 产出」筛选。与左栏下拉、本轮资源条同一把尺子（producer/export
  // 算产出，其余算引用）。筛选在**后端、分页之前**做 —— 前端只筛当前页会让
  // 「共 N 条」与页内条数错位，那是左栏老毛病，不在这里重犯。
  const [role, setRole] = useState<"all" | "produced" | "reference">("all");
  // v17 · F7（拍板 D4-A）：排序交给后端（台账在**分页之前**排全量），表头是
  // 唯一控制点。取键与台账 `_CHAT_SORT_KEYS` 一一对应（name 升序、其余倒序），
  // 默认按更新时间倒序（小蜜蜂 2026-11-05 第 6 条）。此前是"前端只排当前页
  // 20 条"，等于在一个已经截断的窗口里比大小 —— 翻到第 2 页顺序就乱。
  const [sort, setSort] = useState<string>("updated_at");
  // 删除成功后重拉当前页的触发器
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!chatId) {
      setItems([]);
      setTotal(0);
      return;
    }
    setLoading(true);
    chatApi
      // v23（2026-11-09 拍板）：跨聊天汇总下线 —— 抽屉固定看当前聊天。
      // 后端 scope=session 参数保留不动（社区版公共契约），前端不再请求。
      .listChatResources(
        chatId,
        PAGE_SIZE,
        offset,
        sort,
        "chat",
        "chat",
        role === "all" ? "" : role,
      )
      .then((res) => {
        setItems(res.items || []);
        setTotal(res.total || 0);
      })
      .catch(() => {
        setItems([]);
        setTotal(0);
      })
      .finally(() => setLoading(false));
  }, [chatId, offset, refreshSignal, sort, tick, role]);

  const rows = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    const out = items.filter(
      (it) =>
        (kind === "all" || it.kind === kind) &&
        (!kw ||
          (it.title || "").toLowerCase().includes(kw) ||
          (it.path || "").toLowerCase().includes(kw) ||
          displayName(it).toLowerCase().includes(kw)),
    );
    // 顺序由后端定（见上）：这里只做类型/关键词筛选，不再自带第二把尺子
    return out;
  }, [items, kind, keyword]);

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

  /**
   * 删除（v17 · F7）：会话资源侧走**软删** —— 台账行标 deleted_at、写一条
   * delete 事件，磁盘文件保留（台账里 memories/resources 的删除历来软删，
   * 硬删只留给「我的空间」，见拍板 D2-B）。删完重拉当前页，行立刻显示
   * 「已删除」灰标；失败给明确提示，不静默。
   */
  const doDelete = async (item: ChatResourceItem) => {
    try {
      await deleteWorkspaceFile(item.path, { soft: true });
      message.success(t("chat.resources.deleteDone"));
      setTick((v) => v + 1);
    } catch (err) {
      message.error(
        `${t("chat.resources.deleteFailed")}: ${
          err instanceof Error ? err.message : String(err)
        }`,
      );
    }
  };

  /**
   * 表头排序（v17 · F7）：把列键透传给后端，由台账在全量数据上重排。
   * 每个键方向定死（名称升序、时间/大小/版本倒序），点表头就是"换尺子"，
   * 不做 antd 默认的三态循环 —— 那会让"按时间"在升序/取消之间漂。
   */
  const handleTableChange: NonNullable<
    TableProps<ChatResourceItem>["onChange"]
  > = (_pag, _filters, sorter) => {
    const s = Array.isArray(sorter) ? sorter[0] : sorter;
    const key = String(s?.columnKey ?? "");
    if (s?.order && key && key !== sort) setSort(key);
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
      // v17 · F7：表头即排序控件（点表头 → sort_by 交后端全量重排）。
      // 名称列自己管两行的省略（antd 的 ellipsis 只认单行，套两行会把目录那行裁掉）
      sorter: true,
      sortOrder: sort === "name" ? "ascend" : null,
      showSorterTooltip: false,
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
      key: "updated_at",
      width: 112,
      // v17 · F5/F7：这一列就是**文件真实修改时间**（台账 updated_at），
      // 表头点击 → 后端按同一字段全量重排；扫盘回退行才借 last_seen_at。
      sorter: true,
      sortOrder: sort === "updated_at" ? "descend" : null,
      showSorterTooltip: false,
      render: (_, item) => fmtTime(item.updated_at || item.last_seen_at),
    },
    {
      // v17 · F7：版本列（此前台账里一直有 version，界面从不显示 → 用户
      // 看到"v1 的文件内容早变了"却无从判断）。口径见 file_ledger._apply_to_resource：
      // 首次=1，内容（字节数/mtime）变了才 +1。
      title: t("chat.resources.versionTitle"),
      key: "version",
      width: 56,
      sorter: true,
      sortOrder: sort === "version" ? "descend" : null,
      showSorterTooltip: false,
      render: (_, item) =>
        item.kind === "file"
          ? t("chat.resources.version", { n: Number(item.version ?? 1) || 1 })
          : "-",
    },
    {
      title: t("chat.resources.size"),
      key: "size",
      width: 62,
      sorter: true,
      sortOrder: sort === "size" ? "descend" : null,
      showSorterTooltip: false,
      render: (_, item) => fmtSize(item.size),
    },
    {
      title: t("chat.resources.actions"),
      key: "actions",
      width: 112,
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
                {/* v17 · F7：预览/下载/**删除**三个动作齐全（小蜜蜂第 6 条）。
                    会话侧走软删（台账标 deleted_at，磁盘文件保留，可重新生成）；
                    「我的空间」的硬删语义不动（拍板 D2-B）。二次确认。 */}
                <Popconfirm
                  title={t("chat.resources.deleteConfirm")}
                  okText={t("common.confirm")}
                  cancelText={t("common.cancel")}
                  okButtonProps={{ danger: true }}
                  onConfirm={() => doDelete(item)}
                >
                  <Tooltip title={t("chat.resources.delete")}>
                    <Button
                      type="text"
                      size="small"
                      danger
                      icon={<Trash2 size={14} />}
                    />
                  </Tooltip>
                </Popconfirm>
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
        {/* v25 · P3（小蜜蜂第 2 条）：「引用 / 产出」在抽屉里各看各的。
            此前抽屉只有类型 + 关键词，产出/引用只在行尾挂个绿标签，想只看
            产出得自己数。左栏下拉与本轮条早就有这层筛选，抽屉是最后一处缺的
            —— 三处现在共用台账里同一把尺子（producer/export 即产出）。 */}
        <Segmented
          size="small"
          value={role}
          options={[
            { value: "all", label: t("chat.resources.roleAll") },
            { value: "produced", label: t("chat.resources.roleProduced") },
            { value: "reference", label: t("chat.resources.roleReference") },
          ]}
          onChange={(v) => {
            setRole(v as "all" | "produced" | "reference");
            setOffset(0); // 换了筛选口径就回第 1 页，避免停在不存在的页
          }}
        />
        <span className={styles.count}>
          {t("chat.resources.count", { n: total })}
        </span>
        {/* v17 · F7：刷新此前写的是 `setOffset(0)` —— 已在第 1 页时是空操作，
            按了等于没按。改成显式重拉当前页。 */}
        <Button
          size="small"
          icon={<ReloadOutlined />}
          onClick={() => setTick((v) => v + 1)}
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
        // v17 · F7：点表头 → 换尺子交后端全量重排（分页仍由下面这条 Pagination 管）
        onChange={handleTableChange}
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
