import { Card, Row, Col, Typography, Spin } from 'antd';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useState, useEffect } from 'react';
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
  RocketOutlined,
  UserOutlined,
  SafetyOutlined,
  FileTextOutlined,
  AreaChartOutlined,
  BugOutlined,
} from '@ant-design/icons';
import { permissionsApi } from '../../api/modules/permissions';
import { useUser } from '../../contexts/UserContext';
import { MENU_TO_PERMISSION_MODULE } from '../../config/permissionMapping';
import styles from './index.module.css';

const { Title, Text } = Typography;

/**
 * 设置页面
 * 整合所有管理功能，分为两组：用户管理、系统管理
 * 
 * 权限控制：
 * - 每个功能模块对应一个权限模块
 * - 只有用户有权限的模块才显示
 * - admin 角色拥有所有权限
 */
export default function Settings() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { user } = useUser();
  
  // 权限状态
  const [allowedModules, setAllowedModules] = useState<string[]>([]);
  const [permissionsLoaded, setPermissionsLoaded] = useState(false);

  // 加载权限
  useEffect(() => {
    if (!user) {
      setPermissionsLoaded(true);
      return;
    }
    
    permissionsApi.getAllowedModules()
      .then((res) => {
        setAllowedModules(res.modules || []);
        setPermissionsLoaded(true);
      })
      .catch(() => {
        // Fallback: 如果权限API失败，允许所有模块
        setAllowedModules(['all']);
        setPermissionsLoaded(true);
      });
  }, [user]);

  // 检查模块权限
  const isModuleAllowed = (menuKey: string): boolean => {
    if (!permissionsLoaded) return true; // 加载中显示
    if (allowedModules.includes('all')) return true; // admin 角色
    
    // 获取对应的权限模块
    const permModule = MENU_TO_PERMISSION_MODULE[menuKey];
    if (!permModule) {
      // 不在权限映射中，默认允许（如设置页面本身）
      return true;
    }
    
    // 检查权限
    return allowedModules.includes(permModule);
  };

  // 过滤功能模块
  const filterFeatures = (features: any[]) => {
    return features.filter(feature => isModuleAllowed(feature.key));
  };

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
      key: 'overview',
      title: '概览',
      description: '系统概览和统计数据',
      icon: <AreaChartOutlined />,
      path: '/admin/overview',
    },
    {
      key: 'users',
      title: '用户管理',
      description: '系统用户管理',
      icon: <UserOutlined />,
      path: '/admin/users',
    },
    {
      key: 'permissions',
      title: '权限管理',
      description: '角色和权限配置',
      icon: <SafetyOutlined />,
      path: '/admin/permissions',
    },
    {
      key: 'audit',
      title: '审计日志',
      description: '系统操作审计日志',
      icon: <FileTextOutlined />,
      path: '/admin/audit',
    },
    {
      key: 'config',
      title: '系统配置',
      description: '系统配置和配额管理',
      icon: <SettingOutlined />,
      path: '/admin/config',
    },
    {
      key: 'scenes',
      title: '场景管理',
      description: '管理系统场景',
      icon: <PlayCircleOutlined />,
      path: '/admin/scenes',
    },
    {
      key: 'tags',
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
      title: t('nav.debug', '调试'),
      description: '调试工具和日志',
      icon: <BugOutlined />,
      path: '/debug',
    },
  ];

  // 过滤后的功能模块
  const filteredUserFeatures = filterFeatures(userFeatures);
  const filteredAdminFeatures = filterFeatures(adminFeatures);

  // 点击卡片导航
  const handleCardClick = (path: string) => {
    navigate(path, { state: { from: '/settings' } });
  };

  // 加载中显示
  if (!permissionsLoaded) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '50vh' }}>
        <Spin tip="加载中..." />
      </div>
    );
  }

  return (
    <div className={styles.settingsPage}>
      {/* 用户管理 */}
      {filteredUserFeatures.length > 0 && (
        <div className={styles.section}>
          <Title level={4} className={styles.sectionTitle}>用户管理</Title>
          <Text type="secondary" className={styles.sectionDesc}>
            管理您的个人资源和配置
          </Text>
          <Row gutter={[16, 16]} className={styles.cardGrid}>
            {filteredUserFeatures.map((feature) => (
              <Col key={feature.key}>
                <Card
                  className={styles.featureCard}
                  hoverable
                  onClick={() => handleCardClick(feature.path)}
                >
                  <div className={styles.cardContent}>
                    <div className={styles.iconWrapper}>
                      {feature.icon}
                    </div>
                    <div className={styles.textWrapper}>
                      <Text strong className={styles.cardTitle}>{feature.title}</Text>
                      <Text type="secondary" className={styles.cardDesc}>{feature.description}</Text>
                    </div>
                  </div>
                </Card>
              </Col>
            ))}
          </Row>
        </div>
      )}

      {/* 系统管理 */}
      {filteredAdminFeatures.length > 0 && (
        <div className={styles.section}>
          <Title level={4} className={styles.sectionTitle}>系统管理</Title>
          <Text type="secondary" className={styles.sectionDesc}>
            系统级管理和配置（需要管理员权限）
          </Text>
          <Row gutter={[16, 16]} className={styles.cardGrid}>
            {filteredAdminFeatures.map((feature) => (
              <Col key={feature.key}>
                <Card
                  className={styles.featureCard}
                  hoverable
                  onClick={() => handleCardClick(feature.path)}
                >
                  <div className={styles.cardContent}>
                    <div className={styles.iconWrapper}>
                      {feature.icon}
                    </div>
                    <div className={styles.textWrapper}>
                      <Text strong className={styles.cardTitle}>{feature.title}</Text>
                      <Text type="secondary" className={styles.cardDesc}>{feature.description}</Text>
                    </div>
                  </div>
                </Card>
              </Col>
            ))}
          </Row>
        </div>
      )}
    </div>
  );
}
