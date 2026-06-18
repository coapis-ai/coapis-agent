import { request } from '../request';

// ==================== 统一多层进化 API ====================

export interface EvolutionOverview {
  total_experiences: number;
  promoted_count: number;
  promotion_rate: number;
  active_users: number;
  active_agents: number;
  bucket_a_count: number;
  bucket_b_count: number;
  users: Array<{
    username: string;
    agent_count: number;
    experience_count: number;
    promoted_count: number;
  }>;
}

export interface UserEvolutionStatus {
  username: string;
  agents: Array<{
    agent_id: string;
    enabled: boolean;
    trajectory_count: number;
    pending_experiences: number;
    approved_experiences: number;
    rejected_experiences: number;
  }>;
  total_experiences: number;
  total_pending: number;
  total_approved: number;
  total_rejected: number;
}

export interface ExperienceEntry {
  id: string;
  content: string;
  category: string;
  source_user: string;
  source_agent: string;
  confidence: number;
  created_at: string;
  status: 'pending' | 'approved' | 'rejected' | 'promoted';
  bucket: 'a' | 'b' | null;
  keywords: string[];
  review_result?: string;
}

export interface BucketEntry extends ExperienceEntry {
  similar_entries?: ExperienceEntry[];
  similarity_score?: number;
}

export interface FoundationEntry extends ExperienceEntry {
  promoted_at: string;
  promoted_by: string;
  affected_users: string[];
  affected_agents: string[];
}

// ==================== 概览 API ====================

export const getEvolutionOverview = (): Promise<EvolutionOverview> => {
  return request('/evolution/overview');
};

// ==================== 用户级进化 API (Level 3) ====================

export const getUserEvolutionStatus = (username: string): Promise<UserEvolutionStatus> => {
  return request(`/evolution/user/${username}`);
};

export const listUserExperiences = (
  username: string,
  status: string = 'all',
  limit: number = 50
): Promise<{ experiences: ExperienceEntry[]; total: number }> => {
  const params = new URLSearchParams();
  params.set('status', status);
  params.set('limit', String(limit));
  return request(`/evolution/user/${username}/experiences?${params.toString()}`);
};

export const getUserAgents = (username: string) => {
  return request(`/evolution/user/${username}/agents`);
};

// ==================== 中间层 API (Level 2) ====================

export const getBucketA = (
  status: string = 'all',
  username?: string
): Promise<{ entries: BucketEntry[]; total: number }> => {
  const params = new URLSearchParams();
  params.set('status', status);
  if (username) params.set('username', username);
  return request(`/evolution/bucket-a?${params.toString()}`);
};

export const getBucketB = (
  status: string = 'all',
  username?: string
): Promise<{ entries: BucketEntry[]; total: number }> => {
  const params = new URLSearchParams();
  params.set('status', status);
  if (username) params.set('username', username);
  return request(`/evolution/bucket-b?${params.toString()}`);
};

export const reviewExperience = (
  experienceId: string,
  action: 'approve' | 'reject',
  comment: string = ''
): Promise<{ success: boolean }> => {
  const params = new URLSearchParams();
  params.set('action', action);
  params.set('comment', comment);
  return request(`/evolution/review/${experienceId}?${params.toString()}`, { method: 'POST' });
};

export const getReviewLog = (limit: number = 50): Promise<{ log: any[]; total: number }> => {
  return request(`/evolution/review-log?limit=${limit}`);
};

// ==================== 归档管理 API ====================

export const listArchivedEntries = (
  limit: number = 100,
  month?: string
): Promise<{ entries: any[]; total: number }> => {
  const params = new URLSearchParams();
  params.set('limit', String(limit));
  if (month) params.set('month', month);
  return request(`/evolution/archive?${params.toString()}`);
};

export const cleanupExpiredArchives = (): Promise<{ success: boolean; cleaned: number }> => {
  return request('/evolution/archive/cleanup', { method: 'POST' });
};

export const getBucketStats = (): Promise<any> => {
  return request('/evolution/bucket-stats');
};

// ==================== 全局基础层 API (Level 1) ====================

export const listFoundationEntries = (
  limit: number = 50
): Promise<{ entries: FoundationEntry[]; total: number }> => {
  return request(`/evolution/foundation?limit=${limit}`);
};

export const promoteToFoundation = (
  experienceId: string,
  comment: string = ''
): Promise<{ success: boolean }> => {
  return request(`/evolution/promote/${experienceId}`, {
    method: 'POST',
    body: JSON.stringify({ comment }),
    headers: { 'Content-Type': 'application/json' },
  });
};

export const demoteFromFoundation = (
  experienceId: string,
  comment: string = ''
): Promise<{ success: boolean }> => {
  return request(`/evolution/demote/${experienceId}`, {
    method: 'POST',
    body: JSON.stringify({ comment }),
    headers: { 'Content-Type': 'application/json' },
  });
};

// ==================== 配置管理 API ====================

export const getEvolutionConfig = () => {
  return request('/evolution/config');
};

export const updateEvolutionConfig = (config: any) => {
  return request('/evolution/config', {
    method: 'PUT',
    body: JSON.stringify(config),
    headers: { 'Content-Type': 'application/json' },
  });
};

export const enableEvolution = () => {
  return request('/evolution/enable', { method: 'POST' });
};

export const disableEvolution = () => {
  return request('/evolution/disable', { method: 'POST' });
};
