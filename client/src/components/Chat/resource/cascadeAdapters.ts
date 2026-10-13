import { api } from "@/api";
import type { CascadeNode } from "@/components/CascadeMenu/CascadeMenu";

/**
 * 级联菜单的数据适配器 —— 领域知识只写在这里。
 *
 * CascadeMenu 不认识「文件」「知识库」，它只调用 `load(node)`。本文件把
 * 三个真实数据源映射成 CascadeNode，并维护缓存：
 *
 * - 本会话文件：GET /myfiles/resources?chat_id=<uuid>（资源契约，refs 表反查）
 * - 我的空间：  GET /myfiles/list?path=<dir>&category=files
 * - 关联知识：  GET /knowledge/bases → GET /knowledge/bases/{id}/documents
 *
 * key 命名空间（组件不解析，仅作为唯一键与缓存键）：
 *   "session" / "files:<dir>" / "kb" / "kb:<id>" / "kbdoc:<id>"
 * 文件节点 key 直接用后端返回的全路径（`/docs/a.pdf`），与 selectedFiles.path
 * 同源，勾选态可直接由 selectedFiles 反推。
 */

const cache = new Map<string, CascadeNode[]>();

/** 上传/生成新文件后失效（目录缓存过期） */
export function invalidateCascade(dirPath?: string): void {
  if (dirPath) cache.delete(`files:${dirPath}`);
  else cache.clear();
}

function sizeLabel(n: number): string {
  if (!n) return "";
  if (n < 1024) return `${n}B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)}K`;
  return `${(n / 1024 / 1024).toFixed(1)}M`;
}

function basename(p: string): string {
  const i = p.lastIndexOf("/");
  return i >= 0 ? p.slice(i + 1) : p;
}

interface ListItems {
  items?: Array<{
    name: string;
    type: string;
    path: string;
    size?: number;
    items_count?: number;
  }>;
  /** 后端分页前的总条数（page_size=200 截断时 > items.length） */
  total?: number;
}

async function loadMySpaceDir(dir: string): Promise<CascadeNode[]> {
  const ck = `files:${dir}`;
  const cached = cache.get(ck);
  if (cached) return cached;
  const data = (await api.get(
    `/myfiles/list?path=${encodeURIComponent(dir)}&category=files&page_size=200`,
  )) as ListItems;
  const nodes: CascadeNode[] = (data.items ?? []).map((it) =>
    it.type === "directory"
      ? {
          key: it.path,
          name: it.name,
          kind: "group",
          usage: "working-path",
          meta: it.items_count ? String(it.items_count) : undefined,
          payload: { path: it.path, type: "folder" },
        }
      : {
          key: it.path,
          name: it.name,
          kind: "item",
          usage: "reference",
          meta: sizeLabel(it.size ?? 0),
          payload: { path: it.path, type: "file", size: it.size },
        },
  );
  // 后端 page_size=200 会截断，total 是截断前的总数。把差额作为「more」计数节点
  // 交给 CascadeMenu 渲染尾巴行（「…还有 N 项未显示」），否则用户看不到被截断。
  const total = data.total ?? nodes.length;
  if (total > nodes.length) {
    nodes.push({
      key: `${ck}:more`,
      name: "",
      kind: "more",
      count: total - nodes.length,
    });
  }
  cache.set(ck, nodes);
  return nodes;
}

/**
 * 资源清单分页拉取：走资源契约 `GET /myfiles/resources`（每资源一行、已去重、
 * 带 status 与引用者计数），不再读 `file_records` 事件流。
 *
 * 后端 limit 上限 200，用 offset 翻页（每页 100，最多 5 页）。`total` 是分页前
 * 总数，供调用方折算「还有 N 项未加载」的尾巴行 —— 没有 total 被截断的记录会
 * 静默消失。
 */
async function fetchResources(
  chatId?: string,
  maxPages = 5,
): Promise<{ rows: Array<Record<string, unknown>>; total: number }> {
  const PAGE = 100;
  const rows: Array<Record<string, unknown>> = [];
  let total = 0;
  for (let p = 0; p < maxPages; p++) {
    const tail = chatId ? `&chat_id=${encodeURIComponent(chatId)}` : "";
    const resp = (await api.get(
      `/myfiles/resources?limit=${PAGE}&offset=${p * PAGE}${tail}`,
    )) as { items?: Array<Record<string, unknown>>; total?: number };
    const items = resp?.items ?? [];
    rows.push(...items);
    total = resp?.total ?? rows.length;
    if (items.length < PAGE || rows.length >= total) break;
  }
  return { rows, total };
}

const STATUS_LABEL: Record<string, string> = {
  draft: "草稿",
  official: "正式",
  orphan: "孤儿",
  archived: "归档",
};

/** 资源行 → 级联节点。key 用后端全路径，与 selectedFiles.path 同源。 */
function resourceNode(r: Record<string, unknown>): CascadeNode {
  const p = String(r.path ?? "");
  const refs = Number(r.ref_count ?? 0);
  const parts = [
    STATUS_LABEL[String(r.status ?? "")] ?? String(r.status ?? ""),
    refs > 1 ? `引用${refs}处` : refs === 1 ? "本会话引用" : "未引用",
    sizeLabel(Number(r.size_bytes ?? 0)),
  ].filter(Boolean);
  return {
    key: p,
    name: String(r.title ?? basename(p)),
    kind: "item",
    usage: "reference",
    meta: parts.join(" · "),
    payload: { path: p, type: "file", size: Number(r.size_bytes ?? 0) },
  };
}

/** 把后端截断的差额折算成 CascadeMenu 的 more 计数节点（渲染成尾巴行） */
function appendMore(
  nodes: CascadeNode[],
  key: string,
  total: number,
  fetched: number,
): void {
  if (total > fetched) {
    nodes.push({
      key: `${key}:more`,
      name: "",
      kind: "more",
      count: total - fetched,
    });
  }
}

async function loadSession(chatId?: string): Promise<CascadeNode[]> {
  if (!chatId) return [];
  const ck = `session:${chatId}`;
  const cached = cache.get(ck);
  if (cached) return cached;
  // 会话文件 = 资源契约里被本 chat 引用过的那一行（refs 表反查，非冗余列）。
  const { rows, total } = await fetchResources(chatId);
  const seen = new Set<string>();
  const nodes: CascadeNode[] = [];
  for (const r of rows) {
    const p = String(r.path ?? "");
    if (!p || seen.has(p)) continue;
    seen.add(p);
    nodes.push(resourceNode(r));
  }
  appendMore(nodes, ck, total, rows.length);
  cache.set(ck, nodes);
  return nodes;
}

async function loadKnowledgeBases(): Promise<CascadeNode[]> {
  const ck = "kb";
  const cached = cache.get(ck);
  if (cached) return cached;
  let bases: Array<Record<string, unknown>> = [];
  try {
    const data = (await api.get("/knowledge/bases")) as {
      bases?: Array<Record<string, unknown>>;
    };
    bases = data.bases ?? [];
  } catch {
    bases = [];
  }
  const nodes: CascadeNode[] = bases.map((b) => ({
    key: `kb:${String(b.id)}`,
    name: String(b.name ?? b.id),
    kind: "group",
    usage: "retrieval",
    meta: b.chunk_count ? String(b.chunk_count) : undefined,
    payload: { id: String(b.id), name: String(b.name ?? b.id) },
  }));
  cache.set(ck, nodes);
  return nodes;
}

async function loadKnowledgeDocs(kbId: string): Promise<CascadeNode[]> {
  const ck = `kb:${kbId}:docs`;
  const cached = cache.get(ck);
  if (cached) return cached;
  let docs: Array<Record<string, unknown>> = [];
  try {
    const data = (await api.get(
      `/knowledge/bases/${encodeURIComponent(kbId)}/documents`,
    )) as { documents?: Array<Record<string, unknown>>; items?: Array<Record<string, unknown>> };
    docs = data.documents ?? data.items ?? [];
  } catch {
    docs = [];
  }
  const nodes: CascadeNode[] = docs.map((d) => ({
    key: `kbdoc:${String(d.id ?? d.name)}`,
    name: String(d.name ?? d.filename ?? d.id),
    kind: "item",
    // 文档级引用后端尚无消费者（消费契约是知识库列表），先只展示不可勾选
    selectable: false,
  }));
  cache.set(ck, nodes);
  return nodes;
}

/**
 * 跨目录检索：走资源契约（/myfiles/resources，每资源一行）。
 * 后端无服务端 search 参数，所以分页拉清单（最多 5 页 = 500 条）后本地过滤；
 * 超出抓取窗口的记录以 more 计数节点呈现为尾巴行，不静默吞掉。
 * 检索场景下 meta 优先展示所在目录（跨目录找文件时目录比状态更有用）。
 */
async function loadSearch(kw: string): Promise<CascadeNode[]> {
  const ck = `search:${kw}`;
  const cached = cache.get(ck);
  if (cached) return cached;
  const { rows, total } = await fetchResources();
  const lower = kw.toLowerCase();
  const seen = new Set<string>();
  const nodes: CascadeNode[] = [];
  for (const r of rows) {
    const p = String(r.path ?? "");
    if (!p || seen.has(p)) continue;
    if (!p.toLowerCase().includes(lower)) continue;
    seen.add(p);
    nodes.push({
      key: p,
      name: String(r.title ?? basename(p)),
      kind: "item",
      usage: "reference",
      meta: p.slice(0, p.lastIndexOf("/") >= 0 ? p.lastIndexOf("/") : p.length),
      payload: { path: p, type: "file", size: Number(r.size_bytes ?? 0) },
    });
  }
  appendMore(nodes, ck, total, rows.length);
  cache.set(ck, nodes);
  return nodes;
}

/** 单一分发入口：组件只需把节点交给它 */
export async function cascadeLoad(
  node: CascadeNode,
  chatId?: string,
): Promise<CascadeNode[]> {
  const key = node.key;
  if (key === "session") return loadSession(chatId);
  if (key.startsWith("files:")) return loadMySpaceDir(key.slice(6));
  // 我的空间里的子目录：节点 key 就是后端全路径（与勾选集合/selectedFiles 同源），
  // 必须在这里接住，否则 hover 进目录永远返回空列。
  if (key.startsWith("/")) return loadMySpaceDir(key);
  if (key === "kb") return loadKnowledgeBases();
  if (key.startsWith("kb:")) return loadKnowledgeDocs(key.slice(3));
  if (key.startsWith("search:")) return loadSearch(key.slice(7));
  return [];
}

export const SESSION_ROOT_KEY = "session";
export const SPACE_ROOT_KEY = "files:/";
export const KB_ROOT_KEY = "kb";
