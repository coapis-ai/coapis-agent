import { request } from "../request";

// Evolution status
export const getEvolutionStatus = (agentId = 'default') => {
  return request(`/evolution/status?agent_id=${encodeURIComponent(agentId)}`);
};

// Evolution stats
export const getEvolutionStats = (agentId = 'default') => {
  return request(`/evolution/stats?agent_id=${encodeURIComponent(agentId)}`);
};

// List trajectories
export const listTrajectories = (agentId = 'default', limit = 50) => {
  return request(`/evolution/trajectories?agent_id=${encodeURIComponent(agentId)}&limit=${limit}`);
};

// Get trajectory by session
export const getTrajectory = (sessionId: string, agentId = 'default', limit = 100) => {
  return request(`/evolution/trajectories/${sessionId}?agent_id=${encodeURIComponent(agentId)}&limit=${limit}`);
};

// List experiences
export const listExperiences = (agentId = 'default', status = 'all', limit = 50) => {
  return request(`/evolution/experiences?agent_id=${encodeURIComponent(agentId)}&status=${status}&limit=${limit}`);
};

// Trigger experience extraction
export const triggerExtraction = (agentId = 'default') => {
  return request(`/evolution/experiences/extract?agent_id=${encodeURIComponent(agentId)}`, { method: 'POST' });
};

// Approve experience
export const approveExperience = (experienceId: string, agentId = 'default') => {
  return request(`/evolution/experiences/${experienceId}/approve?agent_id=${encodeURIComponent(agentId)}`, { method: 'POST' });
};

// Reject experience
export const rejectExperience = (experienceId: string, agentId = 'default') => {
  return request(`/evolution/experiences/${experienceId}/reject?agent_id=${encodeURIComponent(agentId)}`, { method: 'POST' });
};

// Knowledge flow status
export const getKnowledgeFlowStatus = (agentId = 'default') => {
  return request(`/evolution/knowledge-flow/status?agent_id=${encodeURIComponent(agentId)}`);
};

// List pending flows
export const listPendingFlows = (agentId = 'default') => {
  return request(`/evolution/knowledge-flow/pending?agent_id=${encodeURIComponent(agentId)}`);
};

// Approve flow
export const approveFlow = (recordId: string, agentId = 'default', comment = '') => {
  return request(`/evolution/knowledge-flow/${recordId}/approve?agent_id=${encodeURIComponent(agentId)}&comment=${encodeURIComponent(comment)}`, { method: 'POST' });
};

// Reject flow
export const rejectFlow = (recordId: string, agentId = 'default', comment = '') => {
  return request(`/evolution/knowledge-flow/${recordId}/reject?agent_id=${encodeURIComponent(agentId)}&comment=${encodeURIComponent(comment)}`, { method: 'POST' });
};

// Backend review status
export const getReviewStatus = (agentId = 'default') => {
  return request(`/evolution/review/status?agent_id=${encodeURIComponent(agentId)}`);
};

// Get review history
export const getReviewHistory = (agentId = 'default', limit = 50) => {
  return request(`/evolution/review/history?agent_id=${encodeURIComponent(agentId)}&limit=${limit}`);
};

// Start review
export const startReview = (agentId = 'default') => {
  return request(`/evolution/review/start?agent_id=${encodeURIComponent(agentId)}`, { method: 'POST' });
};

// Stop review
export const stopReview = (agentId = 'default') => {
  return request(`/evolution/review/stop?agent_id=${encodeURIComponent(agentId)}`, { method: 'POST' });
};
