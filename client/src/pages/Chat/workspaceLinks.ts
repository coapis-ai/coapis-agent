// ---------------------------------------------------------------------------
// 会话正文里的文件路径 → 可点链接（B5 · 产出直链兜底）
// ---------------------------------------------------------------------------
//
// 提示词已经要求模型「用 write_file 返回的相对路径引用产出文件」，但模型不
// 保证照做：它可能写服务器绝对路径，也可能把路径写成裸文本。裸文本里的路径
// 用户点不动，绝对路径点开了必 401/404。这里在渲染前把正文里的路径收成
// markdown 链接，链接的点击由 Chat 页的事件拦截器接管（预览抽屉 / 带 token 下载）。
//
// 三条硬约束：
//  * 代码块与行内代码里的路径是**示例**，绝不改动；
//  * 已有的 markdown 链接、图片、http(s) URL 不重复包装；
//  * 只认工作区形态（`files/…`、`media/…`、含 `/workspaces/<user>/` 的绝对路径），
//    其他文本一律不碰 —— 兜底不该把正文改成样。
//
// 纯函数模块：不依赖 React、不依赖 api 层，方便单测与复用。

/** 预览抽屉能渲染的类型（与 CoApisPreviewDrawer 共用同一份判定）。 */
export const PREVIEWABLE_SUFFIXES = new Set([
  ".md", ".markdown", ".txt", ".text", ".log", ".json", ".jsonl", ".yaml",
  ".yml", ".toml", ".ini", ".cfg", ".conf", ".csv", ".tsv", ".py", ".js",
  ".ts", ".tsx", ".jsx", ".css", ".sql", ".sh", ".bash", ".xml", ".rst",
  ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".pdf",
]);

export function pathSuffix(p: string): string {
  const m = /\.([A-Za-z0-9]{1,8})$/.exec(p || "");
  return m ? `.${m[1].toLowerCase()}` : "";
}

export function isPreviewablePath(p: string): boolean {
  return PREVIEWABLE_SUFFIXES.has(pathSuffix(p));
}

/**
 * 工作区相对路径（`files/x.md`）→ 我的空间端点参数。
 *
 * ⚠️ 两条路径体系不是一套：`/api/myfiles/*` 的 `path` 是**分类目录内**的相对
 * 路径（`x.md`、`sub/x.md`），而 write_file / 台账给的是**工作区**相对路径
 * （`files/x.md`）。直接把后者喂给 myfiles 会解析成
 * `<user>/files/files/x.md` —— 必 404（实测）。这里统一换算，category 跟着
 * 首段走（files/ → files，media/ → media）。
 */
export function toMyfilesParams(
  rel: string,
): { category: string; path: string } {
  const s = String(rel || "").replace(/^\/+/, "");
  if (s.startsWith("files/")) return { category: "files", path: s.slice(6) };
  if (s.startsWith("media/")) return { category: "media", path: s.slice(6) };
  return { category: "files", path: s };
}

/**
 * 正文/链接里的路径形态 → 工作区相对路径（`files/x.md`）。
 *
 * 认这些形态：`file://`、`/api/files/preview/<p>`、`/myfiles/download?path=<p>`、
 * 服务器绝对路径（取 `/workspaces/<user>/` 之后的部分）、带前导斜杠的相对路径。
 * 拿不准的一律返回 ""，调用方不接管（保持浏览器默认行为）。
 */
export function toWorkspaceRel(raw: string): string {
  if (!raw) return "";
  let s = String(raw).trim();
  if (s.includes("%")) {
    try {
      s = decodeURIComponent(s);
    } catch {
      /* 解不开就保持原样 */
    }
  }
  s = s.replace(/^file:\/\//i, "");
  s = s.replace(/^\/?api\/files\/preview\//i, "");
  s = s.replace(/^\/?files\/preview\//i, "");
  s = s.replace(/^\/?api\/myfiles\/download\?path=/i, "");
  s = s.replace(/^\/?myfiles\/download\?path=/i, "");
  s = s.replace(/[?#].*$/, "");
  s = s.replace(/^\/+/, "");
  const ws = /(?:^|\/)workspaces\/[^/]+\/(.+)$/.exec(s);
  if (ws) s = ws[1];
  s = s.replace(/^\/+/, "");
  s = s.replace(/[)）\]】，。；、,;:：'"“”`]+$/, "");
  if (!s) return "";
  // 只接管工作区形态：其他相对路径一律不猜，避免把正文里的普通词当文件
  if (!/^(files|media)\//.test(s)) return "";
  return s;
}

function mergeProtected(text: string): Array<[number, number]> {
  const ranges: Array<[number, number]> = [];
  const patterns: RegExp[] = [
    /```[\s\S]{0,20000}?```/g,
    /~~~[\s\S]{0,20000}?~~~/g,
    /`[^`\n]{1,600}`/g,
    /!\[[^\]\n]{0,300}\]\([^)\n]{0,600}\)/g,
    /\[[^\]\n]{0,300}\]\([^)\n]{0,600}\)/g,
    /https?:\/\/[^\s)\]】]+/g,
  ];
  for (const re of patterns) {
    let m: RegExpExecArray | null;
    while ((m = re.exec(text)) !== null) {
      if (m[0].length > 0) ranges.push([m.index, m.index + m[0].length]);
      if (m.index === re.lastIndex) re.lastIndex += 1;
    }
  }
  ranges.sort((a, b) => a[0] - b[0]);
  const merged: Array<[number, number]> = [];
  for (const r of ranges) {
    const last = merged[merged.length - 1];
    if (last && r[0] <= last[1]) last[1] = Math.max(last[1], r[1]);
    else merged.push([r[0], r[1]]);
  }
  return merged;
}

// 绝对形态：任意深度目录 + /workspaces/<user>/ + files|media/…
const WS_ABS_RE =
  /(?:\/[A-Za-z0-9._-]+)+\/workspaces\/[^/\s]+\/(?:files|media)\/[^\s`'")\]】，。；、]+/g;
// 相对形态：files/… 或 media/…，必须带扩展名（避免把 `files/` 目录名当文件）
const WS_REL_RE = /(?:files|media)\/[^\s`'")\]】，。；、]+\.[A-Za-z0-9]{1,8}/g;

/** 路径尾部可能粘的标点（中文句号、markdown 括号），从链接文本里剥掉。 */
function stripTail(rel: string): string {
  return rel.replace(/[)）\]】，。；、,;:：'"“”`]+$/, "");
}

function linkifySegment(seg: string, offset: number, full: string): string {
  const wrap = (matched: string, at: number): string => {
    // 前一个字符属于路径/链接的一部分 → 这不是独立的路径提及
    const before = at > 0 ? full[offset + at - 1] : "";
    if (/[A-Za-z0-9._\-/[\]]/.test(before)) return matched;
    const rel = stripTail(toWorkspaceRel(matched));
    if (!rel) return matched;
    const name = rel.split("/").pop() || rel;
    return `[${name}](${rel})`;
  };
  let out = seg;
  out = out.replace(WS_ABS_RE, (m: string, at: number) => wrap(m, at));
  out = out.replace(WS_REL_RE, (m: string, at: number) => wrap(m, at));
  return out;
}

/**
 * 正文兜底：把裸的工作区路径写成 markdown 链接。
 *
 * 幂等：链接化后整段被「已有链接」规则保护，重复调用不会套娃。
 */
export function linkifyWorkspacePaths(text: string): string {
  if (!text || typeof text !== "string") return text;
  if (text.length > 300000) return text; // 超长正文不值得冒渲染风险
  if (!/workspaces\/|files\/|media\//.test(text)) return text;
  const protectedRanges = mergeProtected(text);
  const parts: string[] = [];
  let cursor = 0;
  for (const [lo, hi] of protectedRanges) {
    if (lo > cursor) parts.push(linkifySegment(text.slice(cursor, lo), cursor, text));
    parts.push(text.slice(lo, hi));
    cursor = hi;
  }
  if (cursor < text.length) {
    parts.push(linkifySegment(text.slice(cursor), cursor, text));
  }
  return parts.join("");
}

/**
 * 会话消息数组（completed 事件的 output）正文链接化。
 *
 * 只换 text 内容块，不动消息结构；任何异常都原样返回 —— 兜底坏了不能
 * 把消息链路带崩。
 */
export function linkifyMessageOutput(output: any): any {
  if (!Array.isArray(output)) return output;
  try {
    return output.map((msg: any) => {
      const content = msg?.content;
      if (!Array.isArray(content)) return msg;
      let touched = false;
      const nextContent = content.map((c: any) => {
        if (c?.type === "text" && typeof c.text === "string" && c.text) {
          const linked = linkifyWorkspacePaths(c.text);
          if (linked !== c.text) {
            touched = true;
            return { ...c, text: linked };
          }
        }
        return c;
      });
      return touched ? { ...msg, content: nextContent } : msg;
    });
  } catch {
    return output;
  }
}
