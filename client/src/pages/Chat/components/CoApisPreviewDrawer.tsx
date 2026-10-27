import {
  Button,
  Dropdown,
  Modal,
  Tooltip,
} from "@agentscope-ai/design";
// Space/Spin/Typography/Empty 不在 @agentscope-ai/design 的导出里（Empty 的
// image/description 在本包被收窄成 string），直接用底层 antd。
import { Empty, Segmented, Select, Space, Spin, Typography } from "antd";
import {
  AlertTriangle,
  ChevronDown,
  Copy,
  Download,
  FileText,
  FolderOpen,
  Link2,
  Maximize2,
  Minimize2,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { XMarkdown } from "@ant-design/x-markdown";
import useIsMobile from "../../../hooks/useIsMobile";
import { getChatGlobals } from "../../../lib/chatGlobals";

import { getApiToken, getApiUrl } from "@/api/config";
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

/* ================================================================== *
 * 浮窗几何（D3=C 真浮窗 · D1-补 头部拖动 + 八向缩放）
 *
 * 旧实现是 antd Drawer：贴右缘、只有左边界一条把手能拖宽（用户反馈「实现
 * 只有可以拖动左边框」）。这里换成挂在宿主容器内的绝对定位浮窗：头部可拖、
 * 四边四角可缩放，位置与尺寸写 localStorage，铺满/还原保留。
 * ================================================================== */

interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

type Edge = "n" | "s" | "e" | "w" | "ne" | "nw" | "se" | "sw";

const EDGES: Edge[] = ["n", "s", "e", "w", "ne", "nw", "se", "sw"];

const MIN_H = 260;
const DEFAULT_H = 560;
const SIZE_W_KEY = "coapis.previewWin.w";
const SIZE_H_KEY = "coapis.previewWin.h";
const POS_X_KEY = "coapis.previewWin.x";
const POS_Y_KEY = "coapis.previewWin.y";

const clampNum = (v: number, lo: number, hi: number) =>
  Math.min(Math.max(v, lo), Math.max(lo, hi));

function readNum(key: string): number | null {
  try {
    const raw = localStorage.getItem(key);
    if (raw === null) return null;
    const n = Number(raw);
    return Number.isFinite(n) ? n : null;
  } catch {
    return null;
  }
}

function safeSet(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* 隐私模式下 localStorage 会抛，忽略 */
  }
}

function persistRect(r: Rect) {
  safeSet(SIZE_W_KEY, String(Math.round(r.w)));
  safeSet(SIZE_H_KEY, String(Math.round(r.h)));
  safeSet(POS_X_KEY, String(Math.round(r.x)));
  safeSet(POS_Y_KEY, String(Math.round(r.y)));
}

/** 首次打开按宿主右上摆放；有记录则沿用并夹回宿主可视范围。 */
function initialRect(hostW: number, hostH: number): Rect {
  const w = clampNum(
    readNum(SIZE_W_KEY) ?? Math.min(560, Math.max(MIN_WIDTH, hostW)),
    MIN_WIDTH,
    Math.max(MIN_WIDTH, hostW),
  );
  const h = clampNum(
    readNum(SIZE_H_KEY) ?? DEFAULT_H,
    MIN_H,
    Math.max(MIN_H, hostH),
  );
  const savedX = readNum(POS_X_KEY);
  const savedY = readNum(POS_Y_KEY);
  return {
    x:
      savedX === null
        ? Math.max(0, hostW - w - 16)
        : clampNum(savedX, 0, Math.max(0, hostW - w)),
    y: savedY === null ? 12 : clampNum(savedY, 0, Math.max(0, hostH - h)),
    w,
    h,
  };
}

/** 把浮窗夹回宿主可视范围内（宿主变小 / 拖出边界时）。 */
function clampRect(r: Rect, hostW: number, hostH: number): Rect {
  const w = clampNum(r.w, MIN_WIDTH, Math.max(MIN_WIDTH, hostW));
  const h = clampNum(r.h, MIN_H, Math.max(MIN_H, hostH));
  return {
    x: clampNum(r.x, 0, Math.max(0, hostW - w)),
    y: clampNum(r.y, 0, Math.max(0, hostH - h)),
    w,
    h,
  };
}

/**
 * 头部切换器条目（D2：只列当前会话的资源，下拉选择即切换）。
 * 由聊天页把会话台账喂进来，作用域限定当前会话，不跨会话、不跨用户。
 */
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
  // §3.3：企微 H5/窄屏（含企微 H5 内嵌）→ 全屏弹层
  const isMobile = useIsMobile();
  // D3：铺满 = 占满宿主；还原 = 回到铺满前的位置尺寸
  const [maximized, setMaximized] = useState(false);
  const [rawView, setRawView] = useState(false);
  const [copied, setCopied] = useState(false);
  const [linkCopied, setLinkCopied] = useState(false);
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
  }, [target?.path, ext, canPreview, t]);

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

  const fullscreen = isMobile || getChatGlobals().mode === "embedded";
  const hostRef = useRef<HTMLElement | null>(null);
  const [host, setHost] = useState<HTMLElement | null>(null);
  const rectRef = useRef<Rect>({ x: 0, y: 0, w: savedWidth(), h: DEFAULT_H });
  const [rect, setRectState] = useState<Rect>(rectRef.current);
  const setRect = useCallback((next: Rect) => {
    rectRef.current = next;
    setRectState(next);
  }, []);
  /** 拖动/缩放中：关掉过渡，跟手 */
  const [interacting, setInteracting] = useState(false);
  const prevRectRef = useRef<Rect | null>(null);
  const onMoveRef = useRef<((ev: MouseEvent) => void) | null>(null);
  const maximizedRef = useRef(false);
  maximizedRef.current = maximized;
  const open = !!target;

  // 打开时定位：宿主必须是定位上下文，否则浮窗会跑到整页
  useEffect(() => {
    if (!open) return;
    const el = resolveHost();
    if (!el) return;
    hostRef.current = el;
    setHost(el);
    if (getComputedStyle(el).position === "static") {
      el.style.position = "relative";
    }
    setRect(
      fullscreen
        ? { x: 0, y: 0, w: el.clientWidth, h: el.clientHeight }
        : initialRect(el.clientWidth, el.clientHeight),
    );
  }, [open, fullscreen, resolveHost, setRect]);

  // 宿主尺寸变化：铺满/全屏时跟随，否则把浮窗夹回可视范围
  useEffect(() => {
    if (!open || !host) return;
    const onResize = () => {
      const hw = host.clientWidth;
      const hh = host.clientHeight;
      setRect(
        fullscreen
          ? { x: 0, y: 0, w: hw, h: hh }
          : clampRect(rectRef.current, hw, hh),
      );
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [open, host, fullscreen, setRect]);

  const endInteraction = useCallback(
    (onUp: () => void) => {
      if (onMoveRef.current) {
        document.removeEventListener("mousemove", onMoveRef.current);
        onMoveRef.current = null;
      }
      document.removeEventListener("mouseup", onUp);
      document.body.style.userSelect = "";
      document.body.style.cursor = "";
      setInteracting(false);
      if (!maximizedRef.current) persistRect(rectRef.current);
    },
    [],
  );

  // 头部拖动（铺满/全屏时禁拖，避免把浮窗拖没）
  const startDrag = useCallback(
    (e: React.MouseEvent) => {
      if (fullscreen || maximized) return;
      if ((e.target as HTMLElement).closest("[data-nodrag]")) return;
      const el = hostRef.current;
      if (!el) return;
      const start = rectRef.current;
      const sx = e.clientX;
      const sy = e.clientY;
      setInteracting(true);
      document.body.style.userSelect = "none";
      document.body.style.cursor = "move";
      const onMove = (ev: MouseEvent) => {
        setRect(
          clampRect(
            {
              x: start.x + (ev.clientX - sx),
              y: start.y + (ev.clientY - sy),
              w: start.w,
              h: start.h,
            },
            el.clientWidth,
            el.clientHeight,
          ),
        );
      };
      onMoveRef.current = onMove;
      const onUp = () => endInteraction(onUp);
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    },
    [fullscreen, maximized, setRect, endInteraction],
  );

  // 八向缩放：四边 + 四角
  const startResize = useCallback(
    (edge: Edge) =>
      (e: React.MouseEvent) => {
        e.preventDefault();
        e.stopPropagation();
        const el = hostRef.current;
        if (!el) return;
        const start = rectRef.current;
        const sx = e.clientX;
        const sy = e.clientY;
        let w = start.w;
        let h = start.h;
        let x = start.x;
        let y = start.y;
        setInteracting(true);
        document.body.style.userSelect = "none";
        const onMove = (ev: MouseEvent) => {
          const hw = el.clientWidth;
          const hh = el.clientHeight;
          const dx = ev.clientX - sx;
          const dy = ev.clientY - sy;
          const maxW = Math.max(MIN_WIDTH, hw);
          const maxH = Math.max(MIN_H, hh);
          w = start.w;
          h = start.h;
          x = start.x;
          y = start.y;
          if (edge.includes("e")) w = clampNum(start.w + dx, MIN_WIDTH, maxW);
          if (edge.includes("s")) h = clampNum(start.h + dy, MIN_H, maxH);
          if (edge.includes("w")) {
            const nw = clampNum(start.w - dx, MIN_WIDTH, maxW);
            x = start.x + (start.w - nw);
            w = nw;
          }
          if (edge.includes("n")) {
            const nh = clampNum(start.h - dy, MIN_H, maxH);
            y = start.y + (start.h - nh);
            h = nh;
          }
          setRect(clampRect({ x, y, w, h }, hw, hh));
        };
        onMoveRef.current = onMove;
        const onUp = () => endInteraction(onUp);
        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
      },
    [setRect, endInteraction],
  );

  // 铺满 / 还原
  const toggleMaximize = useCallback(() => {
    const el = hostRef.current;
    const next = !maximized;
    if (next) {
      prevRectRef.current = rectRef.current;
      if (el) setRect({ x: 0, y: 0, w: el.clientWidth, h: el.clientHeight });
    } else if (prevRectRef.current) {
      setRect(prevRectRef.current);
    }
    maximizedRef.current = next;
    setMaximized(next);
    if (!next) persistRect(rectRef.current);
  }, [maximized, setRect]);

  if (!target || !host) return null;

  // D2：头部切换器只列**当前会话**的资源（台账作用域 = 当前 chat_id）
  const switchOptions: { value: string; label: string; title: string }[] = [];
  const seenPath = new Set<string>();
  (items ?? []).forEach((it) => {
    if (!it?.path || seenPath.has(it.path)) return;
    seenPath.add(it.path);
    switchOptions.push({
      value: it.path,
      label: it.title || it.path.split("/").pop() || it.path,
      title: it.path,
    });
  });
  if (!seenPath.has(path)) {
    switchOptions.unshift({ value: path, label: title, title: path });
  }

  return createPortal(
    <div
      className={styles["coapis-preview-win"]}
      style={{
        left: rect.x,
        top: rect.y,
        width: rect.w,
        height: rect.h,
        transition: interacting ? "none" : undefined,
      }}
      role="dialog"
      aria-label={title}
    >
      {/* D1-补：四边 + 四角都能拖（旧版只有左缘一条把手） */}
      {!fullscreen &&
        !maximized &&
        EDGES.map((edge) => (
          <div
            key={edge}
            className={styles[`rz-${edge}`]}
            onMouseDown={startResize(edge)}
          />
        ))}

      <div
        className={styles["coapis-preview-win-header"]}
        onMouseDown={startDrag}
        style={{
          cursor: fullscreen || maximized ? "default" : "move",
        }}
      >
        <FileText size={14} className={styles["coapis-preview-icon"]} />
        <span className={styles["coapis-preview-head-title"]} data-nodrag>
          <Select
            size="small"
            className={styles["coapis-preview-switch"]}
            popupClassName={styles["coapis-preview-switch-dd"]}
            value={path}
            onChange={(v: string) => {
              const hit = (items ?? []).find((i) => i.path === v);
              if (hit) onSelect?.(hit);
            }}
            showSearch
            optionFilterProp="label"
            listHeight={280}
            popupMatchSelectWidth={false}
            suffixIcon={<ChevronDown size={12} />}
            options={switchOptions}
          />
        </span>
        <span className={styles["coapis-preview-head-spacer"]} />
        <span data-nodrag>
          <Dropdown
            menu={{
              items: [
                {
                  key: "raw",
                  icon: <Download size={12} />,
                  label: t("chat.downloadRaw", "下载原文件"),
                  onClick: () => void downloadFile(path, title),
                },
                ...convertTargets.map((fmt) => ({
                  key: `conv-${fmt}`,
                  icon: <Download size={12} />,
                  label: t("chat.convertDownload", "转换为 {{fmt}} 后下载", {
                    fmt,
                  }),
                  disabled: converting === fmt,
                  onClick: () => void convertAndDownload(fmt),
                })),
              ],
            }}
            trigger={["click"]}
          >
            <Button
              type="text"
              size="small"
              loading={converting !== null}
              icon={
                <Space size={2}>
                  <Download size={14} />
                  <ChevronDown size={12} />
                </Space>
              }
            />
          </Dropdown>
        </span>
        {!fullscreen && (
          <span data-nodrag>
            <Tooltip
              title={
                maximized
                  ? t("chat.previewRestore", "还原")
                  : t("chat.previewMaximize", "铺满")
              }
            >
              <Button
                type="text"
                size="small"
                icon={maximized ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
                onClick={toggleMaximize}
              />
            </Tooltip>
          </span>
        )}
        <span data-nodrag>
          <Tooltip title={t("chat.close", "关闭")}>
            <Button type="text" size="small" icon={<X size={14} />} onClick={onClose} />
          </Tooltip>
        </span>
      </div>

      {isMd && (
        <div className={styles["coapis-preview-mdbar"]}>
          <Segmented
            size="small"
            value={rawView ? "raw" : "render"}
            onChange={(v) => setRawView(v === "raw")}
            options={[
              {
                value: "render",
                label: t("chat.previewRender", "渲染"),
              },
              {
                value: "raw",
                label: t("chat.previewRaw", "原文"),
              },
            ]}
          />
          <Tooltip
            title={
              copied ? t("chat.copied", "已复制") : t("chat.copyContent", "复制内容")
            }
          >
            <Button
              type="text"
              size="small"
              icon={<Copy size={12} />}
              disabled={!text}
              onClick={() => void copyFull()}
            />
          </Tooltip>
        </div>
      )}

      <Spin spinning={loading} wrapperClassName={styles["coapis-preview-spin"]}>
        <div className={styles["coapis-preview-win-body"]}>
          {error ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={
                <Text type="danger">{error}</Text>
              }
            />
          ) : kind === "image" ? (
            srcUrl ? (
              <img
                src={srcUrl}
                alt={title}
                className={styles["coapis-preview-image"]}
              />
            ) : (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={t("chat.previewLoading", "加载中…")}
              />
            )
          ) : kind === "pdf" ? (
            srcUrl ? (
              <iframe
                title={title}
                src={srcUrl}
                className={styles["coapis-preview-iframe"]}
              />
            ) : (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={t("chat.previewLoading", "加载中…")}
              />
            )
          ) : kind === "markdown" ? (
            rawView ? (
              <pre className={styles["coapis-preview-code"]}>
                {truncated && (
                  <div className={styles["coapis-preview-truncated"]}>
                    <AlertTriangle size={12} />
                    <span>{t("chat.previewTruncated", "内容过长，已截断")}</span>
                  </div>
                )}
                {text}
              </pre>
            ) : (
              <div className={styles["coapis-preview-md"]}>
                {truncated && (
                  <div className={styles["coapis-preview-truncated"]}>
                    <AlertTriangle size={12} />
                    <span>{t("chat.previewTruncated", "内容过长，已截断")}</span>
                  </div>
                )}
                <XMarkdown content={text ?? ""} />
              </div>
            )
          ) : (
            <pre className={styles["coapis-preview-code"]}>
              {truncated && (
                <div className={styles["coapis-preview-truncated"]}>
                  <AlertTriangle size={12} />
                  <span>{t("chat.previewTruncated", "内容过长，已截断")}</span>
                </div>
              )}
              {text}
            </pre>
          )}
        </div>
      </Spin>

      <div className={styles["coapis-preview-win-footer"]}>
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
      </div>
    </div>,
    host,
  );
}
