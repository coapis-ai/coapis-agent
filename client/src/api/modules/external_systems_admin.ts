import { api } from '../index';

// ─── External Systems Config ───
// Backend routes are under /api/admin/...
// getApiUrl automatically adds '/api' prefix, so we use '/admin/...' to result in '/api/admin/...'

export function getExternalSystemsConfig() {
  return api.get('/admin/external-systems/config');
}

export function saveExternalSystemConfig(data: {
  provider_id: string;
  name: string;
  auth_type?: string;
  client_id?: string;
  shared_secret_use_global?: boolean;
  shared_secret?: string;
  callback_url?: string;
  status?: number;
}) {
  return api.post('/admin/external-systems/config', data);
}

export function deleteExternalSystemConfig(provider_id: string) {
  return api.delete(`/admin/external-systems/config/${provider_id}`);
}

// ─── Identity Bindings ───

export function getIdentityBindings(provider?: string, user_id?: string) {
  const params = new URLSearchParams();
  if (provider) params.append('provider', provider);
  if (user_id) params.append('user_id', user_id);
  return api.get(`/admin/users/identity-bindings${params.toString() ? '?' + params.toString() : ''}`);
}

export function bindIdentityAdmin(data: {
  user_id: string;
  provider: string;
  external_id: string;
}) {
  return api.post('/admin/users/identity-bindings/bind', data);
}

export function unbindIdentityAdmin(data: {
  user_id: string;
  provider: string;
  external_id: string;
}) {
  return api.post('/admin/users/identity-bindings/unbind', data);
}

export function importBatchIdentityMappings(bindings: Array<{
  user_id: string;
  provider: string;
  external_id: string;
}>) {
  return api.post('/admin/users/identity-bindings/import-batch', { bindings });
}
