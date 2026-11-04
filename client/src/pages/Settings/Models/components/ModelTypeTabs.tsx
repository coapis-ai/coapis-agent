import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  MessageOutlined,
  DatabaseOutlined,
  SwapOutlined,
  AudioOutlined,
  EyeOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import { DEFAULT_MODEL_SLOTS } from "./modelSlots";
import type { ProviderInfo, ModelInfo } from "@/api/types";
import styles from "../index.module.less";

interface ModelTypeTabsProps {
  activeType: string | undefined;
  onChange: (type: string | undefined) => void;
  providers: ProviderInfo[];
}

type AnySlot =
  | "chat"
  | "embedding"
  | "rerank"
  | "audio"
  | "vision"
  | "decision";

// 槽位名单来自共享模块（与后端 VALID_DEFAULT_SLOTS 一一对应）：后端加第 6 个
// 槽位时，这里不再是需要手改的第 4 处重复字面量。
const typeOrder: AnySlot[] = DEFAULT_MODEL_SLOTS as AnySlot[];

const typeIcons: Record<string, JSX.Element> = {
  chat: <MessageOutlined />,
  embedding: <DatabaseOutlined />,
  rerank: <SwapOutlined />,
  audio: <AudioOutlined />,
  vision: <EyeOutlined />,
  decision: <ThunderboltOutlined />,
};

/**
 * Model type filter tabs.
 * Counts are per **model** (not per provider), and an "All" tab is shown
 * first. Clicking "All" clears the active type filter.
 */
export function ModelTypeTabs({
  activeType,
  onChange,
  providers,
}: ModelTypeTabsProps) {
  const { t } = useTranslation();

  const counts = useMemo(() => {
    const c: Record<string, number> = {
      chat: 0,
      embedding: 0,
      rerank: 0,
      audio: 0,
      vision: 0,
      decision: 0,
    };
    providers.forEach((p) => {
      (p.models as ModelInfo[]).forEach((m) => {
        const type = m.model_type || "chat";
        if (type in c) c[type] += 1;
      });
    });
    // decision 是用途槽位不是模型类型：判官跑的是 chat 能力的模型，
    // 所以它的候选数 = chat 模型数。
    c.decision = c.chat;
    return c;
  }, [providers]);

  const total = useMemo(
    () => Object.values(counts).reduce((a, b) => a + b, 0),
    [counts],
  );

  const typeLabels: Record<string, string> = {
    chat: t("models.chatModels"),
    embedding: t("models.embeddingModels"),
    rerank: t("models.rerankModels"),
    audio: t("models.audioModels"),
    vision: t("models.visionModels"),
    decision: t("models.decisionModels"),
  };

  return (
    <div className={styles.modelTypeTabs}>
      <button
        type="button"
        className={`${styles.modelTypeTab} ${
          !activeType ? styles.active : ""
        }`}
        onClick={() => onChange(undefined)}
      >
        {t("models.allTypes")}
        <span className={styles.modelTypeTabCount}>{total}</span>
      </button>
      {typeOrder.map((type) => (
        <button
          key={type}
          type="button"
          className={`${styles.modelTypeTab} ${
            activeType === type ? styles.active : ""
          }`}
          onClick={() => onChange(activeType === type ? undefined : type)}
        >
          {typeIcons[type]} {typeLabels[type]}
          <span className={styles.modelTypeTabCount}>{counts[type]}</span>
        </button>
      ))}
    </div>
  );
}
