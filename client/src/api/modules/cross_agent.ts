import { api } from '@/api/index';

export interface BucketStats {
  bucket_a: {
    total: number;
    capacity: number;
    by_category: Record<string, number>;
    by_status: Record<string, number>;
  };
  bucket_b: {
    total: number;
    capacity: number;
    pending: number;
    by_category: Record<string, number>;
    by_status: Record<string, number>;
  };
  review_log: {
    total: number;
  };
}

export interface CrossAgentStatus {
  enabled: boolean;
  config: {
    promotion_threshold: number;
    cold_start_threshold: number;
    review_interval_minutes: number;
    bucket_a_capacity: number;
    bucket_b_capacity: number;
    archive_ttl_days: number;
    min_confidence: number;
    max_keywords: number;
    similarity_threshold: number;
  };
  buckets: BucketStats;
}

export interface ExperienceEntry {
  id: string;
  content: string;
  category: string;
  source_user: string;
  agent_level: string;
  confidence: number;
  created_at: string;
  bucket: string;
  status: string;
  keywords: string[];
  review_result: string | null;
}

export const crossAgentApi = {
  getStatus: () => api.get<CrossAgentStatus>('/cross-agent/status'),

  getBucketA: (status?: string) => {
    const params = status ? `?status=${encodeURIComponent(status)}` : '';
    return api.get<{ entries: ExperienceEntry[]; total: number }>(`/cross-agent/bucket-a${params}`);
  },

  getBucketB: (status?: string) => {
    const params = status ? `?status=${encodeURIComponent(status)}` : '';
    return api.get<{ entries: ExperienceEntry[]; total: number }>(`/cross-agent/bucket-b${params}`);
  },

  reportExperience: (content: string, category: string = 'general', confidence: number = 0.8) =>
    api.post<{ success: boolean; entry: ExperienceEntry }>('/cross-agent/report', {
      content,
      category,
      confidence,
    }),

  triggerReviewCycle: () =>
    api.post<{ success: boolean; results: any[]; total_reviewed: number; promoted: number }>('/cross-agent/review-cycle'),

  getReviewLog: (limit: number = 50) =>
    api.get<{ log: any[]; total: number }>(`/cross-agent/review-log?limit=${limit}`),

  cleanupArchives: () =>
    api.post<{ success: boolean; cleaned: number }>('/cross-agent/cleanup-archives'),

  enable: () => api.post<{ success: boolean; enabled: boolean }>('/cross-agent/enable'),

  disable: () => api.post<{ success: boolean; enabled: boolean }>('/cross-agent/disable'),
};
