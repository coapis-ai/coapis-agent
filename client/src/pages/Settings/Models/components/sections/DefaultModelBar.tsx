import React, { useMemo } from "react";
import { Tooltip } from "antd";
import {
  MessageOutlined,
  DatabaseOutlined,
  SwapOutlined,
  AudioOutlined,
  EyeOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import type { ProviderInfo } from "@/api/types";
import styles from "../../index.module.less";

type ModelType = "chat" | "embedding" | "rerank" | "audio" | "vision";

const TYPE_META: Array<{ type: ModelType; labelKey: string; icon: JSX.Element }> =
  [
    { type: "chat", labelKey: "models.chatModels", icon: <MessageOutlined /> },
    {
      type: "embedding",
      labelKey: "models.embeddingModels",
      icon: <DatabaseOutlined />,
    },
    { type: "rerank", labelKey: "models.rerankModels", icon: <SwapOutlined /> },
    { type: "audio", labelKey: "models.audioModels", icon: <AudioOutlined /> },
    { type: "vision", labelKey: "models.visionModels", icon: <EyeOutlined /> },
  ];

interface DefaultModelBarProps {
  defaultModels: Record<string, { providerId: string; modelId: string }>;
  providers: ProviderInfo[];
}

/**
 * Read-only bar showing the current default model per type.
 * Changing the default is done via the "set as default" button in the
 * ConfiguredModelsSection table below.
 */
export const DefaultModelBar = React.memo(function DefaultModelBar({
  defaultModels,
  providers,
}: DefaultModelBarProps) {
  const { t } = useTranslation();

  // Build a flat lookup from the already-loaded providers (no extra API calls).
  const modelLookup = useMemo(() => {
    const map: Record<string, { modelName: string; providerName: string }> = {};
    for (const p of providers) {
      for (const m of p.models ?? []) {
        map[`${p.id}:${m.id}`] = {
          modelName: m.name,
          providerName: p.name,
        };
      }
    }
    return map;
  }, [providers]);

  return (
    <section>
      <h2 className={styles.sectionTitle}>{t("models.defaultBarTitle")}</h2>
      <div className={styles.defaultModelBar}>
        {TYPE_META.map((meta) => {
          const value = defaultModels[meta.type];
          const key = value ? `${value.providerId}:${value.modelId}` : null;
          const found = key ? modelLookup[key] : undefined;
          const invalid = !!key && !found;

          const displayName = found
            ? `${found.modelName} · ${found.providerName}`
            : invalid
              ? t("models.invalidDefault")
              : t("models.notSet");

          const chipClass = [
            styles.defaultModelChip,
            invalid ? styles.defaultModelChipInvalid : "",
          ]
            .filter(Boolean)
            .join(" ");

          return (
            <div key={meta.type} className={chipClass}>
              <span className={styles.defaultModelChipIcon}>
                {meta.icon}
              </span>
              <span className={styles.defaultModelChipLabel}>
                {t(meta.labelKey)}
              </span>
              <Tooltip title={displayName} placement="top">
                <span
                  className={styles.defaultModelChipValue}
                  data-state={found ? "set" : invalid ? "invalid" : "unset"}
                >
                  {displayName}
                </span>
              </Tooltip>
            </div>
          );
        })}
      </div>
    </section>
  );
});
