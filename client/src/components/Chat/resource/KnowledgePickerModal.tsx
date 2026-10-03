import { useState } from "react";
import { Modal, Button } from "antd";
import { useTranslation } from "react-i18next";
import { KnowledgeSelector } from "./KnowledgeSelector";
import type { KnowledgeInfo } from "../types";

interface KnowledgePickerModalProps {
  open: boolean;
  onClose: () => void;
  onConfirm: (items: KnowledgeInfo[]) => void;
}

/**
 * M4/T4.3：从知识库选择面板（仅企业版入口显示）。
 * 复用 KnowledgeSelector；destroyOnClose 保证每次打开状态干净。
 */
export default function KnowledgePickerModal(props: KnowledgePickerModalProps) {
  const { t } = useTranslation();
  const [picked, setPicked] = useState<KnowledgeInfo[]>([]);

  return (
    <Modal
      title={t("resourceMenu.knowledge")}
      open={props.open}
      onCancel={props.onClose}
      width={520}
      destroyOnClose
      footer={
        <span>
          <Button
            onClick={() => {
              setPicked([]);
              props.onClose();
            }}
          >
            {t("common.cancel")}
          </Button>
          <Button
            type="primary"
            disabled={picked.length === 0}
            onClick={() => {
              props.onConfirm(picked);
              setPicked([]);
              props.onClose();
            }}
          >
            {t("common.confirm")}
          </Button>
        </span>
      }
    >
      <div style={{ maxHeight: "55vh", overflowY: "auto" }}>
        <KnowledgeSelector selected={picked} onSelect={setPicked} />
      </div>
    </Modal>
  );
}
