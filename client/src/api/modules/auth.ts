import { getApiUrl } from "../config";

export interface LoginResponse {
  token: string;
  username: string;
  message?: string;
  first_login?: boolean;
  default_agent_id?: string;
}

export interface AuthStatusResponse {
  enabled: boolean;
  has_users: boolean;
}

export const authApi = {
  login: async (username: string, password: string, expires_in?: number): Promise<LoginResponse> => {
    const body: any = { username, password };
    if (expires_in !== undefined) body.expires_in = expires_in;
    const res = await fetch(getApiUrl("/auth/login"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Login failed");
    }
    return res.json();
  },

  register: async (
    username: string,
    password: string,
  ): Promise<LoginResponse> => {
    const res = await fetch(getApiUrl("/auth/register"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Registration failed");
    }
    return res.json();
  },

  getStatus: async (): Promise<AuthStatusResponse> => {
    const res = await fetch(getApiUrl("/auth/status"));
    if (!res.ok) throw new Error("Failed to check auth status");
    return res.json();
  },

  updateProfile: async (
    currentPassword: string,
    newUsername?: string,
    newPassword?: string,
  ): Promise<LoginResponse> => {
    const token = localStorage.getItem("coapis_auth_token") || "";
    const res = await fetch(getApiUrl("/auth/update-profile"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        current_password: currentPassword,
        new_username: newUsername || null,
        new_password: newPassword || null,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Update failed");
    }
    return res.json();
  },

  completeOnboarding: async (data: {
    agent_name?: string;
    agent_style?: string;
    agent_role?: string;
    user_name?: string;
  }): Promise<{ ok: boolean }> => {
    const token = localStorage.getItem("coapis_auth_token") || "";
    const res = await fetch(getApiUrl("/auth/onboarding/complete"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to complete onboarding");
    }
    return res.json();
  },

  getOnboardingStatus: async (): Promise<{ onboarding_completed: boolean }> => {
    const token = localStorage.getItem("coapis_auth_token") || "";
    const res = await fetch(getApiUrl("/auth/onboarding/status"), {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to get onboarding status");
    }
    return res.json();
  },
};
