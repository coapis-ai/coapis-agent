// 资源类别尺子（v20 · W1 · 前端侧）—— 与后端 resource_category.py 逐字对齐
//
// 唯一口径来源：server/coapis/foundation/resource_category.py
// 对账测试：tests/test_resource_category.py（Python 读这份 TS 的 EXT 表，
// 逐项比对，漂移即红——沿用 mediaType.ts / file_kind_registry 的防漂移惯例）。
//
// 为什么前端也要一份：图标要在渲染时同步决定，不能为拿类别多打一次请求；
// `GET /files/resources/categories` 端点返回的是**后端注册表快照**（管理页
// 筛选项、验收第 10 条），渲染侧用这份同表常量，两处必然同表。

export type ResourceCategory =
  | "doc"
  | "sheet"
  | "slide"
  | "pdf"
  | "image"
  | "media"
  | "archive"
  | "code"
  | "web"
  | "chat_record"
  | "db_record"
  | "kb_entry"
  | "mcp_tool"
  | "other";

export const CATEGORY_ORDER: ResourceCategory[] = [
  "doc",
  "sheet",
  "slide",
  "pdf",
  "image",
  "media",
  "archive",
  "code",
  "web",
  "chat_record",
  "db_record",
  "kb_entry",
  "mcp_tool",
  "other",
];

// ── 扩展名表：与后端逐项一致（对账测试钉死，改一边必须改另一边）──
export const EXT_TO_CATEGORY: Record<string, ResourceCategory> = (() => {
  const table: Record<string, ResourceCategory> = {};
  const put = (cat: ResourceCategory, exts: string) => {
    for (const e of exts.split(" ")) table[e] = cat;
  };
  put(
    "image",
    "png jpg jpeg gif webp svg bmp ico tiff tif avif heic jfif",
  );
  put("pdf", "pdf");
  put(
    "doc",
    "md markdown mdx txt log rtf odt doc docx epub typ quarto adoc asciidoc",
  );
  put("sheet", "xls xlsx xlsm csv tsv ods numbers parquet");
  put("slide", "ppt pptx odp key mmd mermaid drawio");
  put("media", "mp3 wav m4a flac ogg aac opus mp4 mov avi mkv webm m4v wmv");
  put("archive", "zip tar gz tgz bz2 xz 7z rar gz2 zst");
  put(
    "code",
    "py pyi ipynb js mjs cjs ts tsx jsx vue java go rs c cc cpp h hpp cs php " +
      "rb sh bash zsh ps1 bat sql yaml yml json toml ini env dockerfile tf pl lua r jl",
  );
  put("web", "html htm xhtml");
  return table;
})();

/** 路径的扩展名（小写无点；无扩展名返回 ""）。 */
export function extOf(path: string): string {
  const name = (path || "").replace(/\\/g, "/").split("/").pop() || "";
  const dot = name.lastIndexOf(".");
  if (dot <= 0 && !name.includes(".")) return "";
  if (dot < 0) return "";
  return name.slice(name.lastIndexOf(".") + 1).toLowerCase();
}

/** 聊天记录口径：导出目录 / 记录命名（与后端 is_chat_record_path 对齐）。 */
const CHAT_EXPORT_PREFIXES = ["exports/", "chat_exports/", "media/"];
const CHAT_NAME_HINTS = [
  "对话记录",
  "聊天记录",
  "chat-record",
  "chat_record",
  "conversation",
];

export function isChatRecordPath(path: string): boolean {
  const norm = (path || "")
    .replace(/\\/g, "/")
    .trim()
    .toLowerCase()
    .replace(/^\.?\//, "");
  if (CHAT_EXPORT_PREFIXES.some((p) => norm.startsWith(p))) {
    return CHAT_NAME_HINTS.some((h) => norm.includes(h));
  }
  return CHAT_NAME_HINTS.some((h) => norm.includes(h));
}

/** kind + 路径 → 类别。**前端唯一换算函数**（与后端 resolve_category 同规则）。 */
export function resolveCategory(
  kind: string,
  path: string,
): ResourceCategory {
  const k = (kind || "").trim().toLowerCase();
  const raw = (path || "").trim();
  if (k === "web") {
    return raw.startsWith("chat-export:") || isChatRecordPath(raw)
      ? "chat_record"
      : "web";
  }
  if (k === "db") return "db_record";
  if (k === "kb") return "kb_entry";
  if (k === "mcp") return "mcp_tool";
  if (k !== "file") return "other";
  if (isChatRecordPath(raw)) return "chat_record";
  const ext = extOf(raw);
  if (ext && EXT_TO_CATEGORY[ext]) return EXT_TO_CATEGORY[ext];
  const stem = (raw.replace(/\\/g, "/").split("/").pop() || "").toLowerCase();
  return EXT_TO_CATEGORY[stem] || "other";
}

/** 图标 key（渲染侧按此选 antd 图标；图标本体不进 TS 常量，避免样式耦合）。 */
export const CATEGORY_ICON: Record<ResourceCategory, string> = {
  doc: "file-text",
  sheet: "file-excel",
  slide: "file-ppt",
  pdf: "file-pdf",
  image: "file-image",
  media: "video-camera",
  archive: "box-plot",
  code: "code",
  web: "global",
  chat_record: "message",
  db_record: "database",
  kb_entry: "book",
  mcp_tool: "api",
  other: "file",
};
