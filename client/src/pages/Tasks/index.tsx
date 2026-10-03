// 任务中心（壳页）
// v2.2.2 设计：侧边栏「任务」入口，展示长任务执行概览。
// 本期为壳页：占位说明 + 引导发起对话；任务卡片/进度追踪/产物关联属二期。

import { Button, Card } from "antd";
import { RocketOutlined, MessageOutlined } from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { PageHeader } from "../../components/PageHeader";

const TasksPage = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();

  return (
    <div style={{ padding: 24 }}>
      <PageHeader items={[{ title: t("tasks.title") }]} />
      <Card>
        <div
          style={{
            textAlign: "center",
            padding: "48px 24px",
            color: "var(--text-color-secondary, rgba(0,0,0,0.45))",
          }}
        >
          <div style={{ fontSize: 40, marginBottom: 16 }}>
            <RocketOutlined />
          </div>
          <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>
            {t("tasks.placeholderTitle")}
          </div>
          <div style={{ maxWidth: 420, margin: "0 auto 24px", lineHeight: 1.8 }}>
            {t("tasks.placeholderDesc")}
          </div>
          <Button
            type="primary"
            icon={<MessageOutlined />}
            onClick={() => navigate("/chat")}
          >
            {t("tasks.startChat")}
          </Button>
        </div>
      </Card>
    </div>
  );
};

export default TasksPage;
