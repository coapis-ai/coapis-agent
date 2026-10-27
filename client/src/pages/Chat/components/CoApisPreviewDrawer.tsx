import {
  Button,
  Dropdown,
  Modal,
  Tooltip,
} from "@agentscope-ai/design";
// Space/Spin/Typography/Empty 不在 @agentscope-ai/design 的导出里（Empty 的
// image/description 在本包被收窄成 string），直接用底层 antd。
import { Alert, Empty, Segmented, Select, Space, Spin, Typography } from "antd";
import {
  ChevronDown,
  Copy,
  Download,
  FileText,
  FolderOpen,
  Link2,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { XMarkdown } from "@ant-design/x-markdown";

import { getApiToken, getApiUrl } from "@/api/config";
import FloatingWindow from "./FloatingWindow";
import styles from "./CoApisPreviewDrawer.module.less";
import {
  canInlinePreview,
  copyDirectLink,
  convertTargetsFor,
  downloadFile,
  getPreviewKind,
  previewSrcUrl,
} from "../../../utils/webPreview";
import { toMyfilesParams } from "../workspaceLinks";

const { Text } = Typography;

/** 浮窗尺寸上下限与默认值（几何、手势、localStorage 记忆由骨架负责）。 */
const MIN_WIDTH = 340;
const MIN_HEIGHT = 260;
const DEFAULT_WIDTH = 560;
const DEFAULT_HEIGHT = 560;

export interface PreviewTarget {
  /** 工作区相对路径（files/x.md） */
  path: string;
  title?: string;
  size?: number | null;
  updatedAt?: number | string;
  /** 我的空间分类目录（files/media）；默认 files。 */
  category?: string;
}

const IMAGE_EXT = new Set(["png", "jpg", "jpeg", "gif", "webp", "bmp", "svg"]);
const PDF_EXT = "pdf";
const MD_EXT = new Set(["md", "markdown"]);

export interface PreviewSwitchItem {
  path: string;
  title?: string;
  category?: string;
}

const MAX_INLINE_BYTES = 2 * 1024 * 1024;
const MAX_INLINE_LINES = 5000;

function extOf(path: string): string {
  const m = /\.([A-Za-z0-9]{1,8})$/.exec(path || "");
  return m ? m[1].toLowerCase() : "";
}

/**
 * ``/myfiles/preview`` 对文本文件返回的是 JSON 信封
 * （``{"type":"text","content":"…","mime_type":"…"}``），图片/PDF 走二进制。
 * 预览抽屉直接把响应体当文本渲染，md 就会显示成
 * ``{"type":"text","content":"# 标题\n…"}`` —— 必须把 content 拆出来。
 * 非 JSON（纯文本文件）原样返回。
 */
function unwrapPreviewBody(raw: string): string {
  const body = raw.trim();
  if (!body.startsWith("{")) return raw;
  try {
    const parsed = JSON.parse(body);
    if (parsed && parsed.type === "text" && typeof parsed.content === "string") {
      return parsed.content;
    }
  } catch {
    /* 不是合法 JSON：按原文显示 */
  }
  return raw;
}

function myfilesUrl(
  path: string,
  mode: "preview" | "download",
  category = "files",
): string {
  // 工作区相对路径（files/x.md）与 myfiles 的分类内路径不是一套，必须换算
  const params = toMyfilesParams(path);
  const url = getApiUrl(
    `/myfiles/${mode}?path=${encodeURIComponent(params.path)}&category=${encodeURIComponent(
      params.category || category,
    )}`,
  );
  const token = getApiToken();
  return token ? `${url}&token=${encodeURIComponent(token)}` : url;
}

/**
 * 会话文件预览抽屉（B4 · 会话引用与产出资源体验）。
 *
 * 产出卡与资源条点「预览」都进这里：md/文本内联渲染、图片内联、pdf 内嵌，
 * 其余给下载。走**我的空间**端点（用户作用域 + 权限门控），带 token 查询参数
 * 供 iframe/img 这类无法带 Authorization 头的子资源使用。
 *
 * 预览失败时后端返回带原因的 403/404 文案（作用域闸门 / 文件不存在），这里
 * 原样显示 —— 让用户知道为什么，而不是对着空白发呆。
 */
export default function CoApisPreviewDrawer(props: {
  target: PreviewTarget | null;
  onClose: () => void;
  /**
   * 浮窗挂载点（方案 F1 → D3）。聊天页传「主内容区」节点，浮窗就锚在**主内容
   * 窗口**里 —— 不铺满整个浏览器窗口（实测旧版 y=0/h=900，主内容区是
   * y=117/h=750）。未传时退回 document.body。
   */
  getContainer?: HTMLElement | (() => HTMLElement | null) | null;
  /** D2：当前会话的资源清单 = 头部下拉切换器的数据源；不传则标题不可切换 */
  items?: PreviewSwitchItem[];
  /** D2：下拉选中某条 → 交回聊天页切换预览目标 */
  onSelect?: (item: PreviewSwitchItem) => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [rawView, setRawView] = useState(false);
  const [copied, setCopied] = useState(false);
  const [linkCopied, setLinkCopied] = useState(false);
  // 取内容失败后「重试」用：自增一下让加载 effect 重新跑一遍（加载逻辑内联在 effect 里）
  const [reloadTick, setReloadTick] = useState(0);
  const { target, onClose, getContainer, items, onSelect } = props;
  const [loading, setLoading] = useState(false);
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [truncated, setTruncated] = useState(false);
  const [converting, setConverting] = useState<string | null>(null);
  /** 图片/PDF 的资源地址：优先一次性票据（方案 D6），退回时才是 ?token= 直链。 */
  const [srcUrl, setSrcUrl] = useState<string | null>(null);

  const ext = useMemo(() => extOf(target?.path || ""), [target?.path]);
  const path = target?.path || "";
  const category = target?.category || "files";
  const title = target?.title || path.split("/").pop() || path;
  const canPreview = canInlinePreview(path);

  useEffect(() => {
    setText(null);
    setError(null);
    setTruncated(false);
    setRawView(false);
    setCopied(false);
    setSrcUrl(null);
    if (!target || !canPreview) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    // 图片 / PDF：`<img>`、`<iframe>` 是浏览器自己发起的子资源请求，带不了
    // Authorization 头，只能走 URL 里的凭证 —— 用 60 秒即焚的一次性票据，
    // 不再把 24 小时的 JWT 挂在每条文件链接上（方案 D6）。
    if (IMAGE_EXT.has(ext) || ext === PDF_EXT) {
      setLoading(true);
      void previewSrcUrl(target.path, category).then((u) => {
        if (cancelled) return;
        setSrcUrl(u);
        setLoading(false);
      });
      return () => {
        cancelled = true;
      };
    }
    setLoading(true);
    (async () => {
      try {
        const resp = await fetch(myfilesUrl(target.path, "preview", category), {
          headers: { Authorization: `Bearer ${getApiToken()}` },
        });
        if (!resp.ok) {
          let detail = `${resp.status}`;
          try {
            const body = await resp.json();
            detail = body?.detail || body?.message || detail;
          } catch {
            /* 非 JSON 响应就用状态码 */
          }
          if (!cancelled) setError(detail || `${resp.status}`);
          return;
        }
        const raw = unwrapPreviewBody(await resp.text());
        if (target.size != null && target.size > MAX_INLINE_BYTES) {
          if (!cancelled) {
            setTruncated(true);
            setText(t("chat.preview.tooLarge"));
          }
          return;
        }
        const lines = raw.split("\n");
        if (lines.length > MAX_INLINE_LINES) {
          if (!cancelled) {
            setTruncated(true);
            setText(
              `${lines
                .slice(0, MAX_INLINE_LINES)
                .join("\n")}\n\n… ${t("chat.preview.truncated", {
                n: lines.length - MAX_INLINE_LINES,
              })}`,
            );
          }
          return;
        }
        if (!cancelled) setText(raw);
      } catch (e) {
        if (!cancelled) setError(String((e as Error)?.message || e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [target?.path, ext, canPreview, t, reloadTick]);

  // md 工具条「复制内容」：复制的是**正文文本**（不是文件链接）。
  const copyFull = async () => {
    if (text === null) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setError(t("chat.preview.copyFailed"));
    }
  };

  // 方案 D6：复制的是 60 秒即焚的一次性票据，不是 24 小时有效的 JWT 直链。
  // 旧版把 `?token=<JWT>` 明文挂进剪贴板，贴到聊天窗口/邮件/日志里就留下一条
  // 长期可用的文件入口。
  const copyLink = async () => {
    if (await copyDirectLink(path)) {
      setLinkCopied(true);
      window.setTimeout(() => setLinkCopied(false), 1500);
    } else {
      setError(t("chat.preview.copyFailed"));
    }
  };

  // 头部「下载」下拉里的「转换为 X 后下载」：走 downloadFile 的 targetExt 通道
  // （后端 /myfiles/convert 转完再吐产物），失败由 downloadFile 内部退回原文件，
  // 这里只兜网络级异常。
  const convertAndDownload = useCallback(
    async (fmt: string) => {
      if (!path || converting) return;
      setConverting(fmt);
      try {
        await downloadFile(path, title, fmt);
      } catch (e: any) {
        Modal.error({
          title: t("chat.preview.convertFailed"),
          content: String(e?.message || e),
        });
      } finally {
        setConverting(null);
      }
    },
    [path, title, converting, t],
  );

  const isMd = MD_EXT.has(ext);
  // 预览类型（image/pdf/markdown/text/office/unsupported）：正文渲染分支与
  // 头部下载下拉共用这一口径。
  const kind = getPreviewKind(path);
  // 注：原 §3.3 的 isText（复制全文门控）已随「复制」下移到 md 工具条而退役；
  // 转格式目标改由共享口径 convertTargetsFor 决定（只对 md/txt 出项）。

  // F2：转换目标只列后端真支持的三种，且不含自身格式（避免「md 转 md」这种废项）
  const convertTargets = convertTargetsFor(path);

  // F3：「定位」= 去「我的空间」并带 locate 参数（页面展开目录 + 高亮 + 滚动）
  const locateInWorkspace = useCallback(() => {
    navigate("/workspace/myspace?locate=" + encodeURIComponent(path));
  }, [navigate, path]);

  // ── D3=C 真浮窗：宿主解析 + 位置尺寸状态（头部拖动 / 八向缩放） ──
  const resolveHost = useCallback((): HTMLElement | null => {
    const el =
      typeof getContainer === "function"
        ? getContainer()
        : (getContainer as HTMLElement | null);
    return el ?? (typeof document !== "undefined" ? document.body : null);
  }, [getContainer]);

  const switchOptions: (PreviewSwitchItem & {
    value: string;
    label: string;
  })[] = [];
  const seenPath = new Set<string>();
  (items ?? []).forEach((it) => {
    if (!it?.path || seenPath.has(it.path)) return;
    seenPath.add(it.path);
    switchOptions.push({
      path: it.path,
      value: it.path,
      label: it.title || it.path.split("/").pop() || it.path,
      title: it.path,
    });
  });
  if (!seenPath.has(path)) {
    switchOptions.unshift({
      path,
      value: path,
      label: title,
      title: path,
    });
  }

﻿  return (
    <FloatingWindow
      open={!!target}
      storageKey="previewWin"
      getContainer={resolveHost}
      label={title}
      closeTip={t("chat.previewClose", "关闭预览")}
      defaultWidth={DEFAULT_WIDTH}
      defaultHeight={DEFAULT_HEIGHT}
      minWidth={MIN_WIDTH}
      minHeight={MIN_HEIGHT}
      onClose={onClose}
      bodyClassName={styles["coapis-preview-body-host"]}
      title={
        <>
          <FileText size={14} className={styles["coapis-preview-icon"]} />
          {switchOptions.length > 1 ? (
            <Select
              className={styles["coapis-preview-switch"]}
              size="small"
              value={path}
              onChange={(v) => {
                const hit = switchOptions.find((o) => o.value === v);
                if (hit) onSelect?.(hit);
              }}
              options={switchOptions}
              popupClassName={styles["coapis-preview-switch-dd"]}
            />
          ) : (
            <Tooltip title={path}>
              <Text strong style={{ fontSize: 13 }} ellipsis>
                {title}
              </Text>
            </Tooltip>
          )}
        </>
      }
      extra={
        convertTargets.length > 0 ? (
          <Dropdown
            menu={{
              items: convertTargets.map((f) => ({
                key: f,
                label: t(`chat.preview.format.${f}`, f.toUpperCase()),
                onClick: () => convertAndDownload(f),
              })),
            }}
            trigger={["click"]}
          >
            <Tooltip title={t("chat.previewConvert", "转换格式下载")}>
              <Button type="text" size="small">
                <Download size={14} />
                <ChevronDown size={12} />
              </Button>
            </Tooltip>
          </Dropdown>
        ) : null
      }
      footer={
        <>
          <Tooltip title={path}>
            <Text
              type="secondary"
              className={styles["coapis-preview-path"]}
              ellipsis
              style={{ maxWidth: "100%" }}
            >
              {path}
            </Text>
          </Tooltip>
          <Space size={2}>
            <Tooltip title={t("chat.locateInWorkspace", "在我的空间定位")}>
              <Button
                type="text"
                size="small"
                icon={<FolderOpen size={12} />}
                onClick={locateInWorkspace}
              />
            </Tooltip>
            <Tooltip
              title={
                linkCopied
                  ? t("chat.copied", "已复制")
                  : t("chat.copyLink", "复制直链")
              }
            >
              <Button
                type="text"
                size="small"
                icon={<Link2 size={12} />}
                onClick={() => void copyLink()}
              />
            </Tooltip>
          </Space>
        </>
      }
    >
      {isMd && (
        <div className={styles["coapis-preview-mdbar"]}>
          <Segmented
            size="small"
            value={rawView ? "raw" : "render"}
            onChange={(v) => setRawView(v === "raw")}
            options={[
              {
                label: t("chat.previewRendered", "渲染视图"),
                value: "render",
                icon: <FileText size={12} />,
              },
              { label: t("chat.previewRaw", "md 原文"), value: "raw" },
            ]}
          />
          <span className={styles["coapis-preview-head-spacer"]} />
          <Tooltip
            title={copied ? t("chat.copied", "已复制") : t("chat.copyFull", "复制全文")}
          >
            <Button
              type="text"
              size="small"
              icon={<Copy size={12} />}
              onClick={() => void copyFull()}
            />
          </Tooltip>
        </div>
      )}
      <Spin spinning={loading} wrapperClassName={styles["coapis-preview-spin"]}>
        <div className={styles["coapis-preview-win-body"]}>
          {/* 取不到内容时必须有话说：旧版只 console，用户对着空白窗干瞪眼 */}
          {error && (
            <Alert
              className={styles["coapis-preview-alert"]}
              type="warning"
              showIcon
              message={error}
              action={
                <Button
                  type="text"
                  size="small"
                  onClick={() => {
                    setError("");
                    setReloadTick((n) => n + 1);
                  }}
                >
                  {t("chat.preview.retry", "重试")}
                </Button>
              }
            />
          )}
          {truncated && !error && (
            <Alert
              className={styles["coapis-preview-alert"]}
              type="info"
              showIcon
              message={t(
                "chat.previewTruncated",
                "文件较大，这里只显示开头一段；完整内容请用「新窗口打开」或「下载」。",
              )}
            />
          )}
          {kind === "image" &&
            (srcUrl ? (
              <img
                src={srcUrl}
                alt={title}
                className={styles["coapis-preview-image"]}
              />
            ) : (
              <Spin tip={t("chat.previewLoading", "加载中…")} />
            ))}
          {kind === "office" &&
            (convertTargets.length > 0 ? (
              <div className={styles["coapis-preview-office"]}>
                <Empty
                  description={t(
                    "chat.previewOfficeHint",
                    "此格式需转换后预览，请在上方选择转换格式",
                  )}
                />
              </div>
            ) : (
              <Empty
                description={t("chat.previewNoPreview", "该文件不支持预览")}
              />
            ))}
          {kind === "pdf" &&
            (srcUrl ? (
              <iframe
                title={title}
                src={srcUrl}
                className={styles["coapis-preview-iframe"]}
              />
            ) : (
              <Spin tip={t("chat.previewLoading", "加载中…")} />
            ))}
          {kind === "markdown" &&
            (rawView ? (
              <pre className={styles["coapis-preview-code"]}>{text}</pre>
            ) : (
              <div className={styles["coapis-preview-md"]}>
                <XMarkdown content={text ?? undefined} />
              </div>
            ))}
          {kind === "unsupported" && (
            <Empty
              description={t("chat.previewNoPreview", "该文件不支持预览")}
            />
          )}
          {kind === "text" && (
            <pre className={styles["coapis-preview-code"]}>{text}</pre>
          )}
        </div>
      </Spin>
    </FloatingWindow>
  );
}
