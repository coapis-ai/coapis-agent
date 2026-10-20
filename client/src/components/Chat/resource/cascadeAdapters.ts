import { api } from "@/api";
import type { CascadeNode } from "@/components/CascadeMenu/CascadeMenu";
import { mediaTypeFromFilename } from "../mediaType";

/**
 * 级联菜单的数据适配器 —— 领域知识只写在这里。
 *
 * CascadeMenu 不认识「文件」「知识库」，它只调用 `load(node)`。本文件把
 * 三个真实数据源映射成 CascadeNode，并维护缓存：
 *
 * - 本会话文件：GET /myfiles/resources?chat_id=<uuid>（资源契约，refs 表反查）
 * - 我的空间：  GET /myfiles/list?path=<dir>&category=files
 * - 关联知识：  GET /knowledge/bases → GET /knowledge/bases/{kb_id}/documents
 *
 * 契约要点（2026-10-17 逐条对过后端真实路由核过，别再凭想象写字段名）：
 * - 列表统一返回 `{ total, items }`，**没有** `root` / `resources` / `results` /
 *   `bases` / `documents` 这些键；旧代码按 `data.bases` 取数取到 undefined，
 *   「+」菜单的「关联知识」子菜单因此恒为空。
 * - 主键不叫 `id`：知识库是 `kb_id`、文档是 `document_id`（标题是 `title`）、
 *   会话产物是 `path`。按 `b.id` 取会得到 undefined，节点 key 全部塌成
 *   `kb:undefined` 互相顶掉，payload 也带不出真实 id。
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

async function loadMySpaceDir(dir: string, force = false): Promise<CascadeNode[]> {
  const ck = `files:${dir}`;
  // force：展开动作触发的刷新，跳过缓存真读后端
  if (!force) {
    const cached = cache.get(ck);
    if (cached) return cached;
  }
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
          payload: { path: it.path, type: mediaTypeFromFilename(it.name), size: it.size },
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
    payload: {
      path: p,
      type: mediaTypeFromFilename(String(r.title ?? basename(p))),
      size: Number(r.size_bytes ?? 0),
    },
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

async function loadSession(
  chatId?: string,
  force = false,
): Promise<CascadeNode[]> {
  if (!chatId) return [];
  const ck = `session:${chatId}`;
  if (!force) {
    const cached = cache.get(ck);
    if (cached) return cached;
  }
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

async function loadKnowledgeBases(force = false): Promise<CascadeNode[]> {
  const ck = "kb";
  if (!force) {
    const cached = cache.get(ck);
    if (cached) return cached;
  }
  let bases: Array<Record<string, unknown>> = [];
  try {
    const data = (await api.get("/knowledge/bases")) as {
      items?: Array<Record<string, unknown>>;
      bases?: Array<Record<string, unknown>>;
    };
    // 后端 `GET /knowledge/bases` 返回的是 `{ total, items }`，从来没有 `bases`
    // 这个键 —— 旧代码只读 `data.bases`，取到 undefined → 恒为 [] → 「+」菜单
    // 的「关联知识」子菜单永远显示「这里还没有内容」。
    bases = data.items ?? data.bases ?? [];
  } catch (err) {
    // API 调用失败时返回空数组，但记录错误以便调试
    console.warn("加载知识库列表失败:", err);
    bases = [];
  }

  // 后端主键叫 `kb_id` 不叫 `id`（知识库管理页 2026-10 已按同一约定映射过）。
  // 直接读 `b.id` 会得到 undefined：所有节点 key 塌成 `kb:undefined` 互相顶掉，
  // payload.id 也是 undefined，勾选后 Chat 页拿不到真实知识库 id。
  const nodes: CascadeNode[] = bases
    .filter((b) => String(b.kb_id ?? b.id ?? "") !== "")
    .map((b) => {
      const id = String(b.kb_id ?? b.id);
      const name = String(b.name ?? id);
      return {
        key: `kb:${id}`,
        name,
        kind: "group",
        usage: "retrieval",
        meta: b.chunk_count ? String(b.chunk_count) : undefined,
        payload: { id, name },
      };
    });

  // 如果没有知识库，缓存一个空数组（避免重复请求）
  cache.set(ck, nodes);
  return nodes;
}

async function loadKnowledgeDocs(
  kbId: string,
  force = false,
): Promise<CascadeNode[]> {
  const ck = `kb:${kbId}:docs`;
  if (!force) {
    const cached = cache.get(ck);
    if (cached) return cached;
  }
  let docs: Array<Record<string, unknown>> = [];
  try {
    const data = (await api.get(
      `/knowledge/bases/${encodeURIComponent(kbId)}/documents`,
    )) as { documents?: Array<Record<string, unknown>>; items?: Array<Record<string, unknown>> };
    docs = data.documents ?? data.items ?? [];
  } catch {
    docs = [];
  }
  const nodes: CascadeNode[] = docs
    .filter((d) => String(d.document_id ?? d.doc_id ?? d.id ?? "") !== "")
    .map((d) => {
      // 后端文档主键是 `document_id`、标题是 `title`（不是 `id` / `name`）。
      // 旧代码读 `d.id ?? d.name` 全部取不到 → key 塌成 `kbdoc:undefined`、
      // 行名直接渲染成 "undefined"。
      const id = String(d.document_id ?? d.doc_id ?? d.id);
      const name = String(d.title ?? d.name ?? d.filename ?? id);
      return {
        key: `kbdoc:${id}`,
        name,
        kind: "item",
        // 文档级引用后端尚无消费者（消费契约是知识库列表），先只展示不可勾选
        selectable: false,
        meta: d.chunk_count ? String(d.chunk_count) : undefined,
      };
    });
  cache.set(ck, nodes);
  return nodes;
}

/**
 * 跨目录检索：走后端 `GET /myfiles/search` —— 与「我的空间」搜索框**同一个
 * 端点、同一份服务层实现**（递归子树、匹配完整相对路径、排除噪音目录、
 * 目录在前按名排序）。
 *
 * 之前是「分页拉资源清单 500 条 → 前端 substring 过滤」：同一功能第二套轮子，
 * 语义还和搜索框分叉（只匹配文件名、抓取窗口外的文件永远搜不到）。
 * 检索结果里的目录直接是 group 节点，hover 上去由 `loadMySpaceDir` 接住展开。
 */
async function loadSearch(kw: string, force = false): Promise<CascadeNode[]> {
  const ck = `search:${kw}`;
  if (!force) {
    const cached = cache.get(ck);
    if (cached) return cached;
  }
  const data = (await api.get(
    `/myfiles/search?keyword=${encodeURIComponent(kw)}`
    + `&path=${encodeURIComponent("/")}&category=files`,
  )) as ListItems;
  const nodes: CascadeNode[] = [];
  const seen = new Set<string>();
  for (const it of data.items ?? []) {
    const p = it.path;
    if (!p || seen.has(p)) continue; // 去重兜底：同路径重复行会渲染成重复行
    seen.add(p);
    const dir = p.slice(0, p.lastIndexOf("/") >= 0 ? p.lastIndexOf("/") : p.length);
    nodes.push(
      it.type === "directory"
        ? {
            key: p,
            name: it.name,
            kind: "group",
            usage: "working-path",
            meta: dir,
            payload: { path: p, type: "folder" },
          }
        : {
            key: p,
            name: it.name,
            kind: "item",
            usage: "reference",
            meta: dir,
            payload: { path: p, type: mediaTypeFromFilename(it.name), size: it.size },
          },
    );
  }
  // total 是后端命中总数（不受单页上限影响）→ 尾巴行「还有 N 项」是准的
  appendMore(nodes, ck, data.total ?? nodes.length, nodes.length);
  cache.set(ck, nodes);
  return nodes;
}

/** 单一分发入口：组件只需把节点交给它（force=true 时跳过缓存真读） */
export async function cascadeLoad(
  node: CascadeNode,
  chatId?: string,
  force = false,
): Promise<CascadeNode[]> {
  const key = node.key;
  if (key === "session") return loadSession(chatId, force);
  if (key.startsWith("files:")) return loadMySpaceDir(key.slice(6), force);
  // 我的空间里的子目录：节点 key 就是后端全路径（与勾选集合/selectedFiles 同源），
  // 必须在这里接住，否则 hover 进目录永远返回空列。
  if (key.startsWith("/")) return loadMySpaceDir(key, force);
  if (key === "kb") return loadKnowledgeBases(force);
  if (key.startsWith("kb:")) return loadKnowledgeDocs(key.slice(3), force);
  if (key.startsWith("search:")) return loadSearch(key.slice(7), force);
  return [];
}

export const SESSION_ROOT_KEY = "session";
export const SPACE_ROOT_KEY = "files:/";
export const KB_ROOT_KEY = "kb";
