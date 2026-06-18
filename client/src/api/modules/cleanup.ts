import { request } from "../request";
import type {
  StorageOverview,
  CleanupRules,
  CleanupRunResponse,
  CleanupLogEntry,
} from "../types/cleanup";

export const cleanupApi = {
  /** Get hot/warm/cold storage overview */
  getOverview: () => request<StorageOverview>("/cleanup/overview"),

  /** Run full cleanup */
  runCleanup: (userId?: string) =>
    request<CleanupRunResponse>("/cleanup/run", {
      method: "POST",
      body: JSON.stringify({ user_id: userId || "manual" }),
    }),

  /** Run single cleanup task */
  runSingle: (dataType: string) =>
    request<CleanupRunResponse>(`/cleanup/run/${dataType}`, {
      method: "POST",
    }),

  /** Get current cleanup rules */
  getRules: () => request<{ rules: CleanupRules; defaults: CleanupRules }>("/cleanup/rules"),

  /** Update cleanup rules */
  updateRules: (rules: CleanupRules) =>
    request<{ status: string; rules: CleanupRules }>("/cleanup/rules", {
      method: "PUT",
      body: JSON.stringify({ rules }),
    }),

  /** Get cleanup history */
  getHistory: (limit = 20) =>
    request<{ history: CleanupLogEntry[] }>(`/cleanup/history?limit=${limit}`),
};
