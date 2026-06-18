/** Cleanup & archive API types and client. */

export interface StorageTier {
  bytes: number;
  human: string;
  items: string[];
}

export interface StorageOther {
  dialog_bytes: number;
  dialog_human: string;
  tool_results_bytes: number;
  tool_results_human: string;
  browser_bytes: number;
  browser_human: string;
  evolution_bytes: number;
  evolution_human: string;
}

export interface StorageOverview {
  hot: StorageTier;
  warm: StorageTier;
  cold: StorageTier;
  other: StorageOther;
  total_bytes: number;
  total_human: string;
  workspace: string;
}

export interface CleanupRule {
  hot_limit?: number;
  hot_days?: number;
  warm_days: number;
}

export type CleanupRules = Record<string, CleanupRule>;

export interface CleanupResultItem {
  data_type: string;
  items_archived: number;
  items_deleted: number;
  bytes_freed: number;
  details: Record<string, unknown>;
}

export interface CleanupRunResponse {
  status: string;
  total_items_processed: number;
  total_bytes_freed: number;
  results: CleanupResultItem[];
}

export interface CleanupLogEntry {
  id: number;
  user_id: string;
  action: string;
  data_type: string;
  items_count: number;
  bytes_freed: number;
  details: string;
  executed_at: string;
}
