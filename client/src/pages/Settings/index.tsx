import { Card, Row, Col, Typography } from 'antd';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  RobotOutlined,
  ApiOutlined,
  WifiOutlined,
  TeamOutlined,
  ClockCircleOutlined,
  HeartOutlined,
  ThunderboltOutlined,
  ToolOutlined,
  SettingOutlined,
  BarChartOutlined,
  SecurityScanOutlined,
  DollarOutlined,
  SaveOutlined,
  PlayCircleOutlined,
  TagOutlined,
  BugOutlined,
  RocketOutlined,
  CrownOutlined,
  UserOutlined,
  SafetyOutlined,
  FileTextOutlined,
  AreaChartOutlined,
} from '@ant-design/icons';
import styles from './index.module.css';

const { Title, Text } = Typography;

/**
 * 设置页面
 * 整合所有管理功能，分为两组：用户管理、系统管理
 */
export default function Settings() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  // 用户管理（用户级功能）
  const userFeatures = [
    {
      key: 'agents',
      title: t('nav.agents', '智能体管理'),
      description: '管理和配置您的智能体',
      icon: <RobotOutlined />,
      path: '/agents',
    },
    {
      key: 'channels',
      title: t('nav.channels', '频道'),
      description: '频道管理和配置',
      icon: <WifiOutlined />,
      path: '/channels',
    },
    {
      key: 'sessions',
      title: t('nav.sessions', '会话'),
      description: '会话管理和监控',
      icon: <TeamOutlined />,
      path: '/sessions',
    },
    {
      key: 'cron-jobs',
      title: t('nav.cronJobs', '定时任务'),
      description: '定时任务管理',
      icon: <ClockCircleOutlined />,
      path: '/cron-jobs',
    },
    {
      key: 'heartbeat',
      title: t('nav.heartbeat', '心跳'),
      description: '心跳监控和管理',
      icon: <HeartOutlined />,
      path: '/heartbeat',
    },
    {
      key: 'skills',
      title: t('nav.skills', '技能'),
      description: '技能管理和技能池',
      icon: <ThunderboltOutlined />,
      path: '/skills',
    },
    {
      key: 'tools',
      title: t('nav.tools', '工具'),
      description: '工具管理和配置',
      icon: <ToolOutlined />,
      path: '/tools',
    },
    {
      key: 'mcp',
      title: t('nav.mcp', 'MCP'),
      description: 'MCP协议管理',
      icon: <ApiOutlined />,
      path: '/mcp',
    },
    {
      key: 'token-usage',
      title: t('nav.tokenUsage', 'Token消耗'),
      description: 'Token使用量统计',
      icon: <DollarOutlined />,
      path: '/token-usage',
    },
    {
      key: 'backups',
      title: t('nav.backups', '备份与清理'),
      description: '数据备份和清理管理',
      icon: <SaveOutlined />,
      path: '/backups',
    },
  ];

  // 系统管理（系统级功能）
  const adminFeatures = [
    {
      key: 'admin-overview',
      title: '概览',
      description: '系统概览和统计数据',
      icon: <AreaChartOutlined />,
      path: '/admin/overview',
    },
    {
      key: 'admin-users',
      title: '用户管理',
      description: '系统用户管理',
      icon: <UserOutlined />,
      path: '/admin/users',
    },
    {
      key: 'admin-permissions',
      title: '权限管理',
      description: '角色和权限配置',
      icon: <SafetyOutlined />,
      path: '/admin/permissions',
    },
    {
      key: 'admin-audit',
      title: '审计日志',
      description: '系统操作审计日志',
      icon: <FileTextOutlined />,
      path: '/admin/audit',
    },
    {
      key: 'admin-config',
      title: '系统配置',
      description: '系统配置和配额管理',
      icon: <SettingOutlined />,
      path: '/admin/config',
    },
    {
      key: 'scene-management',
      title: '场景管理',
      description: '管理系统场景',
      icon: <PlayCircleOutlined />,
      path: '/admin/scenes',
    },
    {
      key: 'tag-management',
      title: '标签管理',
      description: '管理系统标签',
      icon: <TagOutlined />,
      path: '/admin/tags',
    },
    {
      key: 'models',
      title: t('nav.models', '模型'),
      description: '模型配置和默认模型管理',
      icon: <ApiOutlined />,
      path: '/models',
    },
    {
      key: 'agent-config',
      title: t('nav.agentConfig', '运行配置'),
      description: '智能体运行时配置',
      icon: <SettingOutlined />,
      path: '/agent-config',
    },
    {
      key: 'agent-stats',
      title: t('nav.agentStats', '智能体统计'),
      description: '智能体使用统计和分析',
      icon: <BarChartOutlined />,
      path: '/agent-stats',
    },
    {
      key: 'security',
      title: t('nav.security', '安全'),
      description: '安全设置和密钥管理',
      icon: <SecurityScanOutlined />,
      path: '/security',
    },
    {
      key: 'evolution',
      title: t('nav.evolution', 'Evolution'),
      description: '智能体进化管理',
      icon: <RocketOutlined />,
      path: '/evolution',
    },
    {
      key: 'debug',
      title: t('nav.debug', 'Debug'),
      description: '调试工具和日志',
      icon: <BugOutlined />,
      path: '/debug',
    },
  ];

  const renderFeatureCard = (feature: any) => (
    <Col key={feature.key} style={{ marginBottom: 16 }}>
      <Card
        className={styles.featureCard}
        hoverable
        onClick={() => navigate(feature.path, { state: { from: '/settings' } })}
        style={{ textAlign: 'center', width: 90, height: 90 }}
        bodyStyle={{ padding: '12px 8px' }}
      >
        <div className={styles.iconWrapper}>
          {feature.icon}
        </div>
        <Title level={5} className={styles.cardTitle}>{feature.title}</Title>
      </Card>
    </Col>
  );

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <Title level={2}>设置</Title>
        <Text type="secondary">管理您的智能体、工具和系统配置</Text>
      </div>

      {/* 用户设置 */}
      <div className={styles.section}>
        <Title level={4}>
          <TeamOutlined style={{ marginRight: 8 }} />
          用户设置
        </Title>
        <Row gutter={[16, 16]}>
          {userFeatures.map(renderFeatureCard)}
        </Row>
      </div>

      {/* 系统管理 */}
      <div className={styles.section}>
        <Title level={4}>
          <CrownOutlined style={{ marginRight: 8 }} />
          系统管理
        </Title>
        <Row gutter={[16, 16]}>
          {adminFeatures.map(renderFeatureCard)}
        </Row>
      </div>
    </div>
  );
}
