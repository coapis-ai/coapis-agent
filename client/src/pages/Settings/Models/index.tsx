import { useCallback, useMemo, useState, useEffect } from "react";
import { Button, Input, message } from "antd";
import { PlusOutlined, SearchOutlined, SyncOutlined } from "@ant-design/icons";
import { useProviders } from "./useProviders";
import {
  LoadingState,
  ProviderCard,
  CustomProviderModal,
} from "./components";
import { DefaultModelSelector } from "./components/DefaultModelSelector";
import { ModelTypeTabs } from "./components/ModelTypeTabs";
import { PageHeader } from "@/components/PageHeader";
import { useTranslation } from "react-i18next";
import type { ProviderInfo } from "../../../api/types/provider";
import api from "@/api";
import styles from "./index.module.less";

/* ------------------------------------------------------------------ */
/* Main Page                                                           */
/* ------------------------------------------------------------------ */

function ModelsPage() {
  const { t } = useTranslation();
  const { providers, activeModels, loading, error, fetchAll } = useProviders();
  const [addProviderOpen, setAddProviderOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  
  // Model type filter
  const [modelTypeFilter, setModelTypeFilter] = useState<string | undefined>(undefined);
  
  // Default models configuration
  const [defaultModels, setDefaultModels] = useState<Record<string, { providerId: string; modelId: string } | null>>({});

  // Load default models
  useEffect(() => {
    api.get("/models/default-models").then((data: any) => {
      if (!data || typeof data !== 'object') {
        console.error('Invalid default models response:', data);
        return;
      }
      const models: Record<string, any> = {};
      Object.entries(data).forEach(([type, value]: [string, any]) => {
        if (value) {
          models[type] = {
            providerId: value.provider_id,
            modelId: value.model_id,
          };
        }
      });
      setDefaultModels(models);
    }).catch((err) => {
      console.error('Failed to load default models:', err);
    });
  }, []);

  const handleDefaultModelChange = async (
    type: string,
    value: { providerId: string; modelId: string } | null
  ) => {
    if (!value) return;

    try {
      await api.put("/models/default-models", {
        provider_id: value.providerId,
        model_id: value.modelId,
        model_type: type,
      });
      
      setDefaultModels((prev) => ({
        ...prev,
        [type]: value,
      }));
      
      message.success(t("models.defaultModelSaved"));
    } catch (err: any) {
      message.error(err.response?.data?.detail || t("common.saveFailed"));
    }
  };

  const refreshProvidersSilently = useCallback(() => {
    void fetchAll(false);
  }, [fetchAll]);

  const { sortedProviders } = useMemo(() => {
    // Sort providers: available first, then configured, then unconfigured.
    // Within each group, sort by name alphabetically.
    let sorted = [...providers].sort((a, b) => {
      let isConfiguredA = false;
      let isConfiguredB = false;
      
      if (a.is_custom && a.base_url) {
        isConfiguredA = true;
      } else if (a.require_api_key === false) {
        isConfiguredA = true;
      } else if (a.require_api_key && a.api_key) {
        isConfiguredA = true;
      }
      
      if (b.is_custom && b.base_url) {
        isConfiguredB = true;
      } else if (b.require_api_key === false) {
        isConfiguredB = true;
      } else if (b.require_api_key && b.api_key) {
        isConfiguredB = true;
      }

      const hasModelsA = a.models.length > 0;
      const hasModelsB = b.models.length > 0;
      const isAvailableA = isConfiguredA && hasModelsA;
      const isAvailableB = isConfiguredB && hasModelsB;

      // Priority: available (0) > configured (1) > unconfigured (2)
      const priorityA = isAvailableA ? 0 : isConfiguredA ? 1 : 2;
      const priorityB = isAvailableB ? 0 : isConfiguredB ? 1 : 2;
      
      // First sort by priority
      if (priorityA !== priorityB) {
        return priorityA - priorityB;
      }
      
      // Within same priority, sort by name alphabetically
      return a.name.localeCompare(b.name, undefined, { sensitivity: 'base' });
    });

    // Filter by model type
    if (modelTypeFilter) {
      sorted = sorted.filter((p) =>
        p.models.some((m: any) => (m.model_type || "chat") === modelTypeFilter)
      );
      
      // Filter models within providers
      sorted = sorted.map((p) => ({
        ...p,
        models: p.models.filter(
          (m: any) => (m.model_type || "chat") === modelTypeFilter
        ),
      })) as ProviderInfo[];
    }

    // Fuzzy search filter: match provider name (case-insensitive)
    const query = searchQuery.trim().toLowerCase();
    if (query) {
      sorted = sorted.filter((p) =>
        p.name.toLowerCase().includes(query)
      );
    }

    return { sortedProviders: sorted };
  }, [providers, searchQuery, modelTypeFilter]);

  const renderProviderCards = (list: ProviderInfo[]) =>
    list.map((provider) => (
      <ProviderCard
        key={provider.id}
        provider={provider}
        activeModels={activeModels}
        onSaved={refreshProvidersSilently}
      />
    ));

  return (
    <div className={styles.settingsPage}>
      {loading ? (
        <LoadingState message={t("models.loading")} />
      ) : error ? (
        <LoadingState message={error} error onRetry={fetchAll} />
      ) : (
        <>
          <PageHeader
            parent={t("nav.settings")}
            current={t("models.llmTitle")}
          />
          {/* ---- Scrollable Content ---- */}
          <div className={styles.content}>
            {/* ---- Default Models Section ---- */}
            <div className={styles.defaultModelsSection}>
              <PageHeader current={t("models.defaultModelsTitle")} />
              <div className={styles.defaultModelsGrid}>
                <DefaultModelSelector
                  modelType="chat"
                  label={t("models.chatModels")}
                  icon="💬"
                  value={defaultModels.chat}
                  onChange={(value) => handleDefaultModelChange("chat", value)}
                />
                <DefaultModelSelector
                  modelType="embedding"
                  label={t("models.embeddingModels")}
                  icon="🔢"
                  value={defaultModels.embedding}
                  onChange={(value) => handleDefaultModelChange("embedding", value)}
                />
                <DefaultModelSelector
                  modelType="rerank"
                  label={t("models.rerankModels")}
                  icon="🔄"
                  value={defaultModels.rerank}
                  onChange={(value) => handleDefaultModelChange("rerank", value)}
                />
                <DefaultModelSelector
                  modelType="audio"
                  label={t("models.audioModels")}
                  icon="🎵"
                  value={defaultModels.audio}
                  onChange={(value) => handleDefaultModelChange("audio", value)}
                />
                <DefaultModelSelector
                  modelType="vision"
                  label={t("models.visionModels")}
                  icon="👁"
                  value={defaultModels.vision}
                  onChange={(value) => handleDefaultModelChange("vision", value)}
                />
              </div>
            </div>
            
            {/* ---- Providers Section ---- */}
            <div className={styles.providersBlock}>
              <div className={styles.sectionHeaderRow}>
                <div className={styles.headerLeft}>
                  <PageHeader
                    current={t("models.providersTitle")}
                    className={styles.providersPageHeader}
                  />
                  {/* ---- Model Type Tabs ---- */}
                  <ModelTypeTabs
                    activeType={modelTypeFilter}
                    onChange={setModelTypeFilter}
                    providers={providers}
                  />
                </div>
                <div className={styles.headerRight}>
                  {/* ---- Search ---- */}
                  <div className={styles.searchRow}>
                    <Input
                      placeholder={t("models.searchPlaceholder")}
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      className={styles.searchInput}
                      prefix={<SearchOutlined />}
                      allowClear
                    />
                    <Button
                      icon={<SyncOutlined />}
                      onClick={() => fetchAll()}
                      className={styles.searchBtn}
                      title={t("common.refresh")}
                    />
                  </div>
                  <Button
                    type="primary"
                    icon={<PlusOutlined />}
                    onClick={() => setAddProviderOpen(true)}
                    className={styles.addProviderBtn}
                  >
                    {t("models.addProvider")}
                  </Button>
                </div>
              </div>

              {sortedProviders.length > 0 && (
                <div className={styles.providerGroup}>
                  <div className={styles.providerCards}>
                    {renderProviderCards(sortedProviders)}
                  </div>
                </div>
              )}
            </div>

            <CustomProviderModal
              open={addProviderOpen}
              onClose={() => setAddProviderOpen(false)}
              onSaved={fetchAll}
            />
          </div>
        </>
      )}
    </div>
  );
}

export default ModelsPage;
