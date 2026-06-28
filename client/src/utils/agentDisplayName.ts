import type { TFunction } from "i18next";
import type { AgentSummary } from "../api/types/agents";

/** Check if an agent is the user's default agent (id pattern: user:{username}). */
export function isDefaultAgent(agentId: string): boolean {
  return agentId.startsWith("user:");
}

/** UI label for an agent; default agents (user:*) use i18n + username, others use API `name`. */
export function getAgentDisplayName(
  agent: Pick<AgentSummary, "id" | "name">,
  t: TFunction,
): string {
  if (isDefaultAgent(agent.id)) {
    // If name is already set (e.g. "Default（admin）"), use it directly
    if (agent.name && agent.name !== "Default") {
      return agent.name;
    }
    // Fallback: extract username from id and format with i18n
    const username = agent.id.replace("user:", "");
    return `${t("agent.defaultDisplayName")}（${username}）`;
  }
  return agent.name || agent.id;
}
