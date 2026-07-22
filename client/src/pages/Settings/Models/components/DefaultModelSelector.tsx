import { useState, useEffect, useMemo } from "react";
import { Select, Spin } from "antd";
import { useTranslation } from "react-i18next";
import api from "@/api";
import type { DefaultModelSelectorProps } from "./types";

interface ModelByType {
  provider_id: string;
  provider_name: string;
  model_id: string;
  model_name: string;
  model_type: string;
  supports_image?: boolean;
  embedding_dimension?: number;
  is_free?: boolean;
}

/**
 * Default model selector component
 * Used in model management page to set default models for each type
 */
export function DefaultModelSelector({
  modelType,
  label,
  icon,
  value,
  onChange,
}: DefaultModelSelectorProps) {
  const { t } = useTranslation();
  const [models, setModels] = useState<ModelByType[]>([]);
  const [loading, setLoading] = useState(true);

  // Load models of this type
  useEffect(() => {
    setLoading(true);
    api
      .get(`/models/by-type/${modelType}`)
      .then((data: any) => {
        setModels(Array.isArray(data) ? data : []);
      })
      .catch((err) => {
        console.error(`Failed to load ${modelType} models:`, err);
        setModels([]);
      })
      .finally(() => {
        setLoading(false);
      });
  }, [modelType]);

  // Build grouped options
  const options = useMemo(() => {
    const grouped: Record<string, Array<{ value: string; label: string; model: ModelByType }>> = {};

    models.forEach((m) => {
      if (!grouped[m.provider_name]) {
        grouped[m.provider_name] = [];
      }
      grouped[m.provider_name].push({
        value: `${m.provider_id}:${m.model_id}`,
        label: m.model_name,
        model: m,
      });
    });

    return Object.entries(grouped).map(([providerName, models]) => ({
      label: providerName,
      options: models,
    }));
  }, [models]);

  const handleChange = (combinedValue: string | undefined) => {
    if (!combinedValue) {
      onChange(null as any);
      return;
    }
    const [providerId, modelId] = combinedValue.split(":");
    onChange({ providerId, modelId });
  };

  const currentValue = value
    ? `${value.providerId}:${value.modelId}`
    : undefined;

  return (
    <div className="default-model-selector">
      <label className="default-model-selector-label">
        {icon} {label}
      </label>
      <Spin spinning={loading}>
        <Select
          style={{ width: "100%" }}
          value={currentValue}
          onChange={handleChange}
          options={options}
          placeholder={t("models.selectDefaultModel")}
          allowClear
          showSearch
          optionFilterProp="label"
        />
      </Spin>
    </div>
  );
}
