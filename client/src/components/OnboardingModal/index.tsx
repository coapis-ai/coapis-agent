import React, { useState } from "react";
import { Modal, Steps, Input, Button, Typography, Space, Card, Radio } from "antd";
import { RobotOutlined, UserOutlined, SmileOutlined, ThunderboltOutlined } from "@ant-design/icons";
import { authApi } from "../../api/modules/auth";

const { Title, Paragraph, Text } = Typography;

export interface OnboardingData {
  agent_name?: string;
  agent_style?: string;
  agent_role?: string;
  user_name?: string;
}

interface OnboardingModalProps {
  open: boolean;
  onComplete: (data: OnboardingData) => void;
  onCancel?: () => void;
}

const AGENT_STYLES = [
  { value: "专业", label: "专业", description: "严谨、准确、高效" },
  { value: "友好", label: "友好", description: "温暖、耐心、贴心" },
  { value: "幽默", label: "幽默", description: "轻松、有趣、有梗" },
  { value: "简洁", label: "简洁", description: "直接、干练、不废话" },
];

const AGENT_ROLES = [
  { value: "AI助手", label: "AI 助手", icon: "🤖" },
  { value: "工作伙伴", label: "工作伙伴", icon: "💼" },
  { value: "学习导师", label: "学习导师", icon: "📚" },
  { value: "创意搭档", label: "创意搭档", icon: "🎨" },
];

const OnboardingModal: React.FC<OnboardingModalProps> = ({
  open,
  onComplete,
  onCancel,
}) => {
  const [current, setCurrent] = useState(0);
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<OnboardingData>({
    agent_name: "",
    agent_style: "友好",
    agent_role: "AI助手",
    user_name: "",
  });

  const steps = [
    {
      title: "欢迎",
      icon: <SmileOutlined />,
    },
    {
      title: "设置身份",
      icon: <RobotOutlined />,
    },
    {
      title: "完成",
      icon: <ThunderboltOutlined />,
    },
  ];

  const handleNext = () => {
    setCurrent(current + 1);
  };

  const handlePrev = () => {
    setCurrent(current - 1);
  };

  const handleSubmit = async () => {
    setLoading(true);
    try {
      await authApi.completeOnboarding(data);
      onComplete(data);
    } catch (error) {
      console.error("Failed to complete onboarding:", error);
      // Still complete even if API fails
      onComplete(data);
    } finally {
      setLoading(false);
    }
  };

  const renderStepContent = () => {
    switch (current) {
      case 0:
        return (
          <div style={{ textAlign: "center", padding: "20px 0" }}>
            <RobotOutlined style={{ fontSize: 64, color: "#1890ff", marginBottom: 24 }} />
            <Title level={3}>欢迎使用 CoApis！</Title>
            <Paragraph type="secondary">
              让我们花一分钟来设置你的专属 AI 助手
            </Paragraph>
            <Space direction="vertical" size="small" style={{ marginTop: 20 }}>
              <Text>• 设置助手的名字和风格</Text>
              <Text>• 定义它的角色定位</Text>
              <Text>• 开始你的智能之旅</Text>
            </Space>
          </div>
        );

      case 1:
        return (
          <div style={{ padding: "10px 0" }}>
            <Card title="给你的助手起个名字" size="small" style={{ marginBottom: 16 }}>
              <Input
                placeholder="例如：小蜜、助手、CoApis..."
                value={data.agent_name}
                onChange={(e) => setData({ ...data, agent_name: e.target.value })}
                prefix={<RobotOutlined />}
              />
            </Card>

            <Card title="选择助手风格" size="small" style={{ marginBottom: 16 }}>
              <Radio.Group
                value={data.agent_style}
                onChange={(e) => setData({ ...data, agent_style: e.target.value })}
                optionType="button"
                buttonStyle="solid"
              >
                {AGENT_STYLES.map((style) => (
                  <Radio.Button key={style.value} value={style.value}>
                    {style.label}
                  </Radio.Button>
                ))}
              </Radio.Group>
              <Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
                {AGENT_STYLES.find((s) => s.value === data.agent_style)?.description}
              </Paragraph>
            </Card>

            <Card title="选择助手角色" size="small">
              <Radio.Group
                value={data.agent_role}
                onChange={(e) => setData({ ...data, agent_role: e.target.value })}
                optionType="button"
                buttonStyle="solid"
              >
                {AGENT_ROLES.map((role) => (
                  <Radio.Button key={role.value} value={role.value}>
                    {role.icon} {role.label}
                  </Radio.Button>
                ))}
              </Radio.Group>
            </Card>
          </div>
        );

      case 2:
        return (
          <div style={{ textAlign: "center", padding: "20px 0" }}>
            <ThunderboltOutlined style={{ fontSize: 64, color: "#52c41a", marginBottom: 24 }} />
            <Title level={3}>设置完成！</Title>
            <Paragraph type="secondary">
              你的专属 AI 助手已准备就绪
            </Paragraph>
            <Card size="small" style={{ textAlign: "left", maxWidth: 400, margin: "0 auto" }}>
              <Space direction="vertical" size="small">
                <Text>
                  <UserOutlined /> 助手名字：<strong>{data.agent_name || "CoApis"}</strong>
                </Text>
                <Text>
                  <SmileOutlined /> 风格：<strong>{data.agent_style}</strong>
                </Text>
                <Text>
                  <RobotOutlined /> 角色：<strong>{data.agent_role}</strong>
                </Text>
              </Space>
            </Card>
          </div>
        );

      default:
        return null;
    }
  };

  return (
    <Modal
      open={open}
      title="欢迎使用 CoApis"
      width={520}
      footer={
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          {current > 0 && (
            <Button onClick={handlePrev}>上一步</Button>
          )}
          <div style={{ marginLeft: "auto" }}>
            {current < steps.length - 1 ? (
              <Button type="primary" onClick={handleNext}>
                下一步
              </Button>
            ) : (
              <Button type="primary" onClick={handleSubmit} loading={loading}>
                开始使用
              </Button>
            )}
          </div>
        </div>
      }
      onCancel={onCancel}
      closable={false}
      maskClosable={false}
    >
      <Steps current={current} items={steps} style={{ marginBottom: 24 }} />
      {renderStepContent()}
    </Modal>
  );
};

export default OnboardingModal;
