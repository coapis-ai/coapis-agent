import { getApiUrl, clearAuthToken } from "./config";
import { buildAuthHeaders } from "./authHeaders";

function getErrorMessageFromBody(
  text: string,
  contentType: string,
): string | null {
  if (!text) {
    return null;
  }

  if (!contentType.includes("application/json")) {
    return text;
  }

  try {
    const payload = JSON.parse(text) as {
      detail?: unknown;
      message?: unknown;
      error?: unknown;
    };

    if (typeof payload.detail === "string" && payload.detail) {
      return payload.detail;
    }
    if (typeof payload.message === "string" && payload.message) {
      return payload.message;
    }
    if (typeof payload.error === "string" && payload.error) {
      return payload.error;
    }
  } catch {
    return text;
  }

  return text;
}

function buildHeaders(method?: string, extra?: HeadersInit): Headers {
  // Normalize extra to a Headers instance for consistent handling
  const headers = extra instanceof Headers ? extra : new Headers(extra);

  // Only add Content-Type for methods that typically have a body
  if (method && ["POST", "PUT", "PATCH"].includes(method.toUpperCase())) {
    // Don't override if caller explicitly set Content-Type
    if (!headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
  }

  for (const [key, value] of Object.entries(buildAuthHeaders())) {
    if (!headers.has(key)) {
      headers.set(key, value);
    }
  }

  // ── Centralized X-Agent-Id encoding ──
  // Callers may pass raw (possibly non-ASCII) agent IDs in options.headers.
  // Ensure the final header value is always ASCII-safe for HTTP transport.
  const rawAgentId = headers.get("X-Agent-Id");
  if (rawAgentId) {
    try {
      // Check if it's already encoded (contains only ASCII safe chars)
      // If decoding changes the value, it was already encoded → keep it
      // If decoding doesn't change, it's raw → encode it
      const decoded = decodeURIComponent(rawAgentId);
      if (decoded === rawAgentId) {
        // Raw value, needs encoding
        headers.set("X-Agent-Id", encodeURIComponent(rawAgentId));
      }
      // else: already encoded, keep as-is
    } catch {
      // decodeURIComponent failed → value has % sequences but malformed
      // It's likely already encoded, keep as-is
    }
  }

  return headers;
}

export async function request<T = unknown>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const url = getApiUrl(path);
  const method = options.method || "GET";
  const headers = buildHeaders(method, options.headers);

  // Always bypass browser HTTP cache for API requests.
  // Without this, fetch() with default cache mode may return stale
  // cached responses for GET requests when the backend doesn't set
  // Cache-Control headers.
  const cacheMode: RequestCache = method === "GET" ? "no-store" : "default";

  const response = await fetch(url, {
    ...options,
    headers,
    cache: cacheMode,
  });

  if (!response.ok) {
    if (response.status === 401) {
      clearAuthToken();
      if (window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
      throw new Error("Not authenticated");
    }

    const text = await response.text().catch(() => "");
    const contentType = response.headers.get("content-type") || "";
    const errorMessage = getErrorMessageFromBody(text, contentType);

    // Preserve raw body for parseErrorDetail() to extract structured fields
    const finalMessage = errorMessage
      ? `${errorMessage} - ${text}`
      : `Request failed: ${response.status} ${response.statusText}`;

    const err = new Error(finalMessage) as Error & {
      status?: number;
      isForbidden?: boolean;
    };
    err.status = response.status;
    if (response.status === 403) {
      err.isForbidden = true;
      // Override message with a clear permission-denied hint
      err.message = "无权限执行此操作";
    }
    throw err;
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    return (await response.text()) as unknown as T;
  }

  return (await response.json()) as T;
}
