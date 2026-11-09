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
import type { DefaultSlot } from "./components/modelSlots";
import styles from "./index.module.less";

// 槽位名单的单一来源在前端共享模块（与后端 VALID_DEFAULT_SLOTS 一一对应）。
// 页面自己再写一份五项字面量 = 后端加 decision 槽位时页面永远看不见（v16 问题 2）。
type ModelType = DefaultSlot;

const ModelsPage: React.FC = () => {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { providers, activeModels, loading, error, fetchAll } = useProviders();

  const [defaultModels, setDefaultModels] = useState<
    Record<string, { providerId: string; modelId: string }>
  >({});

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
      // 空 model_id = 清空槽位：本地状态要跟着删掉这一项，否则乐观更新
      // 会留下 "provider /" 这种半条命显示（判官槽位尤其要看得到"已下岗"）。
      setDefaultModels((prev) => {
        const next = { ...prev };
        if (!value.modelId) {
          delete next[modelType];
        } else {
          next[modelType] = value;
        }
        return next;
      });
      message.success(
        value.modelId ? t("models.defaultModelSaved") : t("models.defaultModelCleared"),
      );
    } catch (error) {
      console.error("Failed to set default model:", error);
      // 2026-11-09 拍板 D2/F4：后端的校验结论（如"该提供商没有 API Key"）
      // 必须原样显示。之前一律压成"保存失败"，小蜜蜂看不到为什么不能存。
      message.error(
        error instanceof Error && error.message
          ? error.message
          : t("models.failedToSave"),
      );
    }
  };

  const handleDefaultModelChange = (
    type: ModelType,
    value: { providerId: string; modelId: string } | null,
  ) => {
    // 之前这里是 `if (!value) return;`：下拉框的 allowClear 清空后前端
    // 什么都不做，槽位永远只能设不能清（判官上了岗就下不来）。
    if (!value) {
      setDefaultModel(type, { providerId: "", modelId: "" });
      return;
    }
    setDefaultModel(type, value);
  };

  const handleSaved = useCallback(async () => {
    await fetchAll(false);
  }, [fetchAll]);

  const handleAddProviderSuccess = useCallback(async () => {
    setShowAddProviderModal(false);
    await fetchAll(false);
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
          {/* Zone 1: default model bar (read-only, above everything) */}
          <DefaultModelBar
            defaultModels={defaultModels}
            providers={providers}
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
