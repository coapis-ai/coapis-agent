import React, { useState } from "react";
import { Modal, Button, Spin, Empty } from "antd";
import { useTranslation } from "react-i18next";
import styles from "./resource.module.less";

export interface PickItem {
  id: string;
  name: string;
  desc?: string;
}

interface MultiSelectPickerModalProps {
  open: boolean;
  title: string;
  hint?: string;
  items: PickItem[];
  loading: boolean;
  selectedIds: string[];
  onOk: (ids: string[]) => void;
  onClose: () => void;
}

/**
 * M4/T4.1 更多选项：通用多选面板（MCP 服务 / 指定技能）。
 * 本期语义：名单选择并随 biz_params 预留透传（后端暂未消费），UI 状态即时生效。
 */
export default function MultiSelectPickerModal(props: MultiSelectPickerModalProps) {
  const { t } = useTranslation();
  const [checked, setChecked] = useState<Set<string>>(new Set(props.selectedIds));

  // 每次打开同步一次外部选中态
  React.useEffect(() => {
    if (props.open) setChecked(new Set(props.selectedIds));
  }, [props.open, props.selectedIds]);

  const toggle = (id: string) => {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <Modal
      title={props.title}
      open={props.open}
      onCancel={props.onClose}
      width={440}
      destroyOnClose
      footer={
        <div className={styles.footerBar}>
          <span className={styles.footerCount}>
            {t("resourcePicker.selectedCount", { count: checked.size })}
          </span>
          <span>
            <Button onClick={props.onClose} style={{ marginRight: 8 }}>
              {t("common.cancel")}
            </Button>
            <Button
              type="primary"
              onClick={() => {
                props.onOk(Array.from(checked));
                props.onClose();
              }}
            >
              {t("common.confirm")}
            </Button>
          </span>
        </div>
      }
    >
      {props.hint && (
        <div style={{ fontSize: 12, color: "rgba(0,0,0,0.45)", marginBottom: 10 }}>
          {props.hint}
        </div>
      )}
      <Spin spinning={props.loading}>
        {!props.loading && props.items.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("resourcePicker.noneAvailable")} />
        ) : (
          <div className={styles.recordList}>
            {props.items.map((item) => (
              <div
                key={item.id}
                className={styles.pickRow}
                onClick={() => toggle(item.id)}
                role="checkbox"
                aria-checked={checked.has(item.id)}
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "Enter") toggle(item.id);
                }}
              >
                <span
                  style={{
                    width: 14,
                    height: 14,
                    borderRadius: 3,
                    border: checked.has(item.id)
                      ? "1px solid transparent"
                      : "1px solid var(--color-border, rgba(0,0,0,0.15))",
                    background: checked.has(item.id)
                      ? "var(--color-primary, #1677ff)"
                      : "transparent",
                    flexShrink: 0,
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    color: "#fff",
                    fontSize: 10,
                  }}
                >
                  {checked.has(item.id) ? "✓" : ""}
                </span>
                <span className={styles.pickName}>{item.name}</span>
                {item.desc && <span className={styles.pickDesc}>{item.desc}</span>}
              </div>
            ))}
          </div>
        )}
      </Spin>
    </Modal>
  );
}
