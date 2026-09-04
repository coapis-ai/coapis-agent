import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  MessageOutlined,
  DatabaseOutlined,
  SwapOutlined,
  AudioOutlined,
  EyeOutlined,
} from "@ant-design/icons";
import type { ProviderInfo, ModelInfo } from "@/api/types";
import styles from "../index.module.less";

interface ModelTypeTabsProps {
  activeType: string | undefined;
  onChange: (type: string | undefined) => void;
  providers: ProviderInfo[];
}

const typeOrder: Array<"chat" | "embedding" | "rerank" | "audio" | "vision"> = [
  "chat",
  "embedding",
  "rerank",
  "audio",
  "vision",
];

const typeIcons: Record<string, JSX.Element> = {
  chat: <MessageOutlined />,
  embedding: <DatabaseOutlined />,
  rerank: <SwapOutlined />,
  audio: <AudioOutlined />,
  vision: <EyeOutlined />,
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
    };
    providers.forEach((p) => {
      (p.models as ModelInfo[]).forEach((m) => {
        const type = m.model_type || "chat";
        if (type in c) c[type] += 1;
      });
    });
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
