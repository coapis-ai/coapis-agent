import { useState, useEffect, useMemo, useCallback } from "react";
import {
  Button,
  Form,
  Input,
  Modal,
  Tag,
  Tooltip,
  Select,
} from "@agentscope-ai/design";
import { AutoComplete } from "antd";
import {
  DeleteOutlined,
  PlusOutlined,
  ApiOutlined,
  EyeOutlined,
  SettingOutlined,
  DownOutlined,
  SearchOutlined,
  ExperimentOutlined,
  AppstoreOutlined,
  VideoCameraOutlined,
  FileTextOutlined,
  QuestionCircleOutlined,
  DatabaseOutlined,
  UserOutlined,
  GiftOutlined,
  StarFilled,
} from "@ant-design/icons";
import type {
  ProviderInfo,
  SeriesResponse,
  ModelInfo,
  ExtendedModelInfo,
} from "../../../../../api/types";

import api from "../../../../../api";
import { useTranslation } from "react-i18next";
import { useTheme } from "../../../../../contexts/ThemeContext";
import { useAppMessage } from "../../../../../hooks/useAppMessage";
import { JsonConfigEditor } from "./JsonConfigEditor.tsx";
import {
  getLocalizedTestConnectionMessage,
  getTestConnectionFailureDetail,
} from "./testConnectionMessage";
import { OpenRouterFilterSection } from "./OpenRouterFilterSection";
import { ModelTypeTabs } from "../ModelTypeTabs";
import styles from "../../index.module.less";

const typeOrder: Array<"chat" | "embedding" | "rerank" | "audio" | "vision"> = [
  "chat",
  "embedding",
  "rerank",
  "audio",
  "vision",
];

/**
 * Frontend mirror of the backend inference rules
 * (server/coapis/providers/model_type.py). Used only for the "auto-infer"
 * preview hint in the add-model form.
 */
function inferModelType(modelId: string, modelName = ""): string {
  const haystack = `${modelId} ${modelName}`.trim().toLowerCase();
  if (!haystack) return "chat";
  if (haystack.includes("rerank")) return "rerank";
  if (["embed", "bge", "e5-"].some((k) => haystack.includes(k)))
    return "embedding";
  if (
      ["whisper", "asr", "tts", "speech", "speak"].some((k) =>
        haystack.includes(k),
      )
    )
    return "audio";
  if (
    ["vision", "omni", "llava", "clip", "-vl", "_vl", "vl-"].some((k) =>
      haystack.includes(k),
    ) ||
    haystack.endsWith("vl")
  )
    return "vision";
  return "chat";
}

function ModelConfigEditor({
  providerId,
  model,
  onSaved,
  onClose,
  isDark,
}: {
  providerId: string;
  model: ModelInfo;
  onSaved: () => void | Promise<void>;
  onClose: () => void;
  isDark: boolean;
}) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [saving, setSaving] = useState(false);

  const initialText = useMemo(
    () =>
      model.generate_kwargs && Object.keys(model.generate_kwargs).length > 0
        ? JSON.stringify(model.generate_kwargs, null, 2)
        : "",
    [model.generate_kwargs],
  );

  const [text, setText] = useState(initialText);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    setText(initialText);
    setDirty(false);
  }, [initialText]);

  const handleChange = useCallback(
    (val: string) => {
      setText(val);
      setDirty(val !== initialText);
    },
    [initialText],
  );

  const handleSave = async () => {
    const trimmed = text.trim();
    let parsed: Record<string, unknown> = {};
    if (trimmed) {
      try {
        const obj = JSON.parse(trimmed);
        if (!obj || typeof obj !== "object" || Array.isArray(obj)) {
          message.error(t("models.generateConfigMustBeObject"));
          return;
        }
        parsed = obj;
      } catch {
        message.error(t("models.generateConfigInvalidJson"));
        return;
      }
    }

    setSaving(true);
    try {
      await api.configureModel(providerId, model.id, {
        generate_kwargs: parsed,
      });
      message.success(t("models.modelConfigSaved", { name: model.name }));
      setDirty(false);
      await onSaved();
      onClose();
    } catch (error) {
      const errMsg =
        error instanceof Error
          ? error.message
          : t("models.modelConfigSaveFailed");
      message.error(errMsg);
    } finally {
      setSaving(false);
    }
  };

  const typeLabelKey: Record<string, string> = {
    chat: "models.chatModels",
    embedding: "models.embeddingModels",
    rerank: "models.rerankModels",
    audio: "models.audioModels",
    vision: "models.visionModels",
  };

  return (
    <div style={{ padding: "8px 0 4px" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          fontSize: 12,
          color: isDark ? "rgba(255,255,255,0.45)" : "#888",
          marginBottom: 4,
        }}
      >
        {t("models.modelGenerateConfigHint")}
        <Tag
          style={{
            fontSize: 11,
            margin: 0,
            lineHeight: "18px",
            backgroundColor: isDark ? "rgba(24,144,255,0.15)" : "#e6f7ff",
            color: isDark ? "#69b1ff" : "#1890ff",
            borderColor: isDark ? "rgba(24,144,255,0.3)" : "#91d5ff",
          }}
        >
          {t(
            typeLabelKey[model.model_type || "chat"] ?? "models.chatModels",
          )}
        </Tag>
      </div>
      <JsonConfigEditor
        value={text}
        onChange={handleChange}
        placeholder={`Example:\n{\n  "extra_body": {\n    "enable_thinking": false\n  },\n  "max_tokens": 2048\n}`}
      />
      <div
        style={{
          display: "flex",
          justifyContent: "flex-end",
          marginTop: 8,
          gap: 8,
        }}
      >
        <Button
          type="primary"
          size="small"
          loading={saving}
          disabled={!dirty}
          onClick={handleSave}
        >
          {t("models.save")}
        </Button>
      </div>
    </div>
  );
}

const tagColors = (isDark: boolean) => ({
  multimodal: {
    backgroundColor: isDark ? "rgba(24,144,255,0.15)" : "#e6f7ff",
    color: "#1890ff",
    borderColor: isDark ? "rgba(24,144,255,0.3)" : "#91d5ff",
  },
  vision: {
    backgroundColor: isDark ? "rgba(19,194,194,0.15)" : "#e6fffb",
    color: "#13c2c2",
    borderColor: isDark ? "rgba(19,194,194,0.3)" : "#87e8de",
  },
  video: {
    backgroundColor: isDark ? "rgba(114,46,211,0.15)" : "#f9f0ff",
    color: "#722ed1",
    borderColor: isDark ? "rgba(114,46,211,0.3)" : "#d3adf7",
  },
  text: {
    backgroundColor: isDark ? "rgba(255,255,255,0.1)" : "#f5f5f5",
    color: isDark ? "rgba(255,255,255,0.65)" : "#595959",
    borderColor: isDark ? "rgba(255,255,255,0.15)" : "#d9d9d9",
  },
  notProbed: {
    backgroundColor: isDark ? "rgba(255,255,255,0.1)" : "#f5f5f5",
    color: isDark ? "rgba(255,255,255,0.65)" : "#8c8c8c",
    borderColor: isDark ? "rgba(255,255,255,0.15)" : "#d9d9d9",
  },
  builtin: {
    backgroundColor: isDark ? "rgba(82,196,26,0.15)" : "#f6ffed",
    color: "#52c41a",
    borderColor: isDark ? "rgba(82,196,26,0.3)" : "#b7eb8f",
  },
  free: {
    backgroundColor: isDark ? "rgba(82,196,26,0.15)" : "#f6ffed",
    color: "#52c41a",
    borderColor: isDark ? "rgba(82,196,26,0.3)" : "#b7eb8f",
  },
  userAdded: {
    backgroundColor: isDark ? "rgba(24,144,255,0.15)" : "#e6f7ff",
    color: "#1890ff",
    borderColor: isDark ? "rgba(24,144,255,0.3)" : "#91d5ff",
  },
  default: {
    backgroundColor: isDark ? "rgba(250,173,20,0.15)" : "#fffbe6",
    color: "#faad14",
    borderColor: isDark ? "rgba(250,173,20,0.3)" : "#ffe58f",
  },
});

interface RemoteModelManageModalProps {
  provider: ProviderInfo;
  open: boolean;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}

function CapabilityTags({
  model,
  isDark,
}: {
  model: ModelInfo;
  isDark: boolean;
}) {
  const { t } = useTranslation();
  const c = tagColors(isDark);
  if (model.supports_image && model.supports_video) {
    return (
      <Tag style={{ fontSize: 11, marginRight: 4, ...c.multimodal }}>
        <AppstoreOutlined style={{ fontSize: 10, marginRight: 3 }} />
        {t("models.tagMultimodal", "多模态")}
      </Tag>
    );
  }
  if (model.supports_image) {
    return (
      <Tag style={{ fontSize: 11, marginRight: 4, ...c.vision }}>
        <EyeOutlined style={{ fontSize: 10, marginRight: 3 }} />
        {t("models.tagVision", "视觉")}
      </Tag>
    );
  }
  if (model.supports_video) {
    return (
      <Tag style={{ fontSize: 11, marginRight: 4, ...c.video }}>
        <VideoCameraOutlined style={{ fontSize: 10, marginRight: 3 }} />
        {t("models.tagVideo", "视频")}
      </Tag>
    );
  }
  if (model.supports_multimodal === false) {
    return (
      <Tag style={{ fontSize: 11, marginRight: 4, ...c.text }}>
        <FileTextOutlined style={{ fontSize: 10, marginRight: 3 }} />
        {t("models.tagText", "文本")}
      </Tag>
    );
  }
  return (
    <Tag style={{ fontSize: 11, marginRight: 4, ...c.notProbed }}>
      <QuestionCircleOutlined style={{ fontSize: 10, marginRight: 3 }} />
      {t("models.tagNotProbed", "未检测")}
    </Tag>
  );
}

export function RemoteModelManageModal({
  provider,
  open,
  onClose,
  onSaved,
}: RemoteModelManageModalProps) {
  const { t } = useTranslation();
  const { isDark } = useTheme();
  const darkBtnStyle = isDark ? { color: "rgba(255,255,255,0.65)" } : undefined;
  const { message } = useAppMessage();
  const supportsAutoDiscover = provider.support_model_discovery;
  const [adding, setAdding] = useState(false);
  const [saving, setSaving] = useState(false);
  const [discoveringModels, setDiscoveringModels] = useState(false);
  const [testingModelId, setTestingModelId] = useState<string | null>(null);
  const [probingModelId, setProbingModelId] = useState<string | null>(null);
  const [configOpenModelId, setConfigOpenModelId] = useState<string | null>(
    null,
  );
  const [modelSearchQuery, setModelSearchQuery] = useState("");
  const [modelTypeFilter, setModelTypeFilter] = useState("");
  const [typeUpdatingId, setTypeUpdatingId] = useState<string | null>(null);
  const [defaultModels, setDefaultModels] = useState<
    Record<string, { provider_id: string; model_id: string }>
  >({});
  const [form] = Form.useForm();
  const watchedModelId = Form.useWatch("id", form);
  const watchedModelType = Form.useWatch("model_type", form);
  // OpenRouter filter state
  const isOpenRouter = provider.id === "openrouter";
  const [showFilters, setShowFilters] = useState(false);
  const [availableSeries, setAvailableSeries] = useState<string[]>([]);
  const [discoveredModels, setDiscoveredModels] = useState<ExtendedModelInfo[]>(
    [],
  );
  const [selectedSeries, setSelectedSeries] = useState<string[]>([]);
  const [selectedInputModalities, setSelectedInputModalities] = useState<
    string[]
  >([]);
  const [showFreeOnly, setShowFreeOnly] = useState(false);
  const [loadingFilters, setLoadingFilters] = useState(false);

  const [loadingDiscoveredModels, setLoadingDiscoveredModels] = useState(false);

  const modelTypeOptions = useMemo(
    () => [
      { value: "chat", label: t("models.chatModels") },
      { value: "embedding", label: t("models.embeddingModels") },
      { value: "rerank", label: t("models.rerankModels") },
      { value: "audio", label: t("models.audioModels") },
      { value: "vision", label: t("models.visionModels") },
    ],
    [t],
  );

  const typeLabel = (type: string) =>
    modelTypeOptions.find((o) => o.value === type)?.label ?? type;

  // Load default models so rows can show a "default" marker.
  useEffect(() => {
    if (!open) return;
    api
      .get("/models/default-models")
      .then((data: unknown) => {
        if (data && typeof data === "object") {
          setDefaultModels(
            data as Record<string, { provider_id: string; model_id: string }>,
          );
        }
      })
      .catch(() => setDefaultModels({}));
  }, [open]);

  const isDefaultModel = (m: ModelInfo) => {
    const type = m.model_type || "chat";
    const slot = defaultModels[type];
    return (
      !!slot && slot.provider_id === provider.id && slot.model_id === m.id
    );
  };

  const handleModelTypeChange = async (m: ModelInfo, val: string) => {
    setTypeUpdatingId(m.id);
    try {
      await api.updateModel(provider.id, m.id, { model_type: val });
      message.success(t("models.typeUpdated", { type: typeLabel(val) }));
      onSaved();
    } catch (error) {
      const errMsg =
        error instanceof Error ? error.message : t("models.updateModelFailed");
      message.error(errMsg);
    } finally {
      setTypeUpdatingId(null);
    }
  };

  const doAddModel = async (id: string, name: string, modelType?: string) => {
    await api.addModel(provider.id, {
      id,
      name,
      ...(modelType ? { model_type: modelType } : {}),
    });
    message.success(t("models.modelAdded", { name }));
    form.resetFields();
    setAdding(false);
    onSaved();
  };

  const handleAddModel = async () => {
    try {
      const values = await form.validateFields();
      const id = values.id.trim();
      const name = values.name?.trim() || id;
      const modelAlreadyExists = [
        ...(provider.models ?? []),
      ].some((model) => model.id.trim() === id);

      if (modelAlreadyExists) {
        message.warning(t("models.modelAlreadyExists", { id }));
        return;
      }

      // Step 1: Test the model connection first
      const modelType =
        values.model_type && values.model_type !== "auto"
          ? values.model_type
          : undefined;
      setSaving(true);
      const testResult = await api.testModelConnection(provider.id, {
        model_id: id,
      });

      if (!testResult.success) {
        // Test failed – ask user whether to proceed anyway
        setSaving(false);
        const failureDetail =
          getTestConnectionFailureDetail(testResult.message) ||
          t("models.modelTestFailed");
        Modal.confirm({
          title: t("models.testConnectionFailed"),
          content: t("models.modelTestFailedConfirm", {
            message: failureDetail,
          }),
          okText: t("models.addModel"),
          cancelText: t("models.cancel"),
          onOk: async () => {
            setSaving(true);
            try {
              await doAddModel(id, name, modelType);
            } catch (error) {
              const errMsg =
                error instanceof Error
                  ? error.message
                  : t("models.modelAddFailed");
              message.error(errMsg);
            } finally {
              setSaving(false);
            }
          },
        });
        return;
      }

      // Step 2: If test passed, add the model
      await doAddModel(id, name, modelType);
    } catch (error) {
      if (error && typeof error === "object" && "errorFields" in error) return;
      const errMsg =
        error instanceof Error ? error.message : t("models.modelAddFailed");
      message.error(errMsg);
    } finally {
      setSaving(false);
    }
  };

  const handleTestModel = async (modelId: string) => {
    setTestingModelId(modelId);
    try {
      const result = await api.testModelConnection(provider.id, {
        model_id: modelId,
      });
      if (result.success) {
        message.success(getLocalizedTestConnectionMessage(result, t));
      } else {
        message.warning(getLocalizedTestConnectionMessage(result, t));
      }
    } catch (error) {
      const errMsg =
        error instanceof Error
          ? error.message
          : t("models.testConnectionError");
      message.error(errMsg);
    } finally {
      setTestingModelId(null);
    }
  };

  const handleProbeMultimodal = async (modelId: string) => {
    setProbingModelId(modelId);
    try {
      const result = await api.probeMultimodal(provider.id, modelId);
      const parts: string[] = [];
      if (result.supports_image) parts.push(t("models.probeImage"));

      if (result.supports_video) parts.push(t("models.probeVideo"));

      if (parts.length > 0) {
        message.success(
          t("models.probeSupported", {
            types: parts.join(", "),
          }),
        );
      } else {
        message.info(t("models.probeNotSupported"));
      }
      await onSaved();
    } catch (error) {
      const errMsg =
        error instanceof Error ? error.message : t("models.probeFailed");

      message.error(errMsg);
    } finally {
      setProbingModelId(null);
    }
  };

  const handleRemoveModel = (modelId: string, modelName: string) => {
    Modal.confirm({
      title: t("models.removeModel"),
      content: t("models.removeModelConfirm", {
        name: modelName,
        provider: provider.name,
      }),
      okText: t("common.delete"),
      okButtonProps: { danger: true },
      cancelText: t("models.cancel"),
      onOk: async () => {
        try {
          await api.removeModel(provider.id, modelId);
          message.success(t("models.modelRemoved", { name: modelName }));
          await onSaved();
        } catch (error) {
          const errMsg =
            error instanceof Error
              ? error.message
              : t("models.modelRemoveFailed");
          message.error(errMsg);
        }
      },
    });
  };

  const handleClose = () => {
    setAdding(false);
    setConfigOpenModelId(null);
    setModelSearchQuery("");
    form.resetFields();
    onClose();
  };

  // Load available series for OpenRouter
  useEffect(() => {
    if (isOpenRouter) {
      api
        .getOpenRouterSeries()
        .then((res: SeriesResponse) => {
          const series = res.series || [];
          setAvailableSeries(series);
          setSelectedSeries((prev) =>
            prev.length === 0
              ? series
              : prev.filter((item) => series.includes(item)),
          );
        })
        .catch(() => {
          setAvailableSeries([]);
          setSelectedSeries([]);
        });
    }
  }, [isOpenRouter]);

  // Fetch models with current filters
  const handleFetchModels = async () => {
    if (!isOpenRouter) return;

    setLoadingFilters(true);
    try {
      const filterBody: Record<string, unknown> = {};
      const hasPartialProviderSelection =
        selectedSeries.length > 0 &&
        selectedSeries.length < availableSeries.length;
      if (hasPartialProviderSelection) {
        filterBody.providers = selectedSeries;
      }
      if (selectedInputModalities.length > 0) {
        filterBody.input_modalities = selectedInputModalities;
      }
      if (showFreeOnly) {
        filterBody.is_free = true;
      }

      const result = await api.filterOpenRouterModels(filterBody);
      if (result.success) {
        setDiscoveredModels(result.models || []);
        message.success(
          t("models.filteredModelsLoaded", { count: result.total_count }),
        );
      } else {
        message.error(t("models.filterFailed"));
      }
    } catch {
      message.error(t("models.filterFailed"));
    } finally {
      setLoadingFilters(false);
    }
  };

  const handleAddFilteredModel = async (model: ExtendedModelInfo) => {
    setSaving(true);
    try {
      await api.addModel(provider.id, {
        id: model.id,
        name: model.name,
        is_free: model.is_free,
        supports_multimodal: model.supports_multimodal,
        supports_image: model.supports_image,
        supports_video: model.supports_video,
        probe_source: model.probe_source,
      });
      message.success(t("models.modelAdded", { name: model.name }));
      await onSaved();
      setDiscoveredModels((prev) => prev.filter((m) => m.id !== model.id));
    } catch {
      message.error(t("models.modelAddFailed"));
    } finally {
      setSaving(false);
    }
  };

  const handleAutoDiscoverModels = async () => {
    setDiscoveringModels(true);
    try {
      const result = await api.discoverModels(provider.id, undefined, true);

      if (!result.success) {
        message.error(result.message || t("models.autoDiscoverModelsFailed"));
        return;
      }

      await onSaved();

      if (result.added_count > 0) {
        message.success(
          t("models.autoDiscoverModelsSuccess", {
            count: result.added_count,
          }),
        );
        return;
      }

      message.info(
        result.message ||
          t("models.autoDiscoverModelsNoNew", {
            count: result.models.length,
          }),
      );
    } catch (error) {
      const errMsg =
        error instanceof Error
          ? error.message
          : t("models.autoDiscoverModelsFailed");
      message.error(errMsg);
    } finally {
      setDiscoveringModels(false);
    }
  };

  useEffect(() => {
    if (!adding) {
      setDiscoveredModels([]);
      return;
    }
    setLoadingDiscoveredModels(true);
    api
      .discoverModels(provider.id, undefined, false)
      .then((result) => {
        const sorted = result.models
          .slice()
          .sort((a, b) => a.id.localeCompare(b.id));
        setDiscoveredModels(sorted as unknown as ExtendedModelInfo[]);
      })
      .catch(() => setDiscoveredModels([]))
      .finally(() => setLoadingDiscoveredModels(false));
  }, [adding, provider.id]);

  useEffect(() => {
    if (!isOpenRouter || !adding) return;
    setAdding(false);
    form.resetFields();
  }, [adding, form, isOpenRouter]);

  const filteredModels = useMemo(() => {
    let list = [...(provider.models ?? [])];
    if (modelTypeFilter) {
      list = list.filter((m) => (m.model_type || "chat") === modelTypeFilter);
    }
    const q = modelSearchQuery.trim().toLowerCase();
    if (q) {
      list = list.filter(
        (m) =>
          m.name.toLowerCase().includes(q) || m.id.toLowerCase().includes(q),
      );
    }
    return list.sort((a, b) => {
      const ta = typeOrder.indexOf(
        (a.model_type || "chat") as (typeof typeOrder)[number],
      );
      const tb = typeOrder.indexOf(
        (b.model_type || "chat") as (typeof typeOrder)[number],
      );
      if (ta !== tb) return ta - tb;
      return a.name.localeCompare(b.name);
    });
  }, [provider.models, modelSearchQuery, modelTypeFilter]);

  const colors = tagColors(isDark);

  return (
    <Modal
      title={t("models.manageModelsTitle", { provider: provider.name })}
      open={open}
      onCancel={handleClose}
      footer={null}
      width={800}
      destroyOnHidden
    >
      {/* Type filter tabs (always shown, counts per model) */}
      <div style={{ marginBottom: 8 }}>
        <ModelTypeTabs
          activeType={modelTypeFilter || undefined}
          onChange={(v) => setModelTypeFilter(v ?? "")}
          providers={[provider]}
        />
      </div>

      <Input
        placeholder={t("models.searchModelPlaceholder", "搜索模型...")}
        value={modelSearchQuery}
        onChange={(e) => setModelSearchQuery(e.target.value)}
        prefix={<SearchOutlined />}
        allowClear
      />

      {/* Model list */}
      <div className={styles.modelList}>
        {filteredModels.length === 0 ? (
          <div className={styles.modelListEmpty}>{t("models.noModels")}</div>
        ) : (
          filteredModels.map((m) => {
            const isDeletable = provider.is_custom;
            const isConfigOpen = configOpenModelId === m.id;
            return (
              <div key={m.id}>
                <div className={styles.modelListItem}>
                  {/* Row 1: name + ID */}
                  <div className={styles.modelRowMain}>
                    <span className={styles.modelListItemName}>{m.name}</span>
                    {isDefaultModel(m) && (
                      <Tag
                        style={{
                          fontSize: 11,
                          marginRight: 4,
                          ...colors.default,
                        }}
                      >
                        <StarFilled
                          style={{ fontSize: 10, marginRight: 3 }}
                        />
                        {t("models.defaultModelTag")}
                      </Tag>
                    )}
                    <span className={styles.modelListItemId}>{m.id}</span>
                  </div>
                  {/* Row 2: type (save on change) + capability/free/default tags */}
                  <div className={styles.modelRowMeta}>
                    <Select
                      size="small"
                      style={{ width: 132 }}
                      value={m.model_type || "chat"}
                      loading={typeUpdatingId === m.id}
                      onChange={(val: string) => handleModelTypeChange(m, val)}
                      options={modelTypeOptions}
                    />
                    <CapabilityTags model={m} isDark={isDark} />
                    {m.is_free && (
                      <Tag
                        style={{
                          fontSize: 11,
                          marginRight: 4,
                          ...colors.free,
                        }}
                      >
                        <GiftOutlined
                          style={{ fontSize: 10, marginRight: 3 }}
                        />
                        {t("models.free")}
                      </Tag>
                    )}
                    <Tag
                      style={{
                        fontSize: 11,
                        marginRight: 4,
                        ...(isDeletable ? colors.userAdded : colors.builtin),
                      }}
                    >
                      {isDeletable ? (
                        <UserOutlined
                          style={{ fontSize: 10, marginRight: 3 }}
                        />
                      ) : (
                        <DatabaseOutlined
                          style={{ fontSize: 10, marginRight: 3 }}
                        />
                      )}
                      {t(isDeletable ? "models.userAdded" : "models.builtin")}
                    </Tag>
                    <span
                      style={{
                        display: "inline-block",
                        width: 1,
                        height: 16,
                        background: isDark
                          ? "rgba(255,255,255,0.15)"
                          : "#e5e7eb",
                        margin: "0 8px",
                        flexShrink: 0,
                      }}
                    />
                    {m.probe_source !== "documentation" && (
                      <Tooltip
                        title={t("models.probeMultimodal", "测试多模态")}
                      >
                        <Button
                          type="text"
                          size="small"
                          icon={<ExperimentOutlined />}
                          onClick={() => handleProbeMultimodal(m.id)}
                          loading={probingModelId === m.id}
                          style={darkBtnStyle}
                        />
                      </Tooltip>
                    )}
                    <Tooltip title={t("models.testConnection")}>
                      <Button
                        type="text"
                        size="small"
                        icon={<ApiOutlined />}
                        onClick={() => handleTestModel(m.id)}
                        loading={testingModelId === m.id}
                        style={darkBtnStyle}
                      />
                    </Tooltip>
                    <Tooltip title={t("models.modelConfigLabel", "模型配置")}>
                      <Button
                        type="text"
                        size="small"
                        icon={
                          isConfigOpen ? <DownOutlined /> : <SettingOutlined />
                        }
                        onClick={() =>
                          setConfigOpenModelId(isConfigOpen ? null : m.id)
                        }
                        style={darkBtnStyle}
                      />
                    </Tooltip>
                    {isDeletable && (
                      <Button
                        type="text"
                        size="small"
                        danger
                        icon={<DeleteOutlined />}
                        onClick={() => handleRemoveModel(m.id, m.name)}
                      />
                    )}
                  </div>
                </div>
                {isConfigOpen && (
                  <div
                    style={{
                      padding: "0 16px 12px",
                      borderBottom: isDark
                        ? "1px solid rgba(255,255,255,0.06)"
                        : "1px solid #f5f5f5",
                    }}
                  >
                    <ModelConfigEditor
                      providerId={provider.id}
                      model={m}
                      onSaved={onSaved}
                      onClose={() => setConfigOpenModelId(null)}
                      isDark={isDark}
                    />
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {isOpenRouter && (
        <OpenRouterFilterSection
          showFilters={showFilters}
          availableSeries={availableSeries}
          selectedSeries={selectedSeries}
          selectedInputModalities={selectedInputModalities}
          showFreeOnly={showFreeOnly}
          loadingFilters={loadingFilters}
          discoveredModels={discoveredModels}
          saving={saving}
          isDark={isDark}
          freeTagStyle={colors.free}
          onToggleFilters={() => setShowFilters(!showFilters)}
          onSelectedSeriesChange={setSelectedSeries}
          onSelectedInputModalitiesChange={setSelectedInputModalities}
          onShowFreeOnlyChange={setShowFreeOnly}
          onFetchModels={handleFetchModels}
          onAddModel={handleAddFilteredModel}
        />
      )}

      {/* Add model section */}
      {!isOpenRouter &&
        (adding ? (
          <div className={styles.modelAddForm}>
            <Form form={form} layout="vertical" style={{ marginBottom: 0 }}>
              <Form.Item
                name="id"
                label={t("models.modelIdLabel")}
                rules={[{ required: true, message: t("models.modelIdLabel") }]}
                style={{ marginBottom: 12 }}
              >
                <AutoComplete
                  placeholder={t("models.modelIdPlaceholder")}
                  options={discoveredModels.map((model) => ({
                    value: model.id,
                    label: model.id,
                  }))}
                  filterOption={(
                    inputValue: string,
                    option?: { value?: string },
                  ) =>
                    option?.value
                      ?.toLowerCase()
                      .includes(inputValue.toLowerCase()) ?? false
                  }
                  notFoundContent={
                    loadingDiscoveredModels
                      ? t("common.loading")
                      : t("models.modelDiscoveryUnavailableHint")
                  }
                >
                  <Input />
                </AutoComplete>
              </Form.Item>
              <Form.Item
                name="name"
                label={t("models.modelNameLabel")}
                style={{ marginBottom: 12 }}
              >
                <Input placeholder={t("models.modelNamePlaceholder")} />
              </Form.Item>
              <Form.Item
                name="model_type"
                label={t("models.modelTypeLabel")}
                initialValue="auto"
                style={{ marginBottom: 12 }}
              >
                <Select
                  options={[
                    { value: "auto", label: t("models.autoInferType") },
                    ...modelTypeOptions,
                  ]}
                />
              </Form.Item>
              {watchedModelType === "auto" &&
                watchedModelId &&
                String(watchedModelId).trim() !== "" && (
                  <div
                    style={{
                      marginTop: -6,
                      marginBottom: 12,
                      fontSize: 12,
                      color: isDark ? "rgba(255,255,255,0.45)" : "#888",
                    }}
                  >
                    {t("models.inferredTypeHint", {
                      type: typeLabel(
                        inferModelType(
                          String(watchedModelId),
                          String(form.getFieldValue("name") || ""),
                        ),
                      ),
                    })}
                  </div>
                )}
              <div
                style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}
              >
                <Button
                  size="small"
                  onClick={() => {
                    setAdding(false);
                    form.resetFields();
                  }}
                >
                  {t("models.cancel")}
                </Button>
                <Button
                  type="primary"
                  size="small"
                  loading={saving}
                  onClick={handleAddModel}
                >
                  {t("models.addModel")}
                </Button>
              </div>
            </Form>
          </div>
        ) : (
          <div className={styles.modalActionRow}>
            {supportsAutoDiscover && (
              <Button
                icon={<SearchOutlined />}
                loading={discoveringModels}
                onClick={handleAutoDiscoverModels}
                style={{ flex: 1 }}
              >
                {t("models.autoDiscoverModels")}
              </Button>
            )}
            <Button
              type="dashed"
              icon={<PlusOutlined />}
              onClick={() => setAdding(true)}
              style={{ flex: 1 }}
            >
              {t("models.addModel")}
            </Button>
          </div>
        ))}
    </Modal>
  );
}
