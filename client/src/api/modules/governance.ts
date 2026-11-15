/**
 * 治理视图（B4 出口验收第 2 条 + B5 收尾）前端 API —— 三个已上线的只读对账端点。
 *
 * 为什么单独开一个模块：这三个端点分属三个后端路由（decisions / governance / memory），
 * 但在页面上回答的是同一个问题——闸门到底拦没拦、治理事件都发生了什么、上下文吃掉多少。
 * 端点是既有的，这一层只是把它们的真实形状写准，不发明新字段。
 *
 * 错误口径与 checkpoints.ts **不同**且刻意如此：checkpoints 把 404 翻译成 enabled=false，
 * 这里**原样抛出**。后端 404/503 的 detail 里写着「需要设哪个环境变量」，那句话必须
 * 原样到达用户眼前 —— API 层吞掉错误，治理页就只剩一句空白的"加载失败"。
 */
import { request } from "../request";

/** 统计窗口可选值。后端 days 越界直接 400（不静默截断），前端只给合法档位。 */
export const GOV_DAYS_OPTIONS = [1, 7, 30] as const;

// ═══════════════════════════════════════════════════════════
// 卡 A · 循环闸对账  GET /decisions/loop-gates
// ═══════════════════════════════════════════════════════════

/** 单个闸门的分桶。`rows` 是台账行数，`hits` = rows × ledger_every。 */
export interface LoopGateBucket {
  gate: string;
  /** 后端给的白话说明（GATE_LABELS），不是前端翻译出来的 */
  label: string;
  rows: number;
  hits: number;
  actions: Record<string, number>;
  last_at: string | null;
}

/** 最近触发行。`created_at` 是**归一化后的 ISO 字符串**（后端 _lg_iso 已转过），不是 epoch 秒。 */
export interface LoopGateRecentRow {
  event_id: string;
  created_at: string;
  gate: string;
  action: string;
  reason: string;
  chat_id: string;
  turn: number;
  user_id: string;
}

/**
 * `enabled` 后端给的是**阈值现状对象**（GateThresholds 全字段，每次请求现读 env），
 * 不是一个布尔 —— 所以这里按对象建模，布尔只作为历史兼容保留。
 * `round_budget=0` 的语义是"只计数不拦"，判"未启用"必须看全字段，不能拿单个字段下结论。
 */
export interface LoopGateThresholds {
  round_budget?: number;
  stop_phrase?: boolean;
  dedup?: number;
  empty_streak?: number;
  session_warn?: number;
  stagnation_similarity?: number;
  stagnation_force_exit?: number;
}

export interface LoopGatesResponse {
  days: number;
  /** 十门零值补齐：后端按 GATE_CODES 全量建桶，"从没触发"的门以 rows=0 出现在这里 */
  gates: LoopGateBucket[];
  total_rows: number;
  total_hits: number;
  active_gates: number;
  /** 闸码不在表里的行（解析不出前缀的算空串）—— 后端显式暴露，前端也必须显式列出 */
  unknown_gates: Record<string, number>;
  recent: LoopGateRecentRow[];
  ledger_every: number;
  counting_note?: string | null;
  enabled?: LoopGateThresholds | boolean | null;
  /** 库读取失败时后端返回这个字段（不抛 HTTP 错），页面上要能看见 */
  error?: string;
}

// ═══════════════════════════════════════════════════════════
// 卡 B · 治理事件  GET /governance/events
// ═══════════════════════════════════════════════════════════

/**
 * kind 词表与后端 `EVENT_KINDS` 逐字对齐（SSOT 在后端 governance/events.py）。
 * 后端对未知 kind 返回 400 —— 前端不许发明 kind，也不许把界面上的词直接拼进查询串。
 */
export const GOV_EVENT_KINDS = [
  "judge",
  "tool",
  "tool_denied",
  "approval",
  "memory",
  "file_version",
  "sandbox_denied",
  "config",
] as const;

export type GovEventKind = (typeof GOV_EVENT_KINDS)[number];

export interface GovernanceEventRow {
  kind: string;
  /** epoch 秒（float），来自审计链/台账的 timestamp，不是 ISO 字符串 */
  ts: number | null;
  username: string | null;
  source: string | null;
  action: string | null;
  session: string | null;
  target: string | null;
  result: string | null;
  reason: string | null;
  ref_id: string | null;
}

export interface GovernanceEventsResponse {
  events: GovernanceEventRow[];
  kinds?: string[];
  limit?: number;
  count?: number;
  note?: string | null;
  role?: string;
  scope?: string;
}

// ═══════════════════════════════════════════════════════════
// 卡 C · 上下文消耗对账  GET /memory/context-usage
// ═══════════════════════════════════════════════════════════

/**
 * 逐会话的实测行。
 *
 * 注意字段的**真假**：`window_tokens` / `peak_used_pct` / `avg_used_pct` / `over_budget`
 * 后端都允许 **null**（provider 未上报模型窗口 → 利用率不可计算，后端选择返回 null 而不是猜）。
 * 前端因此不许把 null 渲染成 0%。
 *
 * 利用率字段只有 `avg_used_pct`（均值口径，sum/calls 换算）与 `peak_used_pct`（峰值口径）。
 * 台账里没有"中位数"这一列 —— 页面上写「均值」，不写「中位」，别给数据安一个它没有的统计量。
 */
export interface ContextUsageSessionRow {
  session_id: string;
  calls: number;
  input_tokens_avg: number;
  input_tokens_max: number;
  window_tokens: number | null;
  peak_used_pct: number | null;
  avg_used_pct: number | null;
  /** 后端给的别名（治理口径 mean_used_pct），值与 avg_used_pct 相同 */
  mean_used_pct?: number | null;
  over_budget: boolean | null;
  models?: string[];
  window_source?: string;
  utilization_note?: string | null;
  input_tokens_per_call?: number[];
}

export interface ContextUsageTier {
  compact_enabled?: boolean;
  targets?: Record<string, number>;
}

export interface ContextUsageResponse {
  ok: boolean;
  scope: { user_id: string | null; days: number; limit: number };
  cutoff_epoch?: number;
  rows_scanned: number;
  usage: {
    sessions: ContextUsageSessionRow[];
    session_count?: number;
    measurable_sessions?: number;
    peak_used_pct_max?: number | null;
    peak_used_pct_avg?: number | null;
    window_tokens?: number | null;
    unknown_window_models?: string[];
    window_note?: string | null;
    utilization_unit?: string;
  };
  tier: ContextUsageTier;
  note?: string | null;
}

export const governanceApi = {
  /**
   * 循环闸按门分桶（B4b 端点）。
   * `recent_limit` 对应后端的 `recent_limit`（蛇形），别拼成 camelCase —— 参数名以端点为准。
   */
  loopGates: (days = 7, recentLimit = 20) => {
    const qs = new URLSearchParams({
      days: String(days),
      recent_limit: String(recentLimit),
    });
    return request<LoopGatesResponse>(`/decisions/loop-gates?${qs.toString()}`);
  },

  /**
   * 治理事件联合视图（B5-B 端点）。
   *
   * 两条硬规矩：
   * 1. `kind` 为空 = 全部，此时**整个参数不发**。后端是 `kind: list[str]`，
   *    传 `?kind=` 空串会进词表校验被判未知 —— 空值必须整条省掉。
   * 2. 未知 kind 在前端就拦下（后端会 400，但那句话不该靠网络往返才拿到）。
   */
  events: (kind = "", limit = 100) => {
    const k = String(kind || "").trim();
    if (k && !(GOV_EVENT_KINDS as readonly string[]).includes(k)) {
      // 不发给后端：未知词表是调用方错误，本地就能判定。
      // 文案用英文技术语 —— 这条字符串会以 detail 原文的形式出现在卡 B 的 Alert 里，
      // 与后端 detail 同一口径；界面文案一律走 i18n，API 层不产中文。
      throw new Error(`Unknown event kind: ${k}. Allowed: ${GOV_EVENT_KINDS.join(", ")}`);
    }
    const qs = new URLSearchParams({ limit: String(limit) });
    if (k) qs.set("kind", k);
    return request<GovernanceEventsResponse>(`/governance/events?${qs.toString()}`);
  },

  /** 上下文消耗实测（B4c 端点）。days 1~365、limit 1~2000，越界后端 400。 */
  contextUsage: (days = 7, limit = 500) => {
    const qs = new URLSearchParams({ days: String(days), limit: String(limit) });
    return request<ContextUsageResponse>(`/memory/context-usage?${qs.toString()}`);
  },
};
