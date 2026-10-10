import { useEffect, useState } from "react";
import { Modal, Button, Spin, Empty, Tag } from "antd";
import { useTranslation } from "react-i18next";
import { userModelPrefsApi } from "../../../api/modules/user_model_prefs";
import { useModelPrefs } from "@/lib/modelChoice";
import styles from "./resource.module.less";

interface ModelOption {
  id: string;
  name: string;
  providerId: string;
  provider?: string;
  model_type?: string;
  status?: string;
}

interface ModelPickerModalProps {
  open: boolean;
  onClose: () => void;
}

/**
 * M4/T4.2：模型选择面板（模型选择自旧工具栏移入 + 菜单 / 个人下拉）。
 *
 * - 只列聊天模型（model_type=llm）：后端 /models/available 支持 types= 过滤，
 *   不过滤会把 qwen3-embedding 这类嵌入模型混进聊天模型列表。
 * - 选中写入 ModelChoiceContext（用户全局偏好，后端 /user/model-prefs 权威），
 *   以 (provider_id, model) 成对存储——同名模型可能来自不同 provider
 *   （dev 实测 a3/A3 与 local3-new/A3 并存），只存模型名会选错 provider。
 * - "自动"为禁用占位（本期不实现自动路由）。
 */
export default function ModelPickerModal(props: ModelPickerModalProps) {
  const { t } = useTranslation();
  const { chat: chatSlot, setChat } = useModelPrefs();
  const [models, setModels] = useState<ModelOption[]>([]);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!props.open || loaded) return;
    setLoading(true);
    userModelPrefsApi
      .getAvailableModels("chat")
      .then((resp: unknown) => {
        // /api/models/available?types=llm → { global_models: [{id,name,provider_id,provider_name,model_type}] }
        // （/api/models 返回的是提供商列表，不能直接当模型用）
        const raw = resp as { global_models?: any[]; models?: any[] } | any[];
        const list: any[] = Array.isArray(raw)
          ? raw
          : Array.isArray(raw?.global_models)
            ? raw.global_models
            : Array.isArray(raw?.models)
              ? raw.models
              : [];
        setModels(
          list
            .map((m) => ({
              id: String(m.id ?? m.model_id ?? ""),
              name: String(m.name ?? m.model_name ?? m.id ?? ""),
              providerId: String(m.provider_id ?? ""),
              provider: m.provider_name
                ? String(m.provider_name)
                : m.provider
                  ? String(m.provider)
                  : undefined,
              model_type: m.model_type ? String(m.model_type) : undefined,
              status: m.status ? String(m.status) : undefined,
            }))
            .filter((m) => m.id && (m.model_type ?? "chat") === "chat"),
        );
        setLoaded(true);
      })
      .catch(() => {
        setModels([]);
        setLoaded(true);
      })
      .finally(() => setLoading(false));
  }, [props.open, loaded]);

  const isCurrent = (m: ModelOption) =>
    chatSlot.model === m.id && (chatSlot.providerId ?? "") === m.providerId;

  const pick = (m: ModelOption) => {
    setChat({ providerId: m.providerId, model: m.id, name: m.name })
      .catch(() => {})
      .finally(() => props.onClose());
  };

  const clear = () => {
    setChat({ providerId: null, model: null, name: null })
      .catch(() => {})
      .finally(() => props.onClose());
  };

  return (
    <Modal
      title={t("resourceMenu.model")}
      open={props.open}
      onCancel={props.onClose}
      width={440}
      destroyOnClose
      footer={
        <span>
          {chatSlot.model && (
            <Button onClick={clear} style={{ marginRight: 8 }}>
              {t("resourcePicker.clearModel")}
            </Button>
          )}
          <Button onClick={props.onClose}>{t("common.close")}</Button>
        </span>
      }
    >
      <div className={styles.pickRow} style={{ opacity: 0.5, cursor: "not-allowed" }}>
        <Tag>{t("resourcePicker.autoUnavailable")}</Tag>
      </div>
      <Spin spinning={loading}>
        {!loading && models.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={t("resourcePicker.noModels")}
          />
        ) : (
          <div className={styles.recordList}>
            {models.map((m) => {
              const current = isCurrent(m);
              return (
                <div
                  key={`${m.providerId}::${m.id}`}
                  className={styles.pickRow}
                  onClick={() => pick(m)}
                  role="radio"
                  aria-checked={current}
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") pick(m);
                  }}
                >
                  <span
                    style={{
                      width: 14,
                      height: 14,
                      borderRadius: "50%",
                      border: current
                        ? "4px solid var(--color-primary, #1677ff)"
                        : "1px solid var(--color-border, rgba(0,0,0,0.15))",
                      flexShrink: 0,
                    }}
                  />
                  <span className={styles.pickName}>{m.name}</span>
                  {m.provider && (
                    <span className={styles.pickDesc}>{m.provider}</span>
                  )}
                  {current && (
                    <Tag color="blue" style={{ marginLeft: "auto" }}>
                      {t("resourcePicker.current")}
                    </Tag>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </Spin>
    </Modal>
  );
}
