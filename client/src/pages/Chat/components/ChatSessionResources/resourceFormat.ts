/**
 * 会话资源的时间/大小/名称口径（v17 · F5 + F6 + F8 共用）。
 *
 * 为什么要有这个文件：同一个接口 `GET /chats/{id}/resources` 历史上吃**两把
 * 尺子**——台账命中时给 epoch **秒**（`Resource.to_dict()` 直接倒列，
 * updated_at 是 float 秒），台账回退扫描时给 epoch **毫秒**
 * （file_service `_to_output`: `st.st_mtime * 1000`）。前端写死按秒乘 1000
 * （ChatSessionResources/index.tsx:81），于是同一张列表里两行的时间尺度能差
 * 一千倍；左栏资源行压根不显示时间，L3 表显示的时间也常年和落盘时间对不上
 * （小蜜蜂 2026-11-05 第 6 条）。
 *
 * 口径定死在**这四处**（后端写、前端读都只此一处）：
 *   1. 台账行出参 → 毫秒（resource_ledger._chat_resource_rows）
 *   2. 扫描回退出参 → 毫秒（file_service 路径，本来就是毫秒）
 *   3. 前端读取 → `toEpochMs` 认秒也认毫秒（兼容存量数据与老缓存）
 *   4. 前端显示 → `formatResTime` / `formatResSize` 全部走这里
 *
 * 存量数据（台账列 float 秒）一律**只改出参口径**，不动历史行。
 */

/** 2001-09-09 的**毫秒**时间戳：小于它的一定是秒制（毫秒制早已越过它）。 */
const MS_THRESHOLD = 1_000_000_000_000;

/**
 * 把后端给的时间统一成**毫秒**。
 *
 * 秒制 / 毫秒制 / ISO 字符串 / 空值都要吃得下：台账历史行是 float 秒、扫描
 * 路径是毫秒、老接口留过 ISO 串。这里不抛错、不返回 NaN —— 左栏一行时间
 * 显示成 `NaN` 比显示 `-` 更糟。
 */
export function toEpochMs(v?: number | string | null): number | null {
  if (v == null || v === "") return null;
  if (typeof v === "string") {
    const asNum = Number(v);
    if (Number.isFinite(asNum) && asNum > 0) {
      return asNum < MS_THRESHOLD ? Math.round(asNum * 1000) : Math.round(asNum);
    }
    const parsed = Date.parse(v);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }
  const n = Number(v);
  if (!Number.isFinite(n) || n <= 0) return null;
  return n < MS_THRESHOLD ? Math.round(n * 1000) : Math.round(n);
}

/** 资源时间 → 本地可读时间（左栏行内、L3 表头、预览抽屉共用同一格式）。 */
export function formatResTime(v?: number | string | null): string {
  const ms = toEpochMs(v);
  if (ms == null) return "-";
  const d = new Date(ms);
  if (Number.isNaN(d.getTime())) return "-";
  const pad = (x: number) => String(x).padStart(2, "0");
  const sameYear = d.getFullYear() === new Date().getFullYear();
  const head = sameYear
    ? `${d.getMonth() + 1}-${pad(d.getDate())}`
    : `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  return `${head} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** 资源字节数 → 可读大小（左栏行内与 L3 表同源，别各写一份 KB/MB 换算）。 */
export function formatResSize(bytes?: number | string | null): string {
  const b = Number.isFinite(Number(bytes)) ? Number(bytes) : 0;
  if (b <= 0) return "";
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  if (b < 1024 * 1024 * 1024) return `${(b / 1024 / 1024).toFixed(1)} MB`;
  return `${(b / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

/**
 * 文件名拆成「主干 + 扩展名」两段（v17 · F8）。
 *
 * 左栏资源行此前是整串 `ellipsis` **从右往左截** —— 面板窄时先被吃掉的就是
 * 尾部扩展名，用户看到的是"报表-三季度…"，分不清是 docx 还是 pdf（小蜜蜂
 * 2026-11-05 第 5 条）。拆两段后 CSS 只截主干、扩展名保尾（见
 * inline.module.less 的 `.rowStem`/`.rowExt`）。
 *
 * 点号只在首字符（隐藏文件 `.gitignore`）时没有扩展名，整串当主干。
 */
export function splitFileName(name: string): { stem: string; ext: string } {
  const s = String(name ?? "");
  const i = s.lastIndexOf(".");
  if (i <= 0 || i === s.length - 1) return { stem: s, ext: "" };
  return { stem: s.slice(0, i), ext: s.slice(i) };
}

/** 「3.2 KB · 11-4 18:30」——左栏资源行的第二行小字（F8）。 */
export function formatResMeta(
  bytes?: number | string | null,
  updated?: number | string | null,
): string {
  const size = formatResSize(bytes);
  const time = formatResTime(updated);
  return [size, time === "-" ? "" : time].filter(Boolean).join(" · ");
}
