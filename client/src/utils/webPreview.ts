/**
 * 会话资源 / 我的空间共用的「预览 / 下载」工具（方案 §3.2 L2、§12.3）
 * ---------------------------------------------------------------------------
 * 产出卡（L1）、本轮资源条（L2）、会话资源 Tab（L3）三处都要「点开一个文件」，
 * 此前各自内联拼 URL，三套词汇、三套鉴权写法；而这三处都 `import
 * "@/utils/webPreview"`，该模块却从未建立 —— 前端整片资源代码因此一次都没
 * 编译过（2026-10-23 实测：tsc 报 TS2307 找不到模块）。本文件补齐这一层。
 *
 * 统一约定（与后端 server/coapis/app/routers/files.py 一一对应）：
 *   GET  /api/myfiles/preview?path=&category=   在线预览（文本/图片/PDF 内联）
 *   GET  /api/myfiles/download?path=&category=  原样下载
 *   POST /api/myfiles/convert?path=&target=&category=&chat_id=  转格式
 *
 * ⚠️ `path` 是**分类目录内**的相对路径（`x.md`），不是工作区相对路径
 *   （`files/x.md`）。换算统一走 workspaceLinks.toMyfilesParams，勿手拼。
 *
 * 鉴权：`window.open` 带不上 Authorization 头，故附 `?token=`
 *   （auth_middleware 支持从 query_params 取 token）。
 */
import { getApiToken } from "../api/config";
import {
  isPreviewablePath,
  pathSuffix,
  toMyfilesParams,
  toWorkspaceRel,
} from "../pages/Chat/workspaceLinks";
import { toDisplayUrl } from "../pages/Chat/utils";

// 展示路径归一（file:// → 相对路径）只此一份实现，转发给资源组件复用。
export { toDisplayUrl };

/**
 * 台账路径 → 我的空间相对路径（`files/…`），供「预览」分类与抽屉取文件用。
 *
 * 为什么不能直接用 `toDisplayUrl`（2026-10-23 实测的 P1）：它是**展示**用
 * 归一，对台账存的工作区相对路径 `files/2026-10/x.md` 返回的是
 * `/api/myfiles/download?path=…&category=files` 这种带 query 的 URL；
 * `getPreviewKind` 在 URL 尾上取不到扩展名 → 判为 unsupported → 三处
 * 资源入口（L1 产出卡 / L2 资源条 / L3 会话资源）的「预览」全部退化成
 * 下载，抽屉一次都没出现过（浏览器实测：点击只发 /myfiles/download）。
 */
export function toLedgerRelPath(raw: string | undefined): string {
  const trimmed = String(raw ?? "").trim();
  return toWorkspaceRel(trimmed) || trimmed;
}

export type PreviewKind =
  | "image"
  | "pdf"
  | "markdown"
  | "text"
  | "office"
  | "unsupported";

const IMAGE_EXT = new Set([
  "png",
  "jpg",
  "jpeg",
  "gif",
  "webp",
  "bmp",
  "svg",
  "ico",
  "tiff",
]);
const PDF_EXT = new Set(["pdf"]);
const MARKDOWN_EXT = new Set(["md", "markdown", "mdx"]);
/** Office 文档：预览端点转 markdown 后内联渲染 */
const OFFICE_EXT = new Set([
  "doc",
  "docx",
  "xls",
  "xlsx",
  "ppt",
  "pptx",
  "odt",
  "ods",
  "odp",
]);
const TEXT_EXT = new Set([
  "txt",
  "text",
  "log",
  "json",
  "jsonl",
  "yaml",
  "yml",
  "toml",
  "ini",
  "cfg",
  "conf",
  "csv",
  "tsv",
  "xml",
  "rst",
  "html",
  "htm",
  "css",
  "scss",
  "less",
  "js",
  "jsx",
  "ts",
  "tsx",
  "py",
  "sh",
  "bash",
  "sql",
  "java",
  "go",
  "rs",
  "c",
  "h",
  "cpp",
  "hpp",
  "cs",
  "php",
  "rb",
  "vue",
]);

/** `files/a/b.png` → `png`（无扩展名返回 ""）。 */
export function extOf(p: string): string {
  const s = pathSuffix(p);
  return s.startsWith(".") ? s.slice(1) : s;
}

/** 工作区相对路径 → 我的空间分类（files/ → files，media/ → media，其余 files）。 */
export function categoryOf(p: string): string {
  return toMyfilesParams(p).category;
}

/** 扩展名 → 预览类型；不在白名单返回 "unsupported"（调用方据此收起预览入口）。 */
export function getPreviewKind(p: string): PreviewKind {
  const ext = extOf(p);
  if (!ext) return "unsupported";
  if (IMAGE_EXT.has(ext)) return "image";
  if (PDF_EXT.has(ext)) return "pdf";
  if (MARKDOWN_EXT.has(ext)) return "markdown";
  if (OFFICE_EXT.has(ext)) return "office";
  if (TEXT_EXT.has(ext)) return "text";
  return "unsupported";
}

/** 预览类型 → 中文标签（资源条与资源 Tab 共用一份措辞）。 */
export const PREVIEW_KIND_LABEL: Record<PreviewKind, string> = {
  image: "图片",
  pdf: "PDF",
  markdown: "Markdown",
  text: "文本",
  office: "Office",
  unsupported: "不可预览",
};

/**
 * 我的空间端点 URL。mode = "preview" | "download"。
 * `extra` 传额外 query（形如 `&chat_id=1`，自带前导 &）。
 */
export function myfilesUrl(
  relPath: string,
  mode: "preview" | "download",
  extra = "",
): string {
  const { category, path } = toMyfilesParams(relPath);
  const token = getApiToken();
  return (
    `/api/myfiles/${mode}?path=${encodeURIComponent(path)}` +
    `&category=${encodeURIComponent(category)}` +
    (token ? `&token=${encodeURIComponent(token)}` : "") +
    extra
  );
}

/** 会话归属参数（转换接口按会话命名产物）；无会话 id 时返回空串。 */
export function chatIdQuery(chatId?: string | number): string {
  return chatId === undefined || chatId === null || chatId === ""
    ? ""
    : `&chat_id=${encodeURIComponent(String(chatId))}`;
}

/**
 * 打开预览：新标签走 /myfiles/preview。
 * 白名单外的类型直接给下载，避免点开一个空白页。
 *
 * `title` 只用于日志/兜底命名，预览页标题由后端 Content-Disposition 决定。
 */
export function previewFile(displayPath: string, title?: string): void {
  const p = String(displayPath || "").trim();
  if (!p) return;
  if (!isPreviewablePath(p)) {
    void downloadFile(p, title || basename(p));
    return;
  }
  window.open(myfilesUrl(p, "preview"), "_blank", "noopener,noreferrer");
}

/**
 * 下载文件。
 *
 * @param rawPath    工作区相对路径（内部换算成我的空间 path/category）
 * @param filename   落盘文件名（浏览器 download 属性用，取自标题）
 * @param targetExt  **目标**扩展名：与源文件一致/省略时原样下载；
 *                   为 pdf/docx/md 时先请后端转换再下载产物
 * @param kind       资源类型（file/image/pdf/markdown…）；不是扩展名，
 *                   仅用于 md↔markdown 之类的同义判断，绝不拿去当 target
 *
 * 转换失败退回原文件下载，不静默吞掉。
 */
export async function downloadFile(
  rawPath: string,
  filename?: string,
  targetExt?: string,
  kind?: string,
): Promise<void> {
  const p = String(rawPath || "").trim();
  if (!p) return;
  const name = String(filename || "").trim() || basename(p);
  const sourceExt = extOf(p);
  const want = String(targetExt || "").toLowerCase();
  // 只认后端支持的三种转换目标；其余（含误传进来的 kind）一律原样下载
  const target = CONVERT_TARGETS.has(want) ? want : "";

  const sameFormat =
    !target ||
    target === sourceExt ||
    (sourceExt === "md" && target === "markdown") ||
    (sourceExt === "markdown" && target === "md");

  if (sameFormat) {
    await saveFile(myfilesUrl(p, "download"), name);
    return;
  }

  const { category, path } = toMyfilesParams(p);
  const token = getApiToken();
  const q = new URLSearchParams({
    path,
    target: target === "markdown" ? "md" : target,
    category,
  });
  void kind; // 预留：kind 不参与 target 决策（见上）
  try {
    const res = await fetch(
      `/api/myfiles/convert?${q.toString()}` +
        (token ? `&token=${encodeURIComponent(token)}` : ""),
      { method: "POST", headers: authHeaders() },
    );
    if (!res.ok) {
      await saveFile(myfilesUrl(p, "download"), name);
      return;
    }
    const data = await res.json();
    const out = String(data?.path || "");
    if (!out) return;
    await saveFile(myfilesUrl(out, "download"), `${name}.${target}`);
  } catch {
    await saveFile(myfilesUrl(p, "download"), name);
  }
}

/** 后端 /myfiles/convert 支持的转换目标白名单。 */
const CONVERT_TARGETS = new Set(["pdf", "docx", "md", "markdown"]);

function basename(p: string): string {
  const s = String(p || "").replace(/[\\/]+$/, "");
  return s.split(/[\\/]/).pop() || s || "download";
}

/**
 * 取回并落盘：带 Authorization 头 fetch 成 blob，再用 <a download> 命名保存。
 * （window.open 带不上鉴权头，也无法自定义文件名，故统一走 blob。）
 * 取回失败（如代理异常）退回新标签直链，让用户至少能拿到文件。
 */
async function saveFile(url: string, filename: string): Promise<void> {
  try {
    const res = await fetch(url, { headers: authHeaders() });
    if (!res.ok) {
      window.open(url, "_blank", "noopener,noreferrer");
      return;
    }
    const blob = await res.blob();
    const objUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = objUrl;
    a.download = filename || "download";
    a.rel = "noopener";
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.setTimeout(() => URL.revokeObjectURL(objUrl), 4000);
  } catch {
    window.open(url, "_blank", "noopener,noreferrer");
  }
}

function authHeaders(): Record<string, string> {
  const token = getApiToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}
