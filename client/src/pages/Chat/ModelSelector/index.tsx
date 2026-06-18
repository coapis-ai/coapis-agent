import { useState, useEffect, useCallback, useRef } from "react";
import { Dropdown, Spin, Tooltip } from "antd";
import { useAppMessage } from "../../../hooks/useAppMessage";
import {
  CheckOutlined,
  LoadingOutlined,
  RightOutlined,
} from "@ant-design/icons";
import { SparkDownLine } from "@agentscope-ai/icons";
import { useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { providerApi } from "../../../api/modules/provider";
import { userModelPrefsApi } from "../../../api/modules/user_model_prefs";
import { useAgentStore } from "../../../stores/agentStore";
import { ProviderIcon } from "../../Settings/Models/components/ProviderIconComponent";
import styles from "./index.module.less";

/**
 * Available model from the global pool or user's custom providers
 */
interface AvailableModel {
  provider_id: string;
  provider_name: string;
  model_id: string;
  model_name: string;
  is_free?: boolean;
  source: 'global' | 'custom';
}

export default function ModelSelector() {
  const { t } = useTranslation();
  const [availableModels, setAvailableModels] = useState<AvailableModel[]>([]);
  const [activeModels, setActiveModels] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [open, setOpen] = useState(false);
  const savingRef = useRef(false);
  const location = useLocation();
  const { selectedAgent } = useAgentStore();
  const { message } = useAppMessage();

  // Fetch available models (global pool + custom providers)
  const fetchAvailableModels = useCallback(async () => {
    setLoading(true);
    try {
      const data = await userModelPrefsApi.getAvailableModels();
      const models: AvailableModel[] = [];

      // Global models
      for (const m of (data.global_models || [])) {
        models.push({
          provider_id: m.provider_id || 'local_llm',
          provider_name: m.provider_name || 'Local LLM',
          model_id: m.id || m,
          model_name: m.name || m.id || m,
          source: 'global',
        });
      }

      // Custom provider models
      for (const cp of (data.custom_providers || [])) {
        if (!cp.enabled) continue;
        for (const m of (cp.models || [])) {
          models.push({
            provider_id: cp.id,
            provider_name: cp.name,
            model_id: m.id || m,
            model_name: m.name || m.id || m,
            source: 'custom',
          });
        }
      }

      setAvailableModels(models);
    } catch (err) {
      console.error("ModelSelector: failed to load available models", err);
    } finally {
      setLoading(false);
    }
  }, []);

  // Fetch active model for current agent
  const fetchActiveModel = useCallback(async () => {
    try {
      const activeData = await providerApi.getActiveModels({
        scope: "effective",
        agent_id: selectedAgent,
      });
      if (activeData) setActiveModels(activeData);
    } catch {
      // ignore
    }
  }, [selectedAgent]);

  useEffect(() => {
    fetchAvailableModels();
    fetchActiveModel();
  }, [fetchAvailableModels, fetchActiveModel]);

  // Re-sync active model whenever the route switches back to /chat
  const prevPathRef = useRef(location.pathname);
  useEffect(() => {
    const prev = prevPathRef.current;
    const curr = location.pathname;
    prevPathRef.current = curr;
    const comingToChat = curr.startsWith("/chat") && !prev.startsWith("/chat");
    if (comingToChat) {
      fetchActiveModel();
    }
  }, [location.pathname, fetchActiveModel]);

  // Group models by provider
  const groupedModels = availableModels.reduce((acc, model) => {
    const key = model.provider_id;
    if (!acc[key]) {
      acc[key] = {
        provider_id: model.provider_id,
        provider_name: model.provider_name,
        source: model.source,
        models: [],
      };
    }
    acc[key].models.push(model);
    return acc;
  }, {} as Record<string, { provider_id: string; provider_name: string; source: string; models: AvailableModel[] }>);

  const activeProviderId = activeModels?.active_llm?.provider_id;
  const activeModelId = activeModels?.active_llm?.model;

  // Display label for trigger button
  const activeModelName = (() => {
    if (!activeProviderId || !activeModelId)
      return t("modelSelector.selectModel");
    for (const group of Object.values(groupedModels)) {
      if (group.provider_id === activeProviderId) {
        const m = group.models.find((m) => m.model_id === activeModelId);
        if (m) return m.model_name || m.model_id;
      }
    }
    return activeModelId;
  })();

  const showActiveProviderIcon = Boolean(activeProviderId);

  const handleOpenChange = useCallback(
    async (next: boolean) => {
      setOpen(next);
      if (next) {
        // Re-fetch available models when dropdown opens to ensure fresh data
        fetchAvailableModels();
        fetchActiveModel();
      }
    },
    [fetchAvailableModels, fetchActiveModel],
  );

  const handleSelect = async (providerId: string, modelId: string) => {
    if (savingRef.current) return;
    if (providerId === activeProviderId && modelId === activeModelId) {
      setOpen(false);
      return;
    }

    setOpen(false);

    savingRef.current = true;
    setSaving(true);
    try {
      await providerApi.setActiveLlm({
        provider_id: providerId,
        model: modelId,
        scope: "agent",
        agent_id: selectedAgent,
      });
      setActiveModels({
        active_llm: { provider_id: providerId, model: modelId },
      });
      window.dispatchEvent(new CustomEvent("model-switched"));
    } catch (err) {
      const msg =
        err instanceof Error ? err.message : t("modelSelector.switchFailed");
      message.error(msg);
    } finally {
      setSaving(false);
      savingRef.current = false;
    }
  };

  const dropdownContent = (
    <div className={styles.panel}>
      {loading ? (
        <div className={styles.spinWrapper}>
          <Spin size="small" />
        </div>
      ) : availableModels.length === 0 ? (
        <div className={styles.emptyTip}>
          {t("modelSelector.noConfiguredModels")}
        </div>
      ) : (
        Object.values(groupedModels).map((group) => {
          const isProviderActive = group.provider_id === activeProviderId;
          return (
            <div
              key={group.provider_id}
              className={[
                styles.providerItem,
                isProviderActive ? styles.providerItemActive : "",
              ].join(" ")}
            >
              <ProviderIcon providerId={group.provider_id} size={20} />
              <span className={styles.providerName}>{group.provider_name}</span>
              <RightOutlined className={styles.providerArrow} />

              {/* Level-2 submenu */}
              <div className={`${styles.submenu} modelSubmenu`}>
                {group.models.map((model) => {
                  const isActive =
                    isProviderActive && model.model_id === activeModelId;
                  return (
                    <div
                      key={model.model_id}
                      className={[
                        styles.modelItem,
                        isActive ? styles.modelItemActive : "",
                      ].join(" ")}
                      onClick={(e) => {
                        e.stopPropagation();
                        handleSelect(group.provider_id, model.model_id);
                      }}
                    >
                      <span className={styles.modelName}>
                        {model.model_name || model.model_id}
                      </span>
                      {isActive && (
                        <CheckOutlined className={styles.checkIcon} />
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })
      )}
    </div>
  );

  return (
    <Dropdown
      open={open}
      onOpenChange={handleOpenChange}
      dropdownRender={() => dropdownContent}
      trigger={["click"]}
      placement="bottomLeft"
    >
      <Tooltip title={t("chat.modelSelectTooltip")} mouseEnterDelay={0.5}>
        <div
          className={[styles.trigger, open ? styles.triggerActive : ""].join(
            " ",
          )}
        >
          {saving && (
            <LoadingOutlined style={{ fontSize: 11, color: "#FF7F16" }} />
          )}
          {showActiveProviderIcon && activeProviderId && (
            <ProviderIcon providerId={activeProviderId} size={16} />
          )}
          <span className={styles.triggerName}>{activeModelName}</span>
          <SparkDownLine
            className={[
              styles.triggerArrow,
              open ? styles.triggerArrowOpen : "",
            ].join(" ")}
          />
        </div>
      </Tooltip>
    </Dropdown>
  );
}
