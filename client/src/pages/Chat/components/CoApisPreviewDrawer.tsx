import { getApiToken } from "@/api/config";
import { api } from "@/api";
import {
  Button,
  Drawer,
  Modal,
  Tooltip,
} from "@agentscope-ai/design";
// Space/Spin/Typography/Empty 不在 @agentscope-ai/design 的导出里（Empty 的
// image/description 在本包被收窄成 string），直接用底层 antd。
import { Empty, Space, Spin, Typography } from "antd";
import {
  AlertTriangle,
  Download,
  ExternalLink,
  FileText,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { XMarkdown } from "@ant-design/x-markdown";

import { getApiUrl } from "../../../api/config";
import { stripFrontmatter } from "../../../utils/markdown";
import { isPreviewablePath, toMyfilesParams } from "../workspaceLinks";

const { Text } = Typography;

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
}) {
  const { t } = useTranslation();
  const { target, onClose } = props;
  const [loading, setLoading] = useState(false);
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [truncated, setTruncated] = useState(false);
  const [converting, setConverting] = useState<string | null>(null);

  const ext = useMemo(() => extOf(target?.path || ""), [target?.path]);
  const path = target?.path || "";
  const category = target?.category || "files";
  const title = target?.title || path.split("/").pop() || path;
  const canPreview = isPreviewablePath(path);

  useEffect(() => {
    setText(null);
    setError(null);
    setTruncated(false);
    if (!target || !canPreview || IMAGE_EXT.has(ext) || ext === PDF_EXT) {
      setLoading(false);
      return;
    }
    let cancelled = false;
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
  const doConvert = useCallback(
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
          content: (
            <a href={myfilesUrl(out, "download")} target="_blank" rel="noreferrer">
              {resp?.name || out}
            </a>
          ),
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

  return (
    <Drawer
      open={!!target}
      onClose={onClose}
      placement="right"
      width={Math.min(760, typeof window !== "undefined" ? window.innerWidth * 0.92 : 760)}
      title={
        <Space size={6} style={{ maxWidth: "80%", overflow: "hidden" }}>
          <FileText size={14} style={{ flexShrink: 0 }} />
          <Text ellipsis style={{ maxWidth: 480 }} title={path}>
            {title}
          </Text>
        </Space>
      }
      extra={
        <Space size={4}>
          {isMd && (
            <>
              <Tooltip title={t("chat.preview.convert")}>
                <Button
                  size="small"
                  type="text"
                  loading={converting === "docx"}
                  onClick={() => doConvert("docx")}
                >
                  docx
                </Button>
              </Tooltip>
              <Tooltip title={t("chat.preview.convert")}>
                <Button
                  size="small"
                  type="text"
                  loading={converting === "pdf"}
                  onClick={() => doConvert("pdf")}
                >
                  pdf
                </Button>
              </Tooltip>
            </>
          )}
          <Tooltip title={t("chat.preview.download")}>
            <Button
              size="small"
              type="text"
              icon={<Download size={14} />}
              href={myfilesUrl(path, "download", category)}
              target="_blank"
            />
          </Tooltip>
          <Tooltip title={t("chat.preview.open")}>
            <Button
              size="small"
              type="text"
              icon={<ExternalLink size={14} />}
              href={myfilesUrl(path, "preview", category)}
              target="_blank"
            />
          </Tooltip>
          <Button size="small" type="text" icon={<X size={14} />} onClick={onClose} />
        </Space>
      }
      styles={{ body: { padding: 12, overflow: "auto" } }}
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
          src={myfilesUrl(target.path, "preview", category)}
          alt={title}
          style={{ maxWidth: "100%", display: "block", margin: "0 auto" }}
        />
      )}
      {!loading && !error && target && ext === PDF_EXT && (
        <iframe
          title={title}
          src={myfilesUrl(target.path, "preview", category)}
          style={{ width: "100%", height: "calc(100vh - 120px)", border: "none" }}
        />
      )}
      {!loading && !error && text !== null && (
        // md 走 markdown 渲染（与「我的空间」记忆面板同一渲染器），其余文本
        // 保持等宽原样 —— 日志/代码不该被 markdown 吃掉换行。
        isMd ? (
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
    </Drawer>
  );
}
