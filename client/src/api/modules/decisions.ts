import { request } from "../request";

/** 判断中枢（v14 §5.2 / U 批）：台账可见 + 配置可改。 */

/**
 * 台账行的字段名**逐一对齐后端 SELECT 的真实列**（v24）：
 * `event_id, created_at, user_id, agent_id, chat_id, turn, source, complexity,
 *  action, judgment, reason, hit_layer, model, latency_ms, cost, tokens,
 *  outcome, rating, input_hash`。
 *
 * 此前这里写的是 `ts / tokens_in / tokens_out / model_id / provider_id /
 * fallback_reason / thinking / engine`——库里没有这些列，接口回来是
 * undefined，于是时间列恒显「-」、判由永远看不见、模型列全空。
 * 接口写错不等于有数据，尺子以库为准。
 */
export interface DecisionEventResponse {
  event_id: string;
  /** float epoch 秒（写入侧用 time.time()），不是 datetime 字符串 */
  created_at: number;
  user_id: string;
  agent_id: string;
  chat_id: string | null;
  turn: number | null;
  source: string;
  complexity: string | null;
  action: string;
  judgment: string | null;
  reason: string | null;
  hit_layer: string | null;
  model: string | null;
  latency_ms: number | null;
  cost: number | null;
  tokens: number | null;
  outcome: string | null;
  rating: number | null;
  input_hash: string | null;
}

export interface DecisionListResponse {
  items: DecisionEventResponse[];
  total: number;
  limit: number;
  offset: number;
  error?: string;
}

export interface DecisionSourceStat {
  source: string;
  n: number;
  /** 真判断次数（规则/闸门/开关关闭这类「压根不需要判」不计入） */
  judged: number;
  llm: number;
  degraded: number;
  timeouts: number;
  no_model: number;
  avg_ms: number | null;
  max_ms: number | null;
  cost: number | null;
  tokens: number | null;
  hit: number;
  miss: number;
  pending: number;
}

export interface DecisionStatsResponse {
  days: number;
  total: number;
  cost: number;
  by_source: DecisionSourceStat[];
  error?: string;
}

export interface DecisionHubConfigResponse {
  enabled: boolean;
  timeout_ms: number;
  thinking_enabled: boolean;
  advisor_enabled: boolean;
  acceptance_enabled: boolean;
  [key: string]: unknown;
}

export interface DecisionConfigResponse {
  config: DecisionHubConfigResponse;
  judge: { provider_id: string; model: string; configured?: boolean; source?: string };
  agent_id: string;
  sources: string[];
}

export const decisionsApi = {
  list: (params: {
    chatId?: string;
    source?: string;
    limit?: number;
    offset?: number;
  }) => {
    const qs = new URLSearchParams();
    if (params.chatId) qs.set("chat_id", params.chatId);
    if (params.source) qs.set("source", params.source);
    if (params.limit) qs.set("limit", String(params.limit));
    if (params.offset) qs.set("offset", String(params.offset));
    const q = qs.toString();
    return request<DecisionListResponse>(`/decisions${q ? `?${q}` : ""}`);
  },

  stats: (days = 7, chatId?: string) => {
    const qs = new URLSearchParams({ days: String(days) });
    if (chatId) qs.set("chat_id", chatId);
    return request<DecisionStatsResponse>(`/decisions/stats?${qs.toString()}`);
  },

  rate: (eventId: string, rating: number, outcome?: string) => {
    const qs = new URLSearchParams({ rating: String(rating) });
    if (outcome) qs.set("outcome", outcome);
    return request<{ ok: boolean }>(
      `/decisions/${encodeURIComponent(eventId)}/rating?${qs.toString()}`,
      { method: "POST" },
    );
  },

  getConfig: () => request<DecisionConfigResponse>("/decisions/config"),

  putConfig: (body: Record<string, unknown>) =>
    request<{ ok: boolean; decision_hub: Record<string, unknown> }>(
      "/decisions/config",
      { method: "PUT", body: JSON.stringify(body) },
    ),
};
