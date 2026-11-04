import React, { useMemo, useState } from "react";
import { Space, Table, Input } from "antd";
import type { ColumnsType } from "antd/es/table";
import { StarFilled, SearchOutlined, ThunderboltOutlined } from "@ant-design/icons";
import { DEFAULT_MODEL_SLOTS } from "../modelSlots";
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

type ModelType =
  | "chat"
  | "embedding"
  | "rerank"
  | "audio"
  | "vision"
  | "decision";

// 槽位名单来自共享模块（与后端 VALID_DEFAULT_SLOTS 一一对应）：加第 6 个槽位
// 不需要在第四处重复字面量里再补一次。
const TYPE_ORDER: ModelType[] = DEFAULT_MODEL_SLOTS as ModelType[];

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
 * "Configured models" zone: a flat table of every model from *available*
 * providers only (configured with credentials + at least one model), so the
 * list shows genuinely usable models. Type filter tabs + search box sit in
 * one row above it, with counts matching the visible rows. Read-only for
 * model CRUD (that lives in the provider "manage models" modal); the only
 * action here is "set as default".
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

  // Only models from available providers (configured + has models) are
  // "usable". Models from unconfigured providers (e.g. built-in OpenAI/
  // Anthropic catalogs without an API key) are noise here — they can't be
  // selected, set as default, or used.
  const configuredProviders = useMemo(
    () =>
      providers.filter((p) => {
        const isConfigured =
          (p.is_custom && !!p.base_url) ||
          p.require_api_key === false ||
          (p.require_api_key && !!p.api_key);
        return isConfigured && (p.models?.length ?? 0) > 0;
      }),
    [providers],
  );

  const allRows: Row[] = useMemo(
    () =>
      configuredProviders.flatMap((p) =>
        (p.models ?? []).map((m) => ({
          key: `${p.id}:${m.id}`,
          provider: p,
          model: m,
        })),
      ),
    [configuredProviders],
  );

  const rows = useMemo(() => {
    let list = allRows;
    if (activeType === "decision") {
      // 决策槽位是"用途槽位"不是模型类型：候选 = 全部 chat 模型（判官要输出
      // JSON 判决，embedding/rerank 干不了），当前在岗的那条排最前。
      const onDuty = defaultModels.decision;
      list = list
        .filter((r) => (r.model.model_type || "chat") === "chat")
        .sort(
          (a, b) =>
            Number(
              !(
                onDuty &&
                b.provider.id === onDuty.providerId &&
                b.model.id === onDuty.modelId
              ),
            ) -
            Number(
              !(
                onDuty &&
                a.provider.id === onDuty.providerId &&
                a.model.id === onDuty.modelId
              ),
            ),
        );
    } else if (activeType) {
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
  }, [allRows, activeType, defaultModels, query]);

  const typeLabels: Record<string, string> = {
    chat: t("models.chatModels"),
    embedding: t("models.embeddingModels"),
    rerank: t("models.rerankModels"),
    audio: t("models.audioModels"),
    vision: t("models.visionModels"),
  decision: t("models.decisionModels"),
  };

  /** 这一行是否就是某个默认槽位里的模型（decision 槽位里放 chat 模型）。 */
  const isDefaultFor = (r: Row, slot: ModelType) => {
    const entry = defaultModels[slot];
    return (
      !!entry &&
      entry.providerId === r.provider.id &&
      entry.modelId === r.model.id
    );
  };

  /** 这一行的归属槽位 = 模型自己的类型（chat 行 = 对话默认槽位）。 */
  const owningSlot = (r: Row) => (r.model.model_type || "chat") as ModelType;

  const isDefault = (r: Row) => isDefaultFor(r, owningSlot(r));

  /** chat 模型可以兼任决策模型（判官跑的必须是 chat 能力的模型）。 */
  const isChatRow = (r: Row) => owningSlot(r) === "chat";

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
        const tags = [];
        if (isDefault(r)) {
          tags.push(
            <Tag key="own" style={{ color: "#faad14", borderColor: "#faad14" }}>
              <StarFilled style={{ marginRight: 4 }} />
              {typeLabels[type] ?? type}
            </Tag>,
          );
        }
        // 决策模型槽位：chat 模型可兼任，所以列表里要看得见谁在岗。
        if (isChatRow(r) && isDefaultFor(r, "decision")) {
          tags.push(
            <Tag
              key="decision"
              style={{ color: "#13c2c2", borderColor: "#13c2c2" }}
            >
              <ThunderboltOutlined style={{ marginRight: 4 }} />
              {t("models.decisionModels")}
            </Tag>,
          );
        }
        if (tags.length === 0) return null;
        return <Space size={4}>{tags}</Space>;
      },
    },
    {
      title: t("models.actions"),
      key: "actions",
      width: 230,
      render: (_, r) => {
        const slot = owningSlot(r);
        const already = isDefault(r);
        const judgeOn = isChatRow(r) && isDefaultFor(r, "decision");
        return (
          <Space size={4}>
            <Button
              size="small"
              type={already ? "default" : "primary"}
              disabled={already}
              onClick={() =>
                onSetDefault(slot, {
                  providerId: r.provider.id,
                  modelId: r.model.id,
                })
              }
            >
              {already ? t("models.alreadyDefault") : t("models.setAsDefault")}
            </Button>
            {isChatRow(r) && (
              // 决策模型（判官）= 模型管理里的第 6 个槽位，与其余槽位同权。
              <Button
                size="small"
                type={judgeOn ? "default" : "primary"}
                disabled={judgeOn}
                icon={<ThunderboltOutlined />}
                onClick={() =>
                  onSetDefault("decision", {
                    providerId: r.provider.id,
                    modelId: r.model.id,
                  })
                }
              >
                {judgeOn
                  ? t("models.alreadyDefault")
                  : t("models.setAsDecision")}
              </Button>
            )}
          </Space>
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
          providers={configuredProviders}
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
