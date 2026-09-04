import React, { useMemo, useState } from "react";
import { Table, Input } from "antd";
import type { ColumnsType } from "antd/es/table";
import { StarFilled, SearchOutlined } from "@ant-design/icons";
import { Button, Tag } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import type { ProviderInfo, ModelInfo } from "@/api/types";
import { ModelTypeTabs } from "../ModelTypeTabs";
import { CapabilityTags, tagColors } from "../CapabilityTags";
import { useTheme } from "@/contexts/ThemeContext";
import styles from "../../index.module.less";

interface Row {
  key: string;
  provider: ProviderInfo;
  model: ModelInfo;
}

type ModelType = "chat" | "embedding" | "rerank" | "audio" | "vision";

const TYPE_ORDER: ModelType[] = ["chat", "embedding", "rerank", "audio", "vision"];

const typeTagColors: Record<string, string> = {
  chat: "blue",
  embedding: "green",
  rerank: "orange",
  audio: "purple",
  vision: "cyan",
};

interface ConfiguredModelsSectionProps {
  providers: ProviderInfo[];
  defaultModels: Record<string, { providerId: string; modelId: string }>;
  onSetDefault: (
    modelType: ModelType,
    value: { providerId: string; modelId: string },
  ) => void;
}

/**
 * "Configured models" zone: a flat table of every model across all
 * providers, with the type filter tabs + search box tightly coupled in
 * one row above it. Read-only for model CRUD (that lives in the provider
 * "manage models" modal); the only action here is "set as default".
 */
export const ConfiguredModelsSection = React.memo(function ConfiguredModelsSection({
  providers,
  defaultModels,
  onSetDefault,
}: ConfiguredModelsSectionProps) {
  const { t } = useTranslation();
  const { isDark } = useTheme();
  const [activeType, setActiveType] = useState<string | undefined>(undefined);
  const [query, setQuery] = useState("");

  const allRows: Row[] = useMemo(
    () =>
      providers.flatMap((p) =>
        (p.models ?? []).map((m) => ({
          key: `${p.id}:${m.id}`,
          provider: p,
          model: m,
        })),
      ),
    [providers],
  );

  const rows = useMemo(() => {
    let list = allRows;
    if (activeType) {
      list = list.filter((r) => (r.model.model_type || "chat") === activeType);
    }
    const q = query.trim().toLowerCase();
    if (q) {
      list = list.filter(
        (r) =>
          r.model.name.toLowerCase().includes(q) ||
          r.model.id.toLowerCase().includes(q) ||
          r.provider.name.toLowerCase().includes(q),
      );
    }
    return [...list].sort(
      (a, b) => {
        const ta = TYPE_ORDER.indexOf((a.model.model_type || "chat") as ModelType);
        const tb = TYPE_ORDER.indexOf((b.model.model_type || "chat") as ModelType);
        if (ta !== tb) return ta - tb;
        if (a.provider.name !== b.provider.name)
          return a.provider.name.localeCompare(b.provider.name);
        return a.model.name.localeCompare(b.model.name);
      },
    );
  }, [allRows, activeType, query]);

  const typeLabels: Record<string, string> = {
    chat: t("models.chatModels"),
    embedding: t("models.embeddingModels"),
    rerank: t("models.rerankModels"),
    audio: t("models.audioModels"),
    vision: t("models.visionModels"),
  };

  const isDefault = (r: Row) => {
    const type = (r.model.model_type || "chat") as string;
    const slot = defaultModels[type];
    return (
      !!slot && slot.providerId === r.provider.id && slot.modelId === r.model.id
    );
  };

  const columns: ColumnsType<Row> = [
    {
      title: t("models.modelNameCol"),
      dataIndex: ["model", "name"],
      key: "model",
      render: (_, r) => (
        <div>
          <div style={{ fontWeight: 500 }}>{r.model.name}</div>
          <div
            style={{
              fontSize: 12,
              color: isDark ? "rgba(255,255,255,0.45)" : "#8c8c8c",
            }}
          >
            {r.model.id}
          </div>
        </div>
      ),
    },
    {
      title: t("models.providerCol"),
      dataIndex: ["provider", "name"],
      key: "provider",
      width: 140,
    },
    {
      title: t("models.typeCol"),
      key: "type",
      width: 110,
      render: (_, r) => {
        const type = r.model.model_type || "chat";
        return (
          <Tag color={typeTagColors[type] ?? "default"}>
            {typeLabels[type] ?? type}
          </Tag>
        );
      },
    },
    {
      title: t("models.capabilityCol"),
      key: "capability",
      width: 110,
      render: (_, r) => <CapabilityTags model={r.model} isDark={isDark} />,
    },
    {
      title: t("models.freeCol"),
      key: "free",
      width: 60,
      align: "center",
      render: (_, r) =>
        r.model.is_free ? (
          <Tag style={tagColors(isDark).free}>{t("models.free")}</Tag>
        ) : (
          <span style={{ color: isDark ? "rgba(255,255,255,0.3)" : "#bfbfbf" }}>
            —
          </span>
        ),
    },
    {
      title: t("models.defaultCol"),
      key: "default",
      width: 110,
      render: (_, r) => {
        if (!isDefault(r)) return null;
        const type = r.model.model_type || "chat";
        return (
          <Tag style={{ color: "#faad14", borderColor: "#faad14" }}>
            <StarFilled style={{ marginRight: 4 }} />
            {typeLabels[type] ?? type}
          </Tag>
        );
      },
    },
    {
      title: t("models.actions"),
      key: "actions",
      width: 120,
      render: (_, r) => {
        const already = isDefault(r);
        return (
          <Button
            size="small"
            type={already ? "default" : "primary"}
            disabled={already}
            onClick={() =>
              onSetDefault(
                (r.model.model_type || "chat") as ModelType,
                {
                  providerId: r.provider.id,
                  modelId: r.model.id,
                },
              )
            }
          >
            {already ? t("models.alreadyDefault") : t("models.setAsDefault")}
          </Button>
        );
      },
    },
  ];

  return (
    <section>
      <h2 className={styles.sectionTitle}>
        {t("models.configuredModelsTitle")}
      </h2>
      <p className={styles.sectionDesc}>
        {t("models.configuredModelsDesc")}
      </p>

      {/* Filter row: type tabs + search, tightly coupled above the table */}
      <div className={styles.configuredFilterRow}>
        <ModelTypeTabs
          activeType={activeType}
          onChange={setActiveType}
          providers={providers}
        />
        <Input
          size="small"
          allowClear
          prefix={<SearchOutlined />}
          placeholder={t("models.searchModelPlaceholder")}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          style={{ width: 220 }}
        />
      </div>

      <Table<Row>
        size="small"
        rowKey="key"
        columns={columns}
        dataSource={rows}
        pagination={false}
        locale={{ emptyText: t("models.noConfiguredModels") }}
      />
    </section>
  );
});
