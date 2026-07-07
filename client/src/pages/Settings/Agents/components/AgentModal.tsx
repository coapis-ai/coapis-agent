import { useEffect, useState, useMemo } from "react";
import {
  Modal,
  Form,
  Input,
  Select,
  Space,
  Spin,
} from "antd";

/** Generate a short ASCII-safe agent ID: user_{6-char hex} */
function generateAgentId(): string {
  // crypto.randomUUID() only works in secure contexts (HTTPS);
  // use Math.random fallback for HTTP environments.
  const uuid = typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID()
    : "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
        const r = (Math.random() * 16) | 0;
        return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
      });
  const hex = uuid.replace(/-/g, "").slice(0, 6);
  return `user_${hex}`;
}
import { useTranslation } from "react-i18next";
import type { AgentSummary } from "@/api/types/agents";
import type { ProviderInfo } from "@/api/types/provider";
import { getAgentDisplayName } from "@/utils/agentDisplayName";
import { providerApi } from "@/api/modules/provider";
import { providerIcon } from "../../Models/components/providerIcon";
import { useUser } from "@/contexts/UserContext";

interface EligibleProvider {
  id: string;
  name: string;
  models: Array<{ id: string; name: string }>;
}

interface AgentModalProps {
  open: boolean;
  editingAgent: AgentSummary | null;
  form: ReturnType<typeof Form.useForm>[0];
  onSave: () => Promise<void>;
  onCancel: () => void;
}

export function AgentModal({
  open,
  editingAgent,
  form,
  onSave,
  onCancel,
}: AgentModalProps) {
  const { t } = useTranslation();
  const { user } = useUser();
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [loadingProviders, setLoadingProviders] = useState(false);
  const [saving, setSaving] = useState(false);

  const selectedProviderId = Form.useWatch("active_model_provider", form);
  const selectedModelId = Form.useWatch("active_model_model", form);

  const eligibleProviders: EligibleProvider[] = useMemo(() => {
    return providers
      .filter((p) => {
        const hasModels =
          (p.models?.length ?? 0) > 0;
        if (!hasModels) return false;
        if (p.require_api_key === false) return !!p.base_url;
        if (p.is_custom) return !!p.base_url;
        if (p.require_api_key ?? true) return !!p.api_key;
        return true;
      })
      .map((p) => ({
        id: p.id,
        name: p.name,
        models: [...(p.models ?? [])],
      }));
  }, [providers]);

  const availableModels = useMemo(() => {
    if (!selectedProviderId) return [];
    const provider = eligibleProviders.find((p) => p.id === selectedProviderId);
    return provider?.models ?? [];
  }, [selectedProviderId, eligibleProviders]);
  // Auto-generate ID when creating a new agent
  useEffect(() => {
    if (open && !editingAgent) {
      form.setFieldsValue({ id: generateAgentId() });
    }
  }, [open, editingAgent, form]);

  useEffect(() => {
    if (!open) return;

    setLoadingProviders(true);
    providerApi
      .listProviders()
      .then((data) => {
        if (Array.isArray(data)) setProviders(data);
      })
      .catch((err) => console.error("Failed to load providers:", err))
      .finally(() => setLoadingProviders(false));
  }, [open]);

  const handleProviderChange = (providerId: string) => {
    form.setFieldsValue({
      active_model_provider: providerId,
      active_model_model: undefined,
    });
  };

  const handleClearModel = () => {
    form.setFieldsValue({
      active_model_provider: undefined,
      active_model_model: undefined,
    });
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave();
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={
        editingAgent
          ? t("agent.editTitle", {
              name: getAgentDisplayName(editingAgent, t),
            })
          : t("agent.createTitle")
      }
      open={open}
      onOk={handleSave}
      onCancel={onCancel}
      confirmLoading={saving}
      width={640}
      okText={t("common.save")}
      cancelText={t("common.cancel")}
    >
      <Form form={form} layout="vertical" autoComplete="off">
        <Form.Item name="active_model_provider" hidden>
          <Input />
        </Form.Item>
        <Form.Item name="active_model_model" hidden>
          <Input />
        </Form.Item>

        <Form.Item
          name="id"
          label={t("agent.idLabel")}
          help={editingAgent ? undefined : t("agent.idHelp")}
        >
          <Input disabled />
        </Form.Item>
        <Form.Item
          name="name"
          label={t("agent.name")}
          rules={[{ required: true, message: t("agent.nameRequired") }]}
        >
          <Input placeholder={t("agent.namePlaceholder")} />
        </Form.Item>
        <Form.Item name="description" label={t("agent.description")}>
          <Input.TextArea
            placeholder={t("agent.descriptionPlaceholder")}
            rows={3}
          />
        </Form.Item>
        <Form.Item label={t("agent.model")} help={t("agent.modelHelp")}>
          <Space.Compact style={{ width: "100%" }}>
            <Select
              value={selectedProviderId || undefined}
              onChange={handleProviderChange}
              placeholder={t("agent.modelPlaceholder")}
              allowClear
              onClear={handleClearModel}
              loading={loadingProviders}
              style={{ width: "45%" }}
              showSearch
              optionFilterProp="label"
              options={eligibleProviders.map((p) => ({
                value: p.id,
                label: p.name,
              }))}
              optionRender={({ value }) => {
                const p = eligibleProviders.find((ep) => ep.id === value);
                if (!p) return value;
                return (
                  <Space size={6}>
                    <img
                      src={providerIcon(p.id)}
                      alt=""
                      style={{ width: 16, height: 16 }}
                    />
                    <span>{p.name}</span>
                  </Space>
                );
              }}
              notFoundContent={
                loadingProviders ? (
                  <Spin size="small" />
                ) : (
                  t("agent.noConfiguredModels")
                )
              }
            />
            <Select
              value={selectedModelId || undefined}
              onChange={(modelId) =>
                form.setFieldsValue({ active_model_model: modelId })
              }
              placeholder={
                selectedProviderId
                  ? t("models.model")
                  : t("agent.modelPlaceholder")
              }
              disabled={!selectedProviderId}
              style={{ width: "55%" }}
              showSearch
              optionFilterProp="label"
              options={availableModels.map((m) => ({
                value: m.id,
                label: m.name || m.id,
              }))}
            />
          </Space.Compact>
        </Form.Item>
        <Form.Item
          name="workspace_dir"
          label={t("agent.workspace")}
          help={!editingAgent ? t("agent.workspaceHelp") : undefined}
        >
          <Input
            placeholder={user?.username ? `workspaces/${user.username}/agents/my-agent` : "workspaces/{username}/agents/my-agent"}
            disabled={!!editingAgent}
          />
        </Form.Item>
      </Form>

      {/* 技能选择已隐藏：全局技能可直接使用，无需在创建/编辑时选择 */}
    </Modal>
  );
}
