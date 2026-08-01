import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type { ProviderInfo } from "@/api/types/provider";
import styles from "../index.module.less";

interface ModelTypeTabsProps {
  activeType: string | undefined;
  onChange: (type: string | undefined) => void;
  providers: ProviderInfo[];
}

interface TypeCount {
  type: string;
  icon: string;
  labelKey: string;
  count: number;
}

/**
 * Model type tabs component
 * Used in model management page to filter providers by model type
 */
export function ModelTypeTabs({
  activeType,
  onChange,
  providers,
}: ModelTypeTabsProps) {
  const { t } = useTranslation();

  const typeCounts: TypeCount[] = useMemo(() => {
    const counts: Record<string, number> = {
      chat: 0,
      embedding: 0,
      rerank: 0,
      audio: 0,
      vision: 0,
    };

    providers.forEach((p) => {
      const types = new Set(
        p.models.map((m: any) => m.model_type || "chat")
      );
      types.forEach((t) => {
        if (counts[t] !== undefined) {
          counts[t]++;
        }
      });
    });

    return [
      { type: "chat", icon: "💬", labelKey: "models.chatModels", count: counts.chat },
      { type: "embedding", icon: "🔢", labelKey: "models.embeddingModels", count: counts.embedding },
      { type: "rerank", icon: "🔄", labelKey: "models.rerankModels", count: counts.rerank },
      { type: "audio", icon: "🎵", labelKey: "models.audioModels", count: counts.audio },
      { type: "vision", icon: "👁", labelKey: "models.visionModels", count: counts.vision },
    ];
  }, [providers]);

  return (
    <div className={styles.modelTypeTabs}>
      {typeCounts.map(({ type, icon, labelKey, count }) => (
        <div
          key={type}
          className={`${styles.modelTypeTab} ${activeType === type ? styles.active : ""}`}
          onClick={() => onChange(activeType === type ? undefined : type)}
        >
          <span className={styles.tabIcon}>{icon}</span>
          <span className={styles.tabLabel}>{t(labelKey)}</span>
          <span className={styles.tabCount}>({count})</span>
        </div>
      ))}
    </div>
  );
}
