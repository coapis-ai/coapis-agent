import { request } from "../request";
import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";

export interface SubTaskResponse {
  name: string;
  description: string;
  expected_outcome: string;
  outcome: string | null;
  state: "todo" | "in_progress" | "done" | "abandoned";
  created_at: string | null;
  finished_at: string | null;
}

export interface PlanStateResponse {
  id: string;
  name: string;
  description: string;
  expected_outcome: string;
  state: "todo" | "in_progress" | "done" | "abandoned";
  subtasks: SubTaskResponse[];
  created_at: string | null;
  finished_at: string | null;
  outcome: string | null;
  /**
   * True when the plan's lifecycle has ended (``finish_plan`` cleared
   * ``current_plan``) but the final snapshot is still being served, so the
   * UI can show a completed plan instead of an empty one.
   */
  finished?: boolean;
  /** Session keys this plan is cached under (channel id and/or chat UUID). */
  session_ids?: string[];
}

/** Envelope returned by ``GET /plan/current``. */
export interface PlanQueryResponse {
  plan: PlanStateResponse | null;
  session_id?: string | null;
  usage?: Record<string, unknown>;
}

export interface PlanConfigResponse {
  enabled: boolean;
  agent_id?: string;
}

/**
 * Accept both the documented envelope and a bare plan object, so callers
 * never mistake the envelope for a plan (which used to render 0/0).
 */
export function unwrapPlan(
  body: PlanQueryResponse | PlanStateResponse | null | undefined,
): PlanStateResponse | null {
  if (!body || typeof body !== "object") return null;
  if ("plan" in body) {
    const inner = (body as PlanQueryResponse).plan;
    return inner ?? null;
  }
  // A bare plan must at least carry an id or a name; anything else (e.g. an
  // unexpected `{}` body) must not be mistaken for a plan, or the UI will
  // render an empty "0/0" panel that looks like it has data.
  if (!("id" in body) && !("name" in body)) return null;
  return body as PlanStateResponse;
}

export const planApi = {
  /** Resolved plan for a session, or ``null`` when there is none. */
  getCurrentPlan: async (
    sessionId?: string,
    agentId?: string,
  ): Promise<PlanStateResponse | null> => {
    const params = new URLSearchParams();
    if (sessionId) params.set("session_id", sessionId);
    if (agentId) params.set("agent_id", agentId);
    const qs = params.toString();
    const body = await request<
      PlanQueryResponse | PlanStateResponse | null
    >(`/plan/current${qs ? `?${qs}` : ""}`);
    return unwrapPlan(body);
  },

  getPlanConfig: (agentId?: string) => {
    const qs = agentId ? `?agent_id=${encodeURIComponent(agentId)}` : "";
    return request<PlanConfigResponse>(`/plan/config${qs}`);
  },

  updatePlanConfig: (body: PlanConfigResponse, agentId?: string) => {
    const qs = agentId ? `?agent_id=${encodeURIComponent(agentId)}` : "";
    return request<PlanConfigResponse>(`/plan/config${qs}`, {
      method: "PUT",
      body: JSON.stringify(body),
    });
  },
};

/**
 * True when an SSE payload belongs to the session we are watching.
 *
 * The runtime caches a plan under the channel session id **and** the chat
 * UUID; whichever one the caller holds, the payload's ``session_ids`` list
 * contains it. Matching only on ``session_id`` used to drop every event for
 * callers that address chats by UUID.
 */
export function planEventMatchesSession(
  data: Record<string, unknown>,
  sessionId?: string,
): boolean {
  if (!sessionId) return true;
  const aliases = data.session_ids;
  if (Array.isArray(aliases) && aliases.includes(sessionId)) return true;
  const eventSid = (data.session_id as string | undefined) || "";
  return !eventSid || eventSid === sessionId;
}

/**
 * Subscribe to plan updates via SSE using fetch streaming.
 * Filters events by sessionId so users only see their own plans.
 * Returns an unsubscribe function.
 */
export function subscribePlanUpdates(
  onUpdate: (
    plan: PlanStateResponse | null,
    sessionId: string | undefined,
    /** Every session key this plan is cached under (aliases for matching). */
    sessionAliases?: string[],
  ) => void,
  onError?: (err: unknown) => void,
  options?: { agentId?: string; sessionId?: string },
): () => void {
  let aborted = false;
  const controller = new AbortController();
  const filterSessionId = options?.sessionId;

  async function connect() {
    while (!aborted) {
      try {
        const params = new URLSearchParams();
        if (options?.agentId) params.set("agent_id", options.agentId);
        const qs = params.toString();
        const url = getApiUrl(`/plan/stream${qs ? `?${qs}` : ""}`);
        const response = await fetch(url, {
          headers: buildAuthHeaders(),
          signal: controller.signal,
        });

        if (!response.ok || !response.body) {
          throw new Error(`SSE connect failed: ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (!aborted) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (line.startsWith("data: ")) {
              try {
                const data = JSON.parse(line.slice(6));
                if (data.type === "plan_update") {
                  if (!planEventMatchesSession(data, filterSessionId)) {
                    continue;
                  }
                  const aliases: string[] = Array.isArray(data.session_ids)
                    ? (data.session_ids as string[])
                    : Array.isArray(data.plan?.session_ids)
                      ? (data.plan.session_ids as string[])
                      : [];
                  onUpdate(
                    unwrapPlan({ plan: data.plan ?? null }),
                    data.session_id,
                    aliases,
                  );
                }
              } catch {
                // ignore parse errors
              }
            }
          }
        }
      } catch (err) {
        if (aborted) return;
        onError?.(err);
        // Reconnect after 3s
        await new Promise((r) => setTimeout(r, 3000));
      }
    }
  }

  connect();

  return () => {
    aborted = true;
    controller.abort();
  };
}
