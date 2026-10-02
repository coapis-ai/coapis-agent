import { Modal, Button } from "antd";
import { useTranslation } from "react-i18next";
import ChatSessionDropdown from "../../../pages/Chat/components/ChatSessionDropdown";

interface HistorySessionsModalProps {
  open: boolean;
  onClose: () => void;
  /**
   * mode="switch"：点击会话即跳转（默认 ChatSessionDropdown 行为）
   * mode="reference"：点击会话加入引用芯片
   */
  mode: "switch" | "reference";
  onReference?: (session: { id: string; name: string }) => void;
}

/**
 * M4/T4.4：历史会话面板。复用 ChatSessionDropdown，两种模式：
 * - switch：切换当前会话（顶栏会话快切同样复用此组件）
 * - reference：把历史会话作为引用芯片附到下一条消息
 */
export default function HistorySessionsModal(props: HistorySessionsModalProps) {
  const { t } = useTranslation();

  return (
    <Modal
      title={
        props.mode === "reference"
          ? t("resourceMenu.history")
          : t("resourceMenu.session")
      }
      open={props.open}
      onCancel={props.onClose}
      width={360}
      destroyOnClose
      footer={
        <Button onClick={props.onClose}>{t("common.close")}</Button>
      }
    >
      <ChatSessionDropdown
        open={props.open}
        onClose={props.onClose}
        onSelect={
          props.mode === "reference" ? props.onReference : undefined
        }
      />
    </Modal>
  );
}
