import {
  Button,
  Drawer,
  Dropdown,
  Modal,
  Tooltip,
} from "@agentscope-ai/design";
// Space/Spin/Typography/Empty 不在 @agentscope-ai/design 的导出里（Empty 的
// image/description 在本包被收窄成 string），直接用底层 antd。
import { Empty, Segmented, Space, Spin, Typography } from "antd";
import {
  AlertTriangle,
  ChevronDown,
  Copy,
  Download,
  ExternalLink,
  FileText,
  FolderOpen,
  Link2,
  Maximize2,
  Minimize2,
  MoreHorizontal,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { XMarkdown } from "@ant-design/x-markdown";
import useIsMobile from "../../../hooks/useIsMobile";
import { getChatGlobals } from "../../../lib/chatGlobals";

import { getApiToken, getApiUrl } from "@/api/config";
import { api } from "../../../api";
import { stripFrontmatter } from "../../../utils/markdown";
import styles from "./CoApisPreviewDrawer.module.less";
import {
  canInlinePreview,
  copyDirectLink,
  convertTargetsFor,
  downloadFile,
  openPreviewWindow,
  previewSrcUrl,
  requestPreviewTicket,
  absoluteUrl,
} from "../../../utils/webPreview";
import { toMyfilesParams } from "../workspaceLinks";

const { Text } = Typography;

/**
 * 转换成功后的下载链接（D6）：点击时现取 60s 一次性票据再下载，
 * 浏览器历史 / 服务器日志里不会出现 JWT；取不到票据退回带 token 直链。
 */
function TicketDownload({ path, name }: { path: string; name: string }) {
  const [href, setHref] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    void (async () => {
      const t = await requestPreviewTicket(path, "download");
      if (alive && t) setHref(absoluteUrl(t));
    })();
    return () => {
      alive = false;
    };
  }, [path]);
  return (
    <a
      href={href ?? myfilesUrl(path, "download")}
      target="_blank"
      rel="noreferrer"
    >
      {name}
    </a>
  );
}

/** 抽屉默认宽度（方案 D1：480px，左边缘可拖拽调宽）。 */
const DEFAULT_WIDTH = 480;
/** 拖拽下限：再窄标题与按钮就挤成一坨。 */
const MIN_WIDTH = 340;
/** 宽度记忆键（方案 D1：拖完写 localStorage，下次打开保持）。 */
const WIDTH_KEY = "coapis.previewDrawer.width";

function savedWidth(): number {
  try {
    const v = Number(localStorage.getItem(WIDTH_KEY));
    return Number.isFinite(v) && v >= MIN_WIDTH ? v : DEFAULT_WIDTH;
  } catch {
    return DEFAULT_WIDTH;
  }
}

/** §3.3 底部固定栏：相对工作区根的展示路径（files/…）。 */
function displayPath(target: PreviewTarget): string {
  const cat = (target.category || "files").replace(/^\/+|\/+$/g, "");
  const rel = (target.path || "").replace(/^\/+/, "");
  return rel.startsWith(`${cat}/`) ? rel : `${cat}/${rel}`;
}

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
   * 抽屉挂载点（方案 F1）。聊天页传「主内容区」节点，抽屉就锚在**主内容窗口**
   * 里 —— 高度 = 主内容高度，不再铺满整个浏览器窗口（实测旧版 y=0/h=900，
   * 主内容区是 y=117/h=750）。未传时退回 antd 默认（document.body）。
   */
  getContainer?: HTMLElement | (() => HTMLElement | null) | null;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  // §3.3：右侧抽屉 480px；企微 H5/窄屏（含企微 H5 内嵌）→ 全屏弹层
  const isMobile = useIsMobile();
  // 方案 D1：默认 480px，左边缘可拖拽调宽；D2「铺满」→ 容器内 100% 宽
  const [width, setWidth] = useState<number>(savedWidth);
  const [maximized, setMaximized] = useState(false);
  const drawerWidth =
    isMobile || getChatGlobals().mode === "embedded" || maximized
      ? "100%"
      : width;
  const [rawView, setRawView] = useState(false);
  const [copied, setCopied] = useState(false);
  const [linkCopied, setLinkCopied] = useState(false);
  const { target, onClose, getContainer } = props;
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
  }, [target?.path, ext, canPreview, t]);

  // 转格式入口（B5）：md 是默认产出格式，交付那一刻按需转一次。原本只有
  // 智能体能转（convert_file 工具），用户在预览里点一下就能转，产物落进
  // 同目录同名并进台账（我的空间与会话资源条都能看到）。
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

  const convertFile = useCallback(
    async (target2: "docx" | "pdf") => {
      if (!path || converting) return;
      setConverting(target2);
      try {
        const resp = await api.post<{ path?: string; name?: string }>(
          `/myfiles/convert?path=${encodeURIComponent(path)}&target=${target2}`,
        );
        const out = resp?.path;
        if (!out) throw new Error(t("chat.preview.convertFailed"));
        setText(null);
        setError(null);
        Modal.success({
          title: t("chat.preview.convertDone"),
          content: <TicketDownload path={out} name={resp?.name || out} />,
        });
      } catch (e: any) {
        Modal.error({
          title: t("chat.preview.convertFailed"),
          content: String(e?.message || e),
        });
      } finally {
        setConverting(null);
      }
    },
    [path, converting, t],
  );

  const isMd = MD_EXT.has(ext);
  // 注：原 §3.3 的 isText（复制全文门控）已随「复制」下移到 md 工具条而退役；
  // 转格式目标改由共享口径 convertTargetsFor 决定（只对 md/txt 出项）。

  // F2：转换目标只列后端真支持的三种，且不含自身格式（避免「md 转 md」这种废项）
  const convertTargets = convertTargetsFor(path);

  // F3：「定位」= 去「我的空间」并带 locate 参数（页面展开目录 + 高亮 + 滚动）
  const locateInWorkspace = useCallback(() => {
    navigate("/workspace/myspace?locate=" + encodeURIComponent(path));
  }, [navigate, path]);

  // ── 方案 D1：左缘拖拽调宽（340px ~ 容器 90%），宽度写 localStorage 记忆 ──
  const draggingRef = useRef(false);
  const [dragging, setDragging] = useState(false);
  const startResize = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      const host =
        (typeof getContainer === "function"
          ? getContainer()
          : (getContainer as HTMLElement | null)) ?? null;
      const right = host?.getBoundingClientRect?.().right ?? window.innerWidth;
      // 拖拽期间禁掉抽屉的宽度过渡动画（走 styles.wrapper，不依赖 antd 类名）
      draggingRef.current = true;
      setDragging(true);
      document.body.style.userSelect = "none";
      document.body.style.cursor = "col-resize";
      const onMove = (ev: MouseEvent) => {
        if (!draggingRef.current) return;
        const max = Math.max(
          MIN_WIDTH,
          (host?.clientWidth ?? window.innerWidth) * 0.9,
        );
        setMaximized(false);
        setWidth(Math.round(Math.min(max, Math.max(MIN_WIDTH, right - ev.clientX))));
      };
      const onUp = () => {
        draggingRef.current = false;
        setDragging(false);
        document.body.style.userSelect = "";
        document.body.style.cursor = "";
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        setWidth((w) => {
          try {
            localStorage.setItem(WIDTH_KEY, String(w));
          } catch {
            /* 隐私模式下 localStorage 会抛，忽略 */
          }
          return w;
        });
      };
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    },
    [getContainer],
  );

  // ── 方案 D2：铺满 / 还原（容器内 100% 宽，主区缩放时跟随） ──
  const toggleMaximize = useCallback(() => {
    setMaximized((m) => {
      const host =
        (typeof getContainer === "function"
          ? getContainer()
          : (getContainer as HTMLElement | null)) ?? null;
      if (!m && host) {
        setWidth(Math.max(MIN_WIDTH, host.clientWidth - 8));
      } else {
        setWidth(savedWidth());
      }
      return !m;
    });
  }, [getContainer]);

  useEffect(() => {
    if (!maximized) return;
    const host =
      (typeof getContainer === "function"
        ? getContainer()
        : (getContainer as HTMLElement | null)) ?? null;
    if (!host) return;
    const onResize = () => setWidth(Math.max(MIN_WIDTH, host.clientWidth - 8));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [maximized, getContainer]);

  return (
    <Drawer
      open={!!target}
      onClose={onClose}
      placement="right"
      width={drawerWidth}
      // F1：锚定聊天主内容区 —— 抽屉高度 = 主内容高度，不再铺满浏览器窗口
      getContainer={getContainer as never}
      rootClassName={styles["coapis-preview-drawer"]}
      // antd v5 的 Drawer 只认 styles={{mask,wrapper,content}}；v4 时代的
      // drawerStyle / drawerBodyStyle / drawerHeaderStyle 都是空转（被 spread 到
      // DOM 上还会触发未知属性告警），已全部移除，内边距交给 LESS 里的
      // :global(.coapis-drawer-header / -body)。
      styles={{
        wrapper: dragging ? { transition: "none" } : undefined,
        content: { overflow: "hidden" },
      }}
      title={
        <Space size={6} style={{ maxWidth: "80%", overflow: "hidden" }}>
          <FileText size={14} style={{ flexShrink: 0 }} />
          <Text ellipsis style={{ maxWidth: 480 }} title={path}>
            {title}
          </Text>
        </Space>
      }
      extra={
        // 方案 F3：头部只留「主操作 + 一个 ⋯ + 铺满 + 关闭」。
        // 旧版把 复制/转docx/转pdf/下载/新标签/关闭 平铺在 480px 宽的头里，
        // 标题被挤成一行省略号 —— 这就是「布局很不友好」的直接来源。
        <Space size={2} align="center">
          {/* 方案 F2/D4：下载下拉 = 原件 + 转格式项（转格式只对 md/txt 出现） */}
          <Dropdown
            trigger={["click"]}
            menu={{
              items: [
                {
                  key: "raw",
                  icon: <Download size={14} />,
                  label: t("chat.preview.downloadOriginal", {
                    ext: ext ? ext.slice(1) : "",
                  }),
                },
                ...convertTargets.map((fmt) => ({
                  key: `to-${fmt}`,
                  icon: <FileText size={14} />,
                  label: t("chat.preview.convertTo", { fmt: fmt.toUpperCase() }),
                  disabled: converting === fmt,
                })),
              ],
              onClick: ({ key }: { key: string }) => {
                if (key === "raw") void downloadFile(path, title);
                else void convertFile(String(key).slice(3) as "pdf" | "docx");
              },
            }}
          >
            <Button size="small" type="text">
              <Space size={4}>
                <Download size={14} />
                {t("chat.preview.download")}
                <ChevronDown size={12} />
              </Space>
            </Button>
          </Dropdown>
          {/* 次要操作收进 ⋯：复制直链 / 在我的空间定位 / 新窗口预览 */}
          <Dropdown
            trigger={["click"]}
            menu={{
              items: [
                {
                  key: "link",
                  icon: <Link2 size={14} />,
                  label: linkCopied
                    ? t("chat.preview.copied")
                    : t("chat.preview.copyLink"),
                },
                {
                  key: "locate",
                  icon: <FolderOpen size={14} />,
                  label: t("chat.preview.locate"),
                },
                {
                  key: "window",
                  icon: <ExternalLink size={14} />,
                  label: t("chat.preview.open"),
                },
              ],
              onClick: ({ key }: { key: string }) => {
                if (key === "link") void copyLink();
                else if (key === "locate") locateInWorkspace();
                else void openPreviewWindow(path);
              },
            }}
          >
            <Tooltip title={t("chat.preview.more")}>
              <Button
                size="small"
                type="text"
                icon={<MoreHorizontal size={14} />}
              />
            </Tooltip>
          </Dropdown>
          {/* 方案 D2：铺满 / 还原 */}
          <Tooltip
            title={
              maximized ? t("chat.preview.restore") : t("chat.preview.maximize")
            }
          >
            <Button
              size="small"
              type="text"
              icon={maximized ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
              onClick={toggleMaximize}
            />
          </Tooltip>
          <Button size="small" type="text" icon={<X size={14} />} onClick={onClose} />
        </Space>
      }
      footer={
        // §3.3 底部固定栏：相对路径 +「在我的空间定位」+「复制直链」
        // 单行不换行（原来 flexWrap:wrap 在 480px 里折成 3 行、footer 占 117px）：
        // 路径 flex:1 省略号 + Tooltip 看全名，按钮 shrink:0。
        target ? (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              fontSize: 12,
              whiteSpace: "nowrap",
            }}
          >
            <Tooltip title={displayPath(target)}>
              <Text
                code
                style={{ flex: 1, minWidth: 0, fontSize: 12, overflow: "hidden", textOverflow: "ellipsis" }}
              >
                <FolderOpen size={12} style={{ verticalAlign: -2 }} /> {displayPath(target)}
              </Text>
            </Tooltip>
            <Tooltip title={t("chat.preview.locate")}>
              <Button
                size="small"
                style={{ flexShrink: 0 }}
                icon={<FolderOpen size={13} />}
                aria-label={t("chat.preview.locate")}
                onClick={() =>
                  navigate(
                    `/workspace/myspace?locate=${encodeURIComponent(target.path)}`,
                  )
                }
              />
            </Tooltip>
            <Tooltip
              title={linkCopied ? t("chat.preview.copyLinkDone", "直链已复制") : t("chat.preview.copyLink")}
            >
              <Button
                size="small"
                style={{ flexShrink: 0 }}
                type={linkCopied ? "primary" : "default"}
                icon={<Link2 size={13} />}
                aria-label={t("chat.preview.copyLink")}
                onClick={() => void copyDirectLink(path).then((ok) => setLinkCopied(ok))}
              />
            </Tooltip>
          </div>
        ) : null
      }
    >
      {/* 方案 D1：左缘拖拽把手（340px ~ 容器 90%，松手写 localStorage） */}
      <div
        className={styles["coapis-preview-resize-handle"]}
        onMouseDown={startResize}
        title={t("chat.preview.resize")}
      />
      {/* 渲染/原文切换从头部下移到正文上方：480px 宽里塞 6 个控件会把标题挤没 */}
      {isMd && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            borderBottom: "1px solid rgba(0, 0, 0, 0.06)",
            flexShrink: 0,
          }}
        >
          <Segmented
            size="small"
            value={rawView ? "raw" : "rendered"}
            onChange={(v) => setRawView(v === "raw")}
            options={[
              { label: t("chat.preview.render"), value: "rendered" },
              { label: t("chat.preview.source"), value: "raw" },
            ]}
          />
          <span style={{ flex: 1 }} />
          <Tooltip title={copied ? t("chat.preview.copied") : t("chat.preview.copy")}>
            <Button
              size="small"
              type={copied ? "primary" : "text"}
              icon={<Copy size={14} />}
              onClick={copyFull}
            />
          </Tooltip>
        </div>
      )}
      <Spin
        spinning={!!target && srcUrl === null && (IMAGE_EXT.has(ext) || ext === PDF_EXT)}
        // Spin 的根节点才是 body 的 flex 子元素：不给它 flex:1，正文只会按内容
        // 高度收缩（实测 85px），下方留大片空白。
        style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}
      >
        <div
          style={{
            flex: 1,
            minHeight: 0,
            display: "flex",
            flexDirection: "column",
            overflow: "auto",
            padding: "12px 16px",
          }}
        >
      {loading && (
        <div style={{ textAlign: "center", padding: 40 }}>
          <Spin />
        </div>
      )}
      {!loading && error && (
        <Empty
          image={<AlertTriangle size={28} style={{ color: "#f5a623" }} />}
          description={error}
        />
      )}
      {!loading && !error && target && IMAGE_EXT.has(ext) && (
        <img
          // D6：图片走 60s 一次性票据，URL 里不再出现 JWT（token 会进历史/Referer）
          src={srcUrl ?? myfilesUrl(target.path, "preview", category)}
          alt={title}
          style={{ maxWidth: "100%", display: "block", margin: "0 auto" }}
        />
      )}
      {!loading && !error && target && ext === PDF_EXT && (
        <iframe
          title={title}
          src={srcUrl ?? myfilesUrl(target.path, "preview", category)}
          // F1：抽屉已锚定主区，正文铺满容器高度（原 calc(100vh-120px) 是窗口高）
          style={{ width: "100%", height: "100%", flex: 1, minHeight: 0, border: "none" }}
        />
      )}
      {!loading && !error && text !== null && (
        // md 走 markdown 渲染（与「我的空间」记忆面板同一渲染器），其余文本
        // 保持等宽原样 —— 日志/代码不该被 markdown 吃掉换行。
        // §3.3「原文/渲染」切换：切到「原文」时 md 也走等宽源文本。
        isMd && !rawView ? (
          <div style={{ fontSize: 13, lineHeight: 1.7 }}>
            <XMarkdown>{stripFrontmatter(text)}</XMarkdown>
          </div>
        ) : (
          <pre
            style={{
              margin: 0,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              fontSize: 12.5,
              lineHeight: 1.6,
              fontFamily:
                "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Noto Sans CJK SC', monospace",
            }}
          >
            {text}
          </pre>
        )
      )}
      {!loading && !error && text === null && truncated && (
        <Empty description={t("chat.preview.tooLarge")} />
      )}
      {!loading && !error && text === null && !truncated && !canPreview && (
        <Empty description={t("chat.preview.unsupported")} />
      )}
        </div>
      </Spin>
    </Drawer>
  );
}
