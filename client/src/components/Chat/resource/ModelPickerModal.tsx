import { useEffect, useState } from "react";
import { Modal, Button, Spin, Empty, Tag } from "antd";
import { useTranslation } from "react-i18next";
import api from "@/api";
import { useModelChoice } from "@/lib/modelChoice";
import styles from "./resource.module.less";

interface ModelOption {
  id: string;
  name: string;
  provider?: string;
  status?: string;
}

interface ModelPickerModalProps {
  open: boolean;
  onClose: () => void;
}

/**
 * M4/T4.2：模型选择面板（模型选择自旧工具栏移入 + 菜单 / 个人下拉）。
 * "自动"为禁用占位（本期不实现自动路由）；选中写入 ModelChoiceContext（持久化），
 * 发送时经 biz_params.model_id 预留透传。
 */
export default function ModelPickerModal(props: ModelPickerModalProps) {
  const { t } = useTranslation();
  const { choice, setChoice, clearChoice } = useModelChoice();
  const [models, setModels] = useState<ModelOption[]>([]);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!props.open || loaded) return;
    setLoading(true);
    api
      .get("/models/available")
      .then((resp) => {
        // /api/models/available → { global_models: [{id,name,provider_id,provider_name}] }
        // （/api/models 返回的是提供商列表，不能直接当模型用）
        const raw = resp as
          | { global_models?: any[]; models?: any[] }
          | any[];
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
              provider: m.provider_name
                ? String(m.provider_name)
                : m.provider
                  ? String(m.provider)
                  : undefined,
              status: m.status ? String(m.status) : undefined,
            }))
            .filter((m) => m.id),
        );
        setLoaded(true);
      })
      .catch(() => {
        setModels([]);
        setLoaded(true);
      })
      .finally(() => setLoading(false));
  }, [props.open, loaded]);

  const pick = (m: ModelOption) => {
    setChoice({ id: m.id, name: m.name });
    props.onClose();
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
          {choice.id && (
            <Button onClick={() => clearChoice()} style={{ marginRight: 8 }}>
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
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("resourcePicker.noModels")} />
        ) : (
          <div className={styles.recordList}>
            {models.map((m) => (
              <div
                key={m.id}
                className={styles.pickRow}
                onClick={() => pick(m)}
                role="radio"
                aria-checked={choice.id === m.id}
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
                    border:
                      choice.id === m.id
                        ? "4px solid var(--color-primary, #1677ff)"
                        : "1px solid var(--color-border, rgba(0,0,0,0.15))",
                    flexShrink: 0,
                  }}
                />
                <span className={styles.pickName}>{m.name}</span>
                {m.provider && (
                  <span className={styles.pickDesc}>{m.provider}</span>
                )}
                {choice.id === m.id && (
                  <Tag color="blue" style={{ marginLeft: "auto" }}>
                    {t("resourcePicker.current")}
                  </Tag>
                )}
              </div>
            ))}
          </div>
        )}
      </Spin>
    </Modal>
  );
}
