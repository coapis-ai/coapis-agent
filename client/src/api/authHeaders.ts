import { getApiToken, getAgentStorageKey } from "./config";

/** Authorization + X-Agent-Id for API requests. Caller sets Content-Type when needed. */
export function buildAuthHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  const token = getApiToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  try {
    // Read from sessionStorage first (per-tab agent), fall back to localStorage
    // Use user-scoped key to prevent agent leakage between users
    const storageKey = getAgentStorageKey();
    const agentStorage =
      sessionStorage.getItem(storageKey) ||
      localStorage.getItem(storageKey);
    if (agentStorage) {
      const parsed = JSON.parse(agentStorage);
      const selectedAgent = parsed?.state?.selectedAgent;
      if (selectedAgent) {
        // Encode to ensure header value is always ASCII-safe
        headers["X-Agent-Id"] = encodeURIComponent(selectedAgent);
      }
    }
  } catch (error) {
    console.warn("Failed to get selected agent from storage:", error);
  }
  return headers;
}
