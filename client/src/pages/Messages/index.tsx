import { Result } from "antd";
import { useTranslation } from "react-i18next";

export default function MessagesPage() {
  const { t } = useTranslation();

  return (
    <Result
      status="info"
      title={t("messages.comingSoon") || "智能消息系统"}
      subTitle={t("messages.comingSoonDesc") || "智能消息系统功能正在开发中，敬请期待..."}
    />
  );
}