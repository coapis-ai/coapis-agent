import { request } from "../request";

/** 判断中枢（v14 §5.2 / U 批）：台账可见 + 配置可改。 */

export interface DecisionEventResponse {
  event_id: string;
  ts: string;
  user_id: string;
  agent_id: string;
  chat_id: string | null;
  turn: number | null;
  source: string;
  action: string;
  judgment: string | null;
  confidence: number | null;
  latency_ms: number | null;
  cost: number | null;
  tokens_in: number | null;
  tokens_out: number | null;
  model_id: string | null;
  provider_id: string | null;
  hit_layer: string | null;
  fallback_reason: string | null;
  thinking: number | null;
  engine: string | null;
  outcome: string | null;
  rating: number | null;
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
  judge: { provider_id: string; model: string };
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
