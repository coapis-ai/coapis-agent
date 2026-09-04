import React, { useState, useEffect, useMemo } from "react";
import { Select, Spin } from "antd";
import {
  MessageOutlined,
  DatabaseOutlined,
  SwapOutlined,
  AudioOutlined,
  EyeOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import api from "@/api";
import styles from "../../index.module.less";

type ModelType = "chat" | "embedding" | "rerank" | "audio" | "vision";

interface ModelByType {
  provider_id: string;
  provider_name: string;
  model_id: string;
  model_name: string;
  model_type: string;
}

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

interface DefaultModelChipProps {
  modelType: ModelType;
  icon: JSX.Element;
  label: string;
  value?: { providerId: string; modelId: string } | null;
  onChange: (
    modelType: ModelType,
    value: { providerId: string; modelId: string } | null,
  ) => void;
  refreshKey: number;
}

function DefaultModelChip({
  modelType,
  icon,
  label,
  value,
  onChange,
  refreshKey,
}: DefaultModelChipProps) {
  const { t } = useTranslation();
  const [models, setModels] = useState<ModelByType[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api
      .get(`/models/by-type/${modelType}`)
      .then((data: unknown) => {
        setModels(Array.isArray(data) ? (data as ModelByType[]) : []);
      })
      .catch((err) => {
        console.error(`Failed to load ${modelType} models:`, err);
        setModels([]);
      })
      .finally(() => {
        setLoading(false);
      });
  }, [modelType, refreshKey]);

  const options = useMemo(() => {
    const grouped: Record<
      string,
      Array<{ value: string; label: string; name: string }>
    > = {};
    models.forEach((m) => {
      if (!grouped[m.provider_name]) grouped[m.provider_name] = [];
      grouped[m.provider_name].push({
        value: `${m.provider_id}:${m.model_id}`,
        label: `${m.model_name} · ${m.provider_name}`,
        name: m.model_name,
      });
    });
    return Object.entries(grouped).map(([providerName, opts]) => ({
      label: providerName,
      options: opts,
    }));
  }, [models]);

  const valueStr = value ? `${value.providerId}:${value.modelId}` : undefined;
  const valueValid =
    !!valueStr && options.some((g) => g.options.some((o) => o.value === valueStr));
  const invalid = !!valueStr && !valueValid;

  const handleSelect = (combined: string | undefined) => {
    if (!combined) {
      // Clearing is ignored: the default slot keeps its last value.
      return;
    }
    const [providerId, modelId] = combined.split(":");
    onChange(modelType, { providerId, modelId });
  };

  return (
    <div
      className={`${styles.defaultModelChip} ${
        invalid ? styles.defaultModelChipInvalid : ""
      }`}
    >
      <span className={styles.defaultModelChipIcon}>{icon}</span>
      <span className={styles.defaultModelChipLabel}>{label}</span>
      <Spin spinning={loading} size="small">
        <Select
          size="small"
          className={styles.defaultModelChipSelect}
          value={invalid ? undefined : valueStr}
          onChange={handleSelect}
          options={options}
          placeholder={
            invalid
              ? t("models.invalidDefault")
              : valueStr
              ? ""
              : t("models.notSet")
          }
          showSearch
          optionFilterProp="label"
          notFoundContent={t("models.noModels")}
        />
      </Spin>
    </div>
  );
}

interface DefaultModelBarProps {
  defaultModels: Record<string, { providerId: string; modelId: string }>;
  onChange: (
    modelType: ModelType,
    value: { providerId: string; modelId: string } | null,
  ) => void;
  refreshKey: number;
}

/**
 * Compact bar with one chip per model type. Each chip is a dropdown that
 * directly switches the default model of that type (saved immediately on
 * change). Shows three states: set / not set / invalid (pointing to a
 * deleted model).
 */
export const DefaultModelBar = React.memo(function DefaultModelBar({
  defaultModels,
  onChange,
  refreshKey,
}: DefaultModelBarProps) {
  const { t } = useTranslation();
  return (
    <section>
      <h2 className={styles.sectionTitle}>{t("models.defaultBarTitle")}</h2>
      <div className={styles.defaultModelBar}>
        {TYPE_META.map((meta) => (
          <DefaultModelChip
            key={meta.type}
            modelType={meta.type}
            icon={meta.icon}
            label={t(meta.labelKey)}
            value={defaultModels[meta.type] ?? null}
            onChange={onChange}
            refreshKey={refreshKey}
          />
        ))}
      </div>
    </section>
  );
});
