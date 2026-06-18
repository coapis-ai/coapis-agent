import React from 'react';
import { Card, Select, Typography, Tag, Space } from 'antd';
import { ToolOutlined } from '@ant-design/icons';

const { Text } = Typography;

const SCENE_OPTIONS = [
  { value: null, label: '自动检测', desc: '根据用户消息自动匹配场景' },
  { value: 'coding', label: '编码', desc: '代码编写、调试、测试、Git' },
  { value: 'ops', label: '运维', desc: '部署、监控、日志、系统管理' },
  { value: 'data', label: '数据', desc: '数据分析、数据库、缓存、队列' },
  { value: 'security', label: '安全', desc: '密钥扫描、漏洞审计、加密' },
  { value: 'ai', label: 'AI', desc: 'LLM、Prompt、向量、知识库' },
  { value: 'collaboration', label: '协作', desc: '通知、共享、任务分发' },
];

const SCENE_COLORS: Record<string, string> = {
  coding: 'blue',
  ops: 'green',
  data: 'orange',
  security: 'red',
  ai: 'purple',
  collaboration: 'cyan',
};

interface SceneSelectorProps {
  value: string | null;
  onChange: (value: string | null) => void;
}

export const SceneSelector: React.FC<SceneSelectorProps> = ({ value, onChange }) => {
  return (
    <Card
      size="small"
      title={
        <Space>
          <ToolOutlined />
          <span>工具场景偏好</span>
        </Space>
      }
      style={{ marginBottom: 16 }}
    >
      <div style={{ marginBottom: 8 }}>
        <Text type="secondary">
          选择场景后，Agent 只加载该场景相关的工具，减少 token 消耗。
        </Text>
      </div>
      <Select
        style={{ width: '100%' }}
        placeholder="选择场景"
        value={value}
        onChange={onChange}
        allowClear
        options={SCENE_OPTIONS.map(opt => ({
          value: opt.value,
          label: (
            <Space>
              {opt.value && <Tag color={SCENE_COLORS[opt.value]}>{opt.value}</Tag>}
              <span>{opt.label}</span>
              <Text type="secondary" style={{ fontSize: 12 }}>- {opt.desc}</Text>
            </Space>
          ),
        }))}
      />
    </Card>
  );
};

export default SceneSelector;
