/**
 * 资源「显示名 / 所在目录」的唯一口径（方案 F2）。
 *
 * 为什么要单独一层（2026-10-27 实测）：三处资源入口（左栏 Inline、聊天窗
 * 本轮资源条、L3 抽屉）各自写「取哪个字段当名字」，而台账的 `title` 是
 * 后端登记的**文件名**——`file_io.py` 历史上登记的是 `Path(p).stem`，
 * 扩展名被抹掉（`d3_verify2.txt` → `d3_verify2`），用户在一列名字里根本
 * 看不出那是个什么文件；抽屉里连目录都没有，路径只藏在 tooltip 里。
 *
 * 口径（唯一一份实现，三处共用）：
 *  - 文件类：**路径里的文件名（含扩展名）优先**，path 缺失才退回 title。
 *    理由：path 是台账主键、必然存在且必然真实；title 是登记时算出来的
 *    派生字段，历史数据不可信（stem 版），新数据也随时可能与 path 不一致。
 *  - 非文件类（web/kb/mcp/db）：title 优先——URL 的最后一段不是可读名字。
 *  - 目录：path 去掉文件名那一段；web 类给主机名。
 */
import type { ChatResourceItem } from "../../../../api/modules/chat";
import { toLedgerRelPath } from "../../../../utils/webPreview";

/** 归一路径并切段：去掉 query/hash、反斜杠当分隔符、丢掉空段。 */
function splitPath(raw: string): string[] {
  const clean = String(raw ?? "")
    .trim()
    .replace(/[?#].*$/, "")
    .replace(/\\/g, "/");
  return clean.split("/").filter(Boolean);
}

/** 路径最后一段（文件名 / 主机名）。带百分号转义的还原成可读字符。 */
export function baseNameOf(raw?: string | null): string {
  const seg = splitPath(String(raw ?? ""));
  if (!seg.length) return "";
  const last = seg[seg.length - 1];
  try {
    return decodeURIComponent(last);
  } catch {
    return last;
  }
}

/** 目录部分（不含文件名）。单层路径没有目录 → 空串。 */
export function dirNameOf(raw?: string | null): string {
  const seg = splitPath(String(raw ?? ""));
  return seg.length > 1 ? seg.slice(0, -1).join("/") : "";
}

/** 有扩展名就当它是文件路径（kind 词汇不统一：台账恒 file，消息 metadata 里更杂）。 */
function looksLikeFile(name: string): boolean {
  return /\.[A-Za-z0-9]{1,8}$/.test(name);
}

/** 显示名：文件名（含扩展名）优先，title 只作兜底。 */
export function displayName(item: ChatResourceItem): string {
  const rel = toLedgerRelPath(item.path);
  const base = baseNameOf(rel);
  if (item.kind === "file" && base) return base;
  if (base && looksLikeFile(base)) return base;
  return item.title || base || rel || "";
}

/** 所在目录：文件给相对目录，web 给主机名，取不到给空串。 */
export function dirName(item: ChatResourceItem): string {
  const rel = toLedgerRelPath(item.path);
  if (!rel) return "";
  if (item.kind === "web") {
    return rel.replace(/^[a-z]+:\/\//i, "").replace(/\/.*$/, "");
  }
  return dirNameOf(rel);
}

/**
 * 目录缩写（2026-10-27 抽屉列宽收口）：只留末尾两段，前面用 `…/` 代替。
 *
 * 抽屉 480px 时名称列只有 ~150px，而台账目录长这样
 * `files/2026-10/20261027_1023_条形图验收/` —— 整条路径 nowrap 撑进自动
 * 布局的表格，名称列被顶到 300px+，时间/大小/操作三列挤成竖排。
 * 目录的**尾部**才是区分度所在（日期_任务名），所以截前不截后；
 * 完整路径留在行 title 与「在我的空间定位」里，不丢信息。
 */
export function shortDir(item: ChatResourceItem): string {
  const dir = dirName(item);
  if (!dir) return "";
  const seg = dir.split("/").filter(Boolean);
  if (seg.length <= 2) return dir;
  return `…/${seg.slice(-2).join("/")}`;
}


/** 去扩展名的文件名：转换/下载时拼新扩展名用（`a.txt` + pdf → `a.pdf`）。 */
export function stemName(item: ChatResourceItem): string {
  const n = displayName(item);
  return n.replace(/\.[A-Za-z0-9]{1,8}$/, "") || n;
}
