/**
 * Permission API module.
 * 
 * Calls backend /api/permissions/* endpoints to get role-based
 * module visibility and permission checks.
 */
import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";

/**
 * Get allowed modules for current user.
 * 
 * Returns: { modules: string[], role: string, username: string }
 */
export async function getAllowedModules() {
  const res = await fetch(getApiUrl("/permissions/modules"), {
    method: "GET",
    headers: buildAuthHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to get allowed modules");
  }
  return res.json();
}

/**
 * Get configuration for a specific role.
 * 
 * Returns: { role: string, config: object }
 */
export async function getRoleConfig(role: string) {
  const res = await fetch(getApiUrl(`/permissions/role/${role}`), {
    method: "GET",
    headers: buildAuthHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to get role config");
  }
  return res.json();
}

/**
 * Get all available roles.
 * 
 * Returns: { roles: string[], current_role: string }
 */
export async function getAllRoles() {
  const res = await fetch(getApiUrl("/permissions/roles"), {
    method: "GET",
    headers: buildAuthHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to get all roles");
  }
  return res.json();
}

/**
 * Check if current user has a specific permission.
 * 
 * Returns: { permission: string, allowed: boolean, role: string }
 */
export async function checkPermission(permission: string) {
  const res = await fetch(getApiUrl("/permissions/check"), {
    method: "POST",
    headers: {
      ...buildAuthHeaders(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ permission }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to check permission");
  }
  return res.json();
}

/**
 * Reload permissions config from file (admin only).
 * 
 * Returns: { success: boolean, message: string }
 */
export async function reloadPermissions() {
  const res = await fetch(getApiUrl("/permissions/reload"), {
    method: "POST",
    headers: buildAuthHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to reload permissions");
  }
  return res.json();
}

/**
 * Get full permissions config (admin only).
 * 
 * Returns: { config: object }
 */
export async function getPermissionsConfig() {
  const res = await fetch(getApiUrl("/permissions/config"), {
    method: "GET",
    headers: buildAuthHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to get permissions config");
  }
  return res.json();
}

/**
 * Update role configuration (admin only).
 * 
 * modules can be either:
 *   - string[] (legacy) + permissions string[]
 *   - object (CRUD matrix) e.g. { "chat": { read: true, create: true, ... } }
 */
export async function updateRoleConfig(
  role: string,
  modules: string[] | Record<string, Record<string, boolean>>,
  permissions: string[] = []
) {
  const isMatrix = typeof modules === "object" && !Array.isArray(modules);
  const body: any = isMatrix
    ? { modules }
    : { modules_list: modules, permissions_list: permissions };
  const res = await fetch(getApiUrl(`/permissions/role/${role}`), {
    method: "PUT",
    headers: {
      ...buildAuthHeaders(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to update role config");
  }
  return res.json();
}

/**
 * Update shell permissions for a role (admin only).
 * 
 * Returns: { success: boolean, message: string }
 */
export async function updateShellPermissions(
  role: string,
  whitelist: string[],
  blacklist: string[],
  dangerousPatterns: string[]
) {
  const res = await fetch(getApiUrl(`/permissions/shell/${role}`), {
    method: "PUT",
    headers: {
      ...buildAuthHeaders(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      whitelist,
      blacklist,
      dangerous_patterns: dangerousPatterns,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to update shell permissions");
  }
  return res.json();
}

/**
 * Get audit logs (admin only).
 * 
 * Returns: { logs: object[], total: number }
 */
export async function getAuditLogs(params?: {
  username?: string;
  role?: string;
  result?: string;
  limit?: number;
  offset?: number;
}) {
  const query = new URLSearchParams();
  if (params?.username) query.set("username", params.username);
  if (params?.role) query.set("role", params.role);
  if (params?.result) query.set("result", params.result);
  if (params?.limit) query.set("limit", String(params.limit));
  if (params?.offset) query.set("offset", String(params.offset));

  const res = await fetch(
    getApiUrl(`/permissions/audit?${query.toString()}`),
    {
      method: "GET",
      headers: buildAuthHeaders(),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to get audit logs");
  }
  return res.json();
}

/**
 * Get user permission overrides.
 */
export async function getUserOverrides(username: string) {
  const res = await fetch(getApiUrl(`/permissions/user/${username}`), {
    method: "GET",
    headers: buildAuthHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to get user overrides");
  }
  return res.json();
}

/**
 * Update user permission overrides.
 */
export async function updateUserOverrides(username: string, overrides: Record<string, Record<string, boolean>>) {
  const res = await fetch(getApiUrl(`/permissions/user/${username}`), {
    method: "PUT",
    headers: { ...buildAuthHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify({ overrides }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to update user overrides");
  }
  return res.json();
}

/**
 * Delete user permission overrides.
 */
export async function deleteUserOverrides(username: string) {
  const res = await fetch(getApiUrl(`/permissions/user/${username}`), {
    method: "DELETE",
    headers: buildAuthHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to delete user overrides");
  }
  return res.json();
}

export const permissionsApi = {
  getAllowedModules,
  getRoleConfig,
  getAllRoles,
  checkPermission,
  reloadPermissions,
  getPermissionsConfig,
  updateRoleConfig,
  updateShellPermissions,
  getAuditLogs,
  getUserOverrides,
  updateUserOverrides,
  deleteUserOverrides,
};
