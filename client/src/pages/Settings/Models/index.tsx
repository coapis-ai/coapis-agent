import React, { useCallback, useEffect, useState } from "react";
import { Empty, Button } from "@agentscope-ai/design";
import { PageHeader } from "@/components/PageHeader";
import { PlusOutlined, SearchOutlined } from "@ant-design/icons";
import { Input } from "antd";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "@/hooks/useAppMessage";
import api from "@/api";
import { useProviders } from "./useProviders";
import {
  DefaultModelBar,
  ConfiguredModelsSection,
  ProviderCard,
  CustomProviderModal,
} from "./components";
import styles from "./index.module.less";

type ModelType = "chat" | "embedding" | "rerank" | "audio" | "vision";

const ModelsPage: React.FC = () => {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { providers, activeModels, loading, error, fetchAll } = useProviders();

  const [defaultModels, setDefaultModels] = useState<
    Record<string, { providerId: string; modelId: string }>
  >({});

  const [refreshDefaultModelKey, setRefreshDefaultModelKey] = useState(0);
  const [showAddProviderModal, setShowAddProviderModal] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  // Load default models on mount
  useEffect(() => {
    loadDefaultModels();
  }, []);

  const loadDefaultModels = async () => {
    try {
      const data = await api.get("/models/default-models");
      if (data && typeof data === "object") {
        // API returns snake_case (provider_id / model_id); components expect
        // camelCase, so normalize here instead of casting blindly.
        const normalized: Record<string, {
          providerId: string;
          modelId: string;
        }> = {};
        for (const [type, raw] of Object.entries(data as Record<string, any>)) {
          if (raw && typeof raw === "object" && (raw.provider_id || raw.providerId)) {
            normalized[type] = {
              providerId: raw.providerId ?? raw.provider_id,
              modelId: raw.modelId ?? raw.model_id,
            };
          }
        }
        setDefaultModels(normalized);
      }
    } catch (error) {
      console.error("Failed to load default models:", error);
    }
  };

  const setDefaultModel = async (
    modelType: ModelType,
    value: { providerId: string; modelId: string },
  ) => {
    try {
      await api.put("/models/default-models", {
        provider_id: value.providerId,
        model_id: value.modelId,
        model_type: modelType,
      });
      setDefaultModels((prev) => ({ ...prev, [modelType]: value }));
      message.success(t("models.defaultModelSaved"));
    } catch (error) {
      console.error("Failed to set default model:", error);
      message.error(t("models.failedToSave"));
    }
  };

  const handleDefaultModelChange = (
    type: ModelType,
    value: { providerId: string; modelId: string } | null,
  ) => {
    if (!value) return;
    setDefaultModel(type, value);
  };

  const handleSaved = useCallback(async () => {
    await fetchAll(false);
    setRefreshDefaultModelKey((k) => k + 1);
  }, [fetchAll]);

  const handleAddProviderSuccess = useCallback(async () => {
    setShowAddProviderModal(false);
    await fetchAll(false);
    setRefreshDefaultModelKey((k) => k + 1);
  }, [fetchAll]);

  const filteredProviders = providers.filter((p) => {
    if (!searchQuery) return true;
    return p.name
      .toLowerCase()
      .includes(searchQuery.toLowerCase());
  });

  const isConfigured = (p: (typeof providers)[number]) => {
    if (p.is_custom && p.base_url) return true;
    if (p.require_api_key === false) return true;
    if (p.require_api_key && p.api_key) return true;
    return false;
  };

  const availableProviders = filteredProviders.filter(
    (p) => isConfigured(p) && p.models.length > 0,
  );
  const unreadyProviders = filteredProviders.filter(
    (p) => !(isConfigured(p) && p.models.length > 0),
  );

  return (
    <div className={styles.modelsPage}>
      <PageHeader
        parent={t("nav.settings")}
        current={t("models.llmTitle")}
      />

      {loading ? (
        <div className={styles.loading}>
          <span className={styles.loadingText}>{t("models.loading")}</span>
        </div>
      ) : error ? (
        <div className={styles.error}>
          <p>{t("models.loadError")}: {error}</p>
          <Button onClick={() => fetchAll()}>{t("models.retry")}</Button>
        </div>
      ) : (
        <>
          {/* Zone 1: default model bar (independent, above everything) */}
          <DefaultModelBar
            defaultModels={defaultModels}
            onChange={handleDefaultModelChange}
            refreshKey={refreshDefaultModelKey}
          />

          {/* Zone 2: configured models — type filter + table, tightly coupled */}
          <ConfiguredModelsSection
            providers={providers}
            defaultModels={defaultModels}
            onSetDefault={handleDefaultModelChange}
          />

          {/* Zone 3: provider management — compact cards, grouped by readiness */}
          <section>
            <div className={styles.providersHeaderRow}>
              <div>
                <h2 className={styles.sectionTitle}>
                  {t("models.providersTitle")}
                </h2>
                <p className={styles.sectionDesc}>
                  {t("models.providersDescription")}
                </p>
              </div>
              <div className={styles.providersHeaderActions}>
                <Input
                  size="small"
                  prefix={<SearchOutlined />}
                  placeholder={t("models.searchPlaceholder")}
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  allowClear
                  style={{ width: 200 }}
                />
                <Button
                  type="primary"
                  size="small"
                  icon={<PlusOutlined />}
                  onClick={() => setShowAddProviderModal(true)}
                >
                  {t("models.addProvider")}
                </Button>
              </div>
            </div>

            {filteredProviders.length === 0 ? (
              <Empty description={t("models.noProviders")} />
            ) : (
              <>
                {availableProviders.length > 0 && (
                  <div className={styles.providerGroup}>
                    <div className={styles.providerGroupHeader}>
                      <span className={styles.providerGroupDotReady} />
                      <span className={styles.providerGroupTitle}>
                        {t("models.availableProviders")}
                      </span>
                      <span className={styles.providerGroupCount}>
                        {availableProviders.length}
                      </span>
                    </div>
                    <div className={styles.providerCards}>
                      {availableProviders.map((provider) => (
                        <ProviderCard
                          key={provider.id}
                          provider={provider}
                          activeModels={activeModels}
                          onSaved={handleSaved}
                        />
                      ))}
                    </div>
                  </div>
                )}
                {unreadyProviders.length > 0 && (
                  <div className={styles.providerGroup}>
                    <div className={styles.providerGroupHeader}>
                      <span className={styles.providerGroupDot} />
                      <span className={styles.providerGroupTitle}>
                        {t("models.unreadyProviders")}
                      </span>
                      <span className={styles.providerGroupCount}>
                        {unreadyProviders.length}
                      </span>
                    </div>
                    <div className={styles.providerCards}>
                      {unreadyProviders.map((provider) => (
                        <ProviderCard
                          key={provider.id}
                          provider={provider}
                          activeModels={activeModels}
                          onSaved={handleSaved}
                        />
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </section>
        </>
      )}

      <CustomProviderModal
        open={showAddProviderModal}
        onClose={() => setShowAddProviderModal(false)}
        onSaved={handleAddProviderSuccess}
      />
    </div>
  );
};

export default ModelsPage;
