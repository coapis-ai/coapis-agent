import { request } from "../request";

// ── 台账管理面 API（v20 · W2/W3/W6）───────────────────────────
//
// 这一层是「台账从机器账本变成用户能用的东西」的前端入口：清单五维筛选、
// 汇总统计、治理动作（定稿/转草稿/归档/软删）、巡检、散文件归位。
// 后端契约住在 `app/routers/files.py`（挂在 /api/myfiles/resources*），
// 全部动作**永不删除文件系统文件**——软删只标台账 + 进 .trash 由 file_service 负责。

/** 台账一行（与 `Resource.to_dict()` + ref_count 对齐）。 */
export interface LedgerResource {
  resource_key: string;
  kind: string;
  category?: string | null;
  title?: string;
  path?: string;
  source?: string;
  status: string;
  version?: number;
  size?: number | null;
  /** epoch 毫秒（一把尺子：与聊天资源端点、前端 fmtMs 同口径） */
  first_seen_at?: number | null;
  updated_at?: number | null;
  last_seen_at?: number | null;
  ref_count?: number;
  [k: string]: unknown;
}

export interface LedgerListParams {
  kind?: string;
  status?: string;
  category?: string;
  source?: string;
  q?: string;
  limit?: number;
  offset?: number;
}

export interface LedgerListResponse {
  items: LedgerResource[];
  total: number;
  limit: number;
  offset: number;
}

export interface LedgerStats {
  by_status?: Record<string, number>;
  by_kind?: Record<string, number>;
  by_category?: Record<string, number>;
  total?: number;
  orphans?: number;
  fs_missing?: number;
  [k: string]: unknown;
}

export interface SweepReport {
  fs_missing?: number;
  fs_missing_list?: unknown[];
  orphans?: number;
  orphan_list?: unknown[];
  unledgered?: number;
  unledgered_list?: Array<{ owner_id?: string; path?: string; size?: number }>;
  unowned?: number;
  unowned_list?: unknown[];
  backfilled?: number;
  scanned?: number;
  [k: string]: unknown;
}

export interface InboxResult {
  ok: boolean;
  inbox?: string;
  moved?: Array<{ path?: string; to?: string }>;
  moved_count?: number;
  skipped?: Array<{ path?: string; reason?: string }>;
  failed?: Array<{ path?: string; reason?: string }>;
  reledgered?: number;
  refs_moved?: number;
  reason?: string;
}

/** 治理动作（后端只认这五个，其余 400）。 */
export type LedgerAction = "publish" | "to_draft" | "archive" | "delete" | "move";

function qs(params: LedgerListParams): string {
  const p = new URLSearchParams();
  if (params.kind) p.set("kind", params.kind);
  if (params.status) p.set("status", params.status);
  if (params.category) p.set("category", params.category);
  if (params.source) p.set("source", params.source);
  if (params.q) p.set("q", params.q);
  p.set("limit", String(params.limit ?? 50));
  p.set("offset", String(params.offset ?? 0));
  return p.toString();
}

export const resourceLedgerApi = {
  /** 台账清单（五维筛选 + 关键词）。软删行不出现。 */
  listResources: (params: LedgerListParams = {}) =>
    request<LedgerListResponse>(`/myfiles/resources?${qs(params)}`),

  /** 汇总：状态/类型/类别分布 + 孤儿数 + 磁盘缺失数。 */
  stats: () => request<LedgerStats>("/myfiles/resources/stats"),

  /** 类别注册表（v20 · W1 唯一真相源，前端不再自建第二张表）。 */
  categories: () =>
    request<{ categories: string[]; valid: string[] }>("/myfiles/resources/categories"),

  /** 治理动作：定稿/转草稿/归档/软删/搬家。失败后端回 400 + 中文原因。 */
  govern: (resourceKey: string, action: LedgerAction) =>
    request<{ ok: boolean; status?: string; reason?: string }>(
      `/myfiles/resources/${encodeURIComponent(resourceKey)}`,
      { method: "PATCH", body: JSON.stringify({ action }) },
    ),

  /** 巡检（管理员）：只报告，永不搬、永不删。 */
  sweep: (opts: { full?: boolean; backfill?: boolean } = {}) =>
    request<SweepReport>(
      `/myfiles/resources/sweep?full=${opts.full ?? true}&backfill=${opts.backfill ?? false}`,
      { method: "POST" },
    ),

  /** 散文件归位（拍板 D4：files/_inbox/）。管理员可代他人（owner_id）。 */
  toInbox: (paths: string[], ownerId?: string) =>
    request<InboxResult>("/myfiles/resources/inbox", {
      method: "POST",
      body: JSON.stringify({ paths, owner_id: ownerId ?? null }),
    }),
};

export default resourceLedgerApi;
