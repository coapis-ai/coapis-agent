import { request } from "../request";
import type { ChannelConfig, SingleChannelConfig } from "../types";
import { useAgentStore } from "../../stores/agentStore";

/** Read current selectedAgent from Zustand store (sync, no hooks). */
function getSelectedAgent(): string | undefined {
  try {
    const { selectedAgent } = useAgentStore.getState();
    // Empty or "default" means user's own agent — don't send it, let backend resolve by username
    return selectedAgent && selectedAgent !== ""
      ? selectedAgent
      : undefined;
  } catch {
    return undefined;
  }
}

/** Build headers dict with X-Agent-Id when an explicit agent is selected. */
function agentHeaders(): Record<string, string> | undefined {
  const id = getSelectedAgent();
  return id ? { "X-Agent-Id": id } : undefined;
}

export const channelApi = {
  listChannelTypes: () =>
    request<string[]>("/config/channels/types", {
      headers: agentHeaders(),
    }),

  listChannels: () =>
    request<ChannelConfig>("/config/channels", {
      headers: agentHeaders(),
    }),

  updateChannels: (body: ChannelConfig) =>
    request<ChannelConfig>("/config/channels", {
      method: "PUT",
      body: JSON.stringify(body),
      headers: agentHeaders(),
    }),

  getChannelConfig: (channelName: string) =>
    request<SingleChannelConfig>(
      `/config/channels/${encodeURIComponent(channelName)}`,
      { headers: agentHeaders() },
    ),

  updateChannelConfig: (channelName: string, body: SingleChannelConfig) =>
    request<SingleChannelConfig>(
      `/config/channels/${encodeURIComponent(channelName)}`,
      {
        method: "PUT",
        body: JSON.stringify(body),
        headers: agentHeaders(),
      },
    ),

  getChannelQrcode: (channel: string) =>
    request<{ qrcode_img: string; poll_token: string }>(
      `/config/channels/${encodeURIComponent(channel)}/qrcode`,
      { headers: agentHeaders() },
    ),

  getChannelQrcodeStatus: (channel: string, token: string) =>
    request<{
      status: string;
      credentials: Record<string, string>;
    }>(
      `/config/channels/${encodeURIComponent(
        channel,
      )}/qrcode/status?token=${encodeURIComponent(token)}`,
      { headers: agentHeaders() },
    ),
};
