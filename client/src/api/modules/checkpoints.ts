/**
 * 检查点（B5-A）前端 API —— 文件级可回滚快照。
 *
 * 后端默认关（开关 COAPIS_CHECKPOINTS_ENABLED）：
 * - 列表端点未开启时返回 404，detail 里写明怎么开启；
 * - 预览端点是只读 dry-run（不写盘）；
 * - 恢复端点必须显式 confirm=true（二次确认）。
 */
import { request } from "../request";

export interface CheckpointSummary {
  checkpoint_id: string;
  kind: string;
  session?: string | null;
  note?: string | null;
  created_at?: number | null;
  file_count?: number | null;
  total_bytes?: number | null;
  pre_restore_of?: string | null;
}

export interface CheckpointListResponse {
  enabled: boolean;
  username: string;
  count: number;
  items: CheckpointSummary[];
  /** 未开启 / 出错时后端给的说明（直接把开关名亮出来，不猜） */
  note?: string | null;
}

export interface CheckpointDiff {
  rel: string;
  kind: string;
  sha256?: string | null;
  size_bytes?: number | null;
}

export interface CheckpointPreview {
  checkpoint_id: string;
  dry_run: boolean;
  wrote_to_disk: boolean;
  writable: boolean;
  to_restore_count?: number;
  to_restore_bytes?: number;
  diffs: CheckpointDiff[];
  missing_blobs: string[];
  note?: string | null;
}

export interface CheckpointRestoreResult {
  checkpoint_id: string;
  restored: string[];
  skipped: string[];
  total_bytes: number;
  pre_restore_checkpoint_id?: string | null;
}

export const checkpointsApi = {
  /** 列检查点（只读）。未开启时不抛错 —— 把 404 的 detail 变成 enabled=false。 */
  list: async (params?: { session?: string; limit?: number; user?: string }) => {
    const qs = new URLSearchParams();
    if (params?.session) qs.set("session", params.session);
    if (params?.limit) qs.set("limit", String(params.limit));
    if (params?.user) qs.set("user", params.user);
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    try {
      return await request<CheckpointListResponse>(`/checkpoints${suffix}`);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      // 404 = 功能未开启（后端 detail 里带开关名）；403 = 作用域不允许
      return {
        enabled: false,
        username: "",
        count: 0,
        items: [],
        note: msg,
      };
    }
  },

  /** 预览恢复差异 —— 只读演练，绝不影响盘上文件。 */
  preview: (body: { checkpoint_id: string; user?: string; path_prefix?: string }) =>
    request<CheckpointPreview>("/checkpoints/preview", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  /** 恢复 —— 必须 confirm=true（二次确认在 UI 里做，不靠前端默认值）。 */
  restore: (body: {
    checkpoint_id: string;
    confirm: true;
    session?: string;
    path_prefix?: string;
    user?: string;
  }) =>
    request<CheckpointRestoreResult>("/checkpoints/restore", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
