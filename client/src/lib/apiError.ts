/**
 * 后端错误响应 → 一句能照着排查的话。
 *
 * 治「进入场景失败」这种一句话糊：后端 ExceptionHandlerMiddleware 对未捕获异常返回
 * `{error, message, error_id}`，HTTPException 返回 `{detail}`。前端此前只写死文案，
 * 用户看到「进入场景失败」，运维在日志里对着 `Error [<id>]` 捞半天也对不上号。
 * 统一在这里把 detail/message 与状态码、error_id 一起端出来。
 */
const pick = (v: unknown): string =>
  typeof v === "string" && v.trim() ? v.trim() : "";

export async function parseApiError(
  res: Response,
  fallback = "请求失败",
): Promise<string> {
  let body: Record<string, unknown> | null = null;
  try {
    body = (await res.json()) as Record<string, unknown>;
  } catch {
    // 非 JSON 响应（网关 502 之类）：只保留状态码
    body = null;
  }
  const text = pick(body?.detail) || pick(body?.message) || fallback;
  const code = pick(body?.error);
  const traceId = pick(body?.error_id);
  const trace = traceId ? ` [${code || "error"} #${traceId}]` : "";
  return `${text}（HTTP ${res.status}）${trace}`;
}
