import { api } from '../index';

/**
 * Get current user info (with role, quota)
 * GET /user/me
 */
export function getCurrentUser() {
  return api.get('/user/me');
}

/**
 * Get current user preferences
 * GET /user/preferences
 */
export function getUserPreferences() {
  return api.get('/user/preferences');
}

/**
 * Update current user preferences
 * PUT /user/preferences
 */
export function updateUserPreferences(data: {
  theme?: string;
  language?: string;
  sidebar_collapsed?: number;
  chat_hide_details?: number;
  chat_auto_scroll?: number;
  chat_font_size?: string;
  chat_code_theme?: string;
  email_notifications?: number;
  push_notifications?: number;
  default_agent_id?: string;
  default_model?: string;
}) {
  return api.put('/user/preferences', data);
}
