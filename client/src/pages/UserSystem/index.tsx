import React, { useState, useEffect } from 'react';
import {
  Card,
  Row,
  Col,
  Statistic,
  Table,
  Tag,
  Badge,
  Button,
  Space,
  Input,
  Modal,
  Form,
  message,
  Tabs,
  Progress,
  Descriptions,
  Empty,
} from 'antd';
import {
  UserOutlined,
  TrophyOutlined,
  ThunderboltOutlined,
  CloudServerOutlined,
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import {
  listUsers,
  registerUser,
  getTokenSummary,
  getUsersConfig,
} from '@/api/modules/user_system';
import styles from './index.module.css';

const { Search } = Input;

const UserSystemPage: React.FC = () => {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(false);
  const [users, setUsers] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [searchText, setSearchText] = useState('');
  const [config, setConfig] = useState<any>(null);
  const [summaryModal, setSummaryModal] = useState<{ visible: boolean; user: any }>({
    visible: false,
    user: null,
  });
  const [registerModal, setRegisterModal] = useState(false);
  const [registerForm] = Form.useForm();
  const [selectedTab, setSelectedTab] = useState('users');

  // Load config
  useEffect(() => {
    getUsersConfig().catch(() => ({ enabled: false })).then((cfg) => {
      setConfig(cfg);
    });
  }, []);

  // Load users
  const loadUsers = async () => {
    setLoading(true);
    try {
      const res: any = await listUsers(page, pageSize);
      setUsers(res.users || []);
      setTotal(res.total || 0);
    } catch (e: any) {
      message.error(t('usersystem.loadFailed'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadUsers();
  }, [page, pageSize]);

  // Get level color
  const getLevelColor = (level: number) => {
    const colors = ['default', 'blue', 'green', 'orange', 'red'];
    return colors[level] || 'default';
  };

  // Get level name
  const getLevelName = (level: number) => {
    return `L${level}`;
  };

  // User table columns
  const userColumns = [
    {
      title: t('usersystem.username'),
      dataIndex: 'username',
      key: 'username',
      render: (text: string) => <strong>{text}</strong>,
    },
    {
      title: t('usersystem.display_name'),
      dataIndex: 'display_name',
      key: 'display_name',
    },
    {
      title: t('usersystem.level'),
      dataIndex: 'level',
      key: 'level',
      render: (level: number) => (
        <Tag color={getLevelColor(level)}>{getLevelName(level)}</Tag>
      ),
    },
    {
      title: t('usersystem.points'),
      dataIndex: 'points',
      key: 'points',
      sorter: (a: any, b: any) => a.points - b.points,
      render: (points: number) => (
        <Space>
          <TrophyOutlined style={{ color: '#faad14' }} />
          {points}
        </Space>
      ),
    },
    {
      title: t('usersystem.token_usage'),
      key: 'token_usage',
      render: (_: any, record: any) => {
        const quota = record.token_quota_monthly || 0;
        const percent = quota > 0 ? (record.token_used_monthly / quota) * 100 : 0;
        return (
          <Space direction="vertical" size={0}>
            <Progress
              percent={Math.min(100, Math.round(percent))}
              size="small"
              strokeColor={percent > 80 ? '#ff4d4f' : '#52c41a'}
              showInfo={false}
            />
            <span style={{ fontSize: 12, color: '#888' }}>
              {record.token_used_monthly.toLocaleString()} / {quota === -1 ? '∞' : quota.toLocaleString()}
            </span>
          </Space>
        );
      },
    },
    {
      title: t('usersystem.role'),
      dataIndex: 'role',
      key: 'role',
      render: (role: string) => (
        <Tag color={role === 'admin' ? 'red' : 'default'}>{role}</Tag>
      ),
    },
    {
      title: t('usersystem.status'),
      dataIndex: 'is_active',
      key: 'is_active',
      render: (active: boolean) => (
        <Badge
          status={active ? 'success' : 'error'}
          text={active ? t('usersystem.active') : t('usersystem.inactive')}
        />
      ),
    },
    {
      title: t('usersystem.actions'),
      key: 'actions',
      render: (_: any, record: any) => (
        <Space>
          <Button
            type="link"
            size="small"
            onClick={() => showSummary(record)}
          >
            {t('usersystem.details')}
          </Button>
        </Space>
      ),
    },
  ];

  // Show user summary modal
  const showSummary = async (user: any) => {
    try {
      const summary: any = await getTokenSummary(user.username);
      setSummaryModal({ visible: true, user: { ...user, summary } });
    } catch {
      setSummaryModal({ visible: true, user: { ...user, summary: null } });
    }
  };

  // Register new user
  const handleRegister = async () => {
    const values = await registerForm.validateFields();
    try {
      await registerUser(values);
      message.success(t('usersystem.registerSuccess'));
      setRegisterModal(false);
      registerForm.resetFields();
      loadUsers();
    } catch (e: any) {
      message.error(e?.message || t('usersystem.registerFailed'));
    }
  };

  // Summary tab content
  const summaryContent = () => {
    if (!summaryModal.user?.summary) {
      return <Empty description={t('usersystem.noData')} />;
    }
    const s = summaryModal.user.summary;
    return (
      <div>
        <Descriptions column={2} bordered size="small">
          <Descriptions.Item label={t('usersystem.quota')}>
            {s.quota_monthly === -1 ? '∞' : s.quota_monthly.toLocaleString()}
          </Descriptions.Item>
          <Descriptions.Item label={t('usersystem.used')}>
            {s.used_monthly.toLocaleString()}
          </Descriptions.Item>
          <Descriptions.Item label={t('usersystem.remaining')}>
            {s.remaining === -1 ? '∞' : s.remaining.toLocaleString()}
          </Descriptions.Item>
          <Descriptions.Item label={t('usersystem.usage_percent')}>
            <Progress
              percent={Math.round(s.usage_percent)}
              size="small"
              strokeColor={s.usage_percent > 80 ? '#ff4d4f' : '#52c41a'}
            />
          </Descriptions.Item>
          <Descriptions.Item label={t('usersystem.total_input')}>
            {s.total_input_tokens.toLocaleString()}
          </Descriptions.Item>
          <Descriptions.Item label={t('usersystem.total_output')}>
            {s.total_output_tokens.toLocaleString()}
          </Descriptions.Item>
        </Descriptions>

        {s.top_models && s.top_models.length > 0 && (
          <div style={{ marginTop: 16 }}>
            <h4>{t('usersystem.top_models')}</h4>
            <Table
              dataSource={s.top_models}
              size="small"
              pagination={false}
              columns={[
                { title: 'Model', dataIndex: 'model', key: 'model' },
                { title: t('usersystem.requests'), dataIndex: 'requests', key: 'requests' },
                { title: t('usersystem.input_tokens'), dataIndex: 'input_tokens', key: 'input_tokens' },
                { title: t('usersystem.output_tokens'), dataIndex: 'output_tokens', key: 'output_tokens' },
              ]}
            />
          </div>
        )}
      </div>
    );
  };

  // Stats cards
  const statsCards = () => {
    const totalUsers = total;
    const totalPoints = users.reduce((sum: number, u: any) => sum + (u.points || 0), 0);
    const totalTokens = users.reduce((sum: number, u: any) => sum + (u.token_used_monthly || 0), 0);
    const activeUsers = users.filter((u: any) => u.is_active).length;

    return (
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card>
            <Statistic
              title={t('usersystem.total_users')}
              value={totalUsers}
              prefix={<UserOutlined />}
              valueStyle={{ color: '#1890ff' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title={t('usersystem.active_users')}
              value={activeUsers}
              prefix={<ThunderboltOutlined />}
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title={t('usersystem.total_points')}
              value={totalPoints}
              prefix={<TrophyOutlined />}
              valueStyle={{ color: '#faad14' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title={t('usersystem.total_tokens')}
              value={totalTokens}
              precision={0}
              prefix={<CloudServerOutlined />}
              valueStyle={{ color: '#722ed1' }}
            />
          </Card>
        </Col>
      </Row>
    );
  };

  if (!config?.enabled) {
    return (
      <div className={styles.pageContainer}>
        <Card>
          <Empty
            description={t('usersystem.disabled')}
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          />
        </Card>
      </div>
    );
  }

  return (
    <div className={styles.pageContainer}>
      <div className={styles.pageHeader}>
        <h2>{t('usersystem.title')}</h2>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => setRegisterModal(true)}
        >
          {t('usersystem.register')}
        </Button>
      </div>

      {statsCards()}

      <Tabs
        activeKey={selectedTab}
        onChange={setSelectedTab}
        items={[
          {
            key: 'users',
            label: t('usersystem.users'),
            children: (
              <Card>
                <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
                  <Col>
                    <Search
                      placeholder={t('usersystem.search')}
                      allowClear
                      enterButton={<SearchOutlined />}
                      style={{ width: 300 }}
                      value={searchText}
                      onChange={(e) => setSearchText(e.target.value)}
                    />
                  </Col>
                  <Col>
                    <Button icon={<ReloadOutlined />} onClick={loadUsers}>
                      {t('usersystem.refresh')}
                    </Button>
                  </Col>
                </Row>

                <Table
                  columns={userColumns}
                  dataSource={users}
                  loading={loading}
                  rowKey="username"
                  pagination={{
                    current: page,
                    pageSize,
                    total,
                    showSizeChanger: true,
                    showTotal: (totalCount) => `${t('usersystem.total', { total: totalCount })}`,
                    onChange: (p, ps) => {
                      setPage(p);
                      setPageSize(ps);
                    },
                  }}
                />
              </Card>
            ),
          },
        ]}
      />

      {/* User Summary Modal */}
      <Modal
        title={t('usersystem.userDetails', { username: summaryModal.user?.username })}
        open={summaryModal.visible}
        onCancel={() => setSummaryModal({ visible: false, user: null })}
        footer={null}
        width={700}
      >
        {summaryContent()}
      </Modal>

      {/* Register Modal */}
      <Modal
        title={t('usersystem.register')}
        open={registerModal}
        onOk={handleRegister}
        onCancel={() => {
          setRegisterModal(false);
          registerForm.resetFields();
        }}
      >
        <Form form={registerForm} layout="vertical">
          <Form.Item
            name="username"
            label={t('usersystem.username')}
            rules={[{ required: true, message: t('usersystem.usernameRequired') }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="password"
            label={t('usersystem.password')}
            rules={[{ required: true, message: t('usersystem.passwordRequired') }, { min: 6 }]}
          >
            <Input.Password />
          </Form.Item>
          <Form.Item name="email" label={t('usersystem.email')}>
            <Input type="email" />
          </Form.Item>
          <Form.Item name="display_name" label={t('usersystem.display_name')}>
            <Input />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default UserSystemPage;
