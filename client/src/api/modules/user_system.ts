import { api } from '../index';

// Backend routes are directly under / (no prefix)
// /users/*, /points/*, /tokens/*

// ─── Users ───

export function getUsersConfig() {
  return api.get('/users/config');
}

export function registerUser(data: { username: string; password: string; email?: string; display_name?: string }) {
  return api.post('/users/register', data);
}

export function loginUser(data: { username: string; password: string }) {
  return api.post('/users/login', data);
}

export function getCurrentUser() {
  return api.get('/users/me');
}

export function getUser(username: string) {
  return api.get(`/users/${username}`);
}

export function updateUser(username: string, data: { email?: string; display_name?: string; avatar_url?: string; password?: string }) {
  return api.put(`/users/${username}`, data);
}

export function deleteUser(username: string) {
  return api.delete(`/users/${username}`);
}

export function listUsers(page = 1, pageSize = 20) {
  return api.get(`/users?page=${page}&page_size=${pageSize}`);
}

export function recalculateLevel(username: string) {
  return api.post(`/users/${username}/recalculate-level`);
}

// ─── Points ───

export function getPointsConfig() {
  return api.get('/points/config');
}

export function addPoints(data: { username: string; amount: number; source: string; description?: string }) {
  return api.post('/points/add', data);
}

export function spendPoints(data: { username: string; amount: number; source: string; description?: string }) {
  return api.post('/points/spend', data);
}

export function getPointTransactions(username: string, page = 1, pageSize = 50, source?: string) {
  const params = [`username=${encodeURIComponent(username)}`, `page=${page}`, `page_size=${pageSize}`];
  if (source) params.push(`source=${encodeURIComponent(source)}`);
  return api.get(`/points/transactions?${params.join('&')}`);
}

export function getLevelInfo() {
  return api.get('/points/levels');
}

// ─── Tokens ───

export function recordTokenUsage(data: { username: string; model: string; input_tokens: number; output_tokens: number; agent_id?: string }) {
  return api.post('/tokens/record', data);
}

export function getQuotaStatus(username: string) {
  return api.get(`/tokens/quota/${username}`);
}

export function getTokenSummary(username?: string) {
  if (username) {
    return api.get(`/tokens/summary/${username}`);
  }
  // Global summary (admin only)
  return api.get('/tokens/summary');
}

export function getTokenHistory(username: string, page = 1, pageSize = 50, model?: string, agentId?: string) {
  const params = [`username=${encodeURIComponent(username)}`, `page=${page}`, `page_size=${pageSize}`];
  if (model) params.push(`model=${encodeURIComponent(model)}`);
  if (agentId) params.push(`agent_id=${encodeURIComponent(agentId)}`);
  return api.get(`/tokens/history?${params.join('&')}`);
}

export function resetMonthlyQuotas() {
  return api.post('/tokens/reset-monthly');
}

export function getModelPricing() {
  return api.get('/tokens/pricing');
}
