/**
 * 默认模型槽位的前端单一来源。
 *
 * 后端 `server/coapis/providers/model_type.py::VALID_DEFAULT_SLOTS` 是权威
 * （五个模型类型 + `decision` 决策槽位）；这里必须与它一一对应，新增槽位
 * 两处一起改。历史实现是页面里写死 5 个类型、4 处各自重复一遍，于是后端
 * 加第 6 个槽位时前端永远不知道（v16 的问题 2 根因）。
 *
 * 图标表在 `modelSlotsIcons.tsx`（JSX 住 .tsx），这里只做纯数据 + 转出口。
 */
export { SLOT_ICONS } from "./modelSlotsIcons";

export type DefaultSlot =
  | "chat"
  | "embedding"
  | "rerank"
  | "audio"
  | "vision"
  | "decision";

/** 与后端 VALID_DEFAULT_SLOTS 同序同集合。 */
export const DEFAULT_MODEL_SLOTS: DefaultSlot[] = [
  "chat",
  "embedding",
  "rerank",
  "audio",
  "vision",
  "decision",
];

/** 槽位对应的模型类型：decision 槽位里放 chat 模型（判官要输出 JSON）。 */
export const SLOT_MODEL_TYPE: Record<DefaultSlot, string> = {
  chat: "chat",
  embedding: "embedding",
  rerank: "rerank",
  audio: "audio",
  vision: "vision",
  decision: "chat",
};

export const SLOT_LABEL_KEYS: Record<DefaultSlot, string> = {
  chat: "models.chatModels",
  embedding: "models.embeddingModels",
  rerank: "models.rerankModels",
  audio: "models.audioModels",
  vision: "models.visionModels",
  decision: "models.decisionModels",
};

/** 某槽位当前是否已配置（defaultModels 里有 provider+model 才算）。 */
export function slotIsConfigured(
  defaultModels: Record<string, { provider_id?: string; model_id?: string }> | undefined,
  slot: string,
): boolean {
  const entry = defaultModels?.[slot];
  return Boolean(entry?.provider_id && entry?.model_id);
}
