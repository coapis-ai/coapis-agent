import { useState, useEffect } from 'react';
import { Card, Row, Col, Statistic, Table, Tag, Button, Space, Tabs, Alert, Spin, Select, message, Modal, Input, Progress, Empty } from 'antd';
import {
  ThunderboltOutlined,
  GlobalOutlined,
  UserOutlined,
  DatabaseOutlined,
  ArrowUpOutlined,
  ArrowDownOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  ReloadOutlined,
  FilterOutlined,
  FileTextOutlined,
  DeleteOutlined,
  BarChartOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { useUser } from '@/contexts/UserContext';
import { useModuleAccess } from '@/hooks/useModuleAccess';
import {
  getEvolutionOverview,
  getUserEvolutionStatus,
  listUserExperiences,
  getBucketA,
  getBucketB,
  reviewExperience,
  listFoundationEntries,
  promoteToFoundation,
  demoteFromFoundation,
  listArchivedEntries,
  cleanupExpiredArchives,
  type EvolutionOverview,
  type UserEvolutionStatus,
  type ExperienceEntry,
  type BucketEntry,
  type FoundationEntry,
} from '@/api/modules/multi_layer_evolution';
import { skillApi } from '@/api/modules/skill';
import styles from './index.module.css';

export default function MultiLayerEvolutionPage() {
  const { t } = useTranslation();
  const { user, isAdmin } = useUser();
  const { isAllowed } = useModuleAccess();
  const [activeTab, setActiveTab] = useState('overview');
  const [selectedUser, setSelectedUser] = useState<string>(user?.username || '');
  const [users, setUsers] = useState<Array<{ username: string; label: string }>>([]);

  const loadUsers = async () => {
    try {
      const overview = await getEvolutionOverview();
      const userList = overview.users.map((u) => ({
        username: u.username,
        label: `${u.username} (${u.experience_count}经验)`,
      }));
      setUsers([{ username: 'all', label: '全部用户' }, ...userList]);
      if (!selectedUser) setSelectedUser('all');
    } catch (e) {
      console.error('Failed to load users:', e);
    }
  };

  useEffect(() => {
    if (isAdmin) {
      loadUsers();
    } else if (user?.username) {
      setSelectedUser(user.username);
    }
  }, [isAdmin, user]);

  // Route guard — deny access if evolution module not allowed
  if (!isAllowed('evolution')) {
    return (
      <div style={{ padding: 48, textAlign: 'center' }}>
        <Alert
          type="error"
          showIcon
          message={t('admin.accessDenied', 'Access Denied')}
          description={t('admin.accessDeniedDesc', 'You do not have permission to access this page.')}
          style={{ maxWidth: 600, margin: '80px auto' }}
        />
      </div>
    );
  }

  const tabItems = [
    {
      key: 'overview',
      label: <><GlobalOutlined /> {t('evolution.overview', '概览')}</>,
      children: <OverviewTab selectedUser={selectedUser} />,
    },
    {
      key: 'user-level',
      label: <><UserOutlined /> {t('evolution.userLevel', '用户级进化')}</>,
      children: <UserLevelTab selectedUser={selectedUser} />,
    },
    {
      key: 'middle-layer',
      label: <><DatabaseOutlined /> {t('evolution.middleLayer', '中间层')}</>,
      children: <MiddleLayerTab selectedUser={selectedUser} isAdmin={isAdmin} />,
    },
    {
      key: 'foundation',
      label: <><ArrowUpOutlined /> {t('evolution.foundation', '全局基础层')}</>,
      children: <FoundationTab isAdmin={isAdmin} />,
    },
    {
      key: 'archive',
      label: <><FileTextOutlined /> {t('evolution.archive', '归档管理')}</>,
      children: <ArchiveTab />,
    },
    {
      key: 'skill-evolution',
      label: <><BarChartOutlined /> {t('evolution.skillEvolution', '技能进化')}</>,
      children: <SkillEvolutionTab />,
    },
  ];

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h1 className={styles.title}>
          <ThunderboltOutlined /> {t('evolution.title', '多层 Agent 进化')}
        </h1>
        <p className={styles.description}>
          {t('evolution.description', '监控和管理智能体的自我进化能力，从个人经验到全局知识的多层流动')}
        </p>
      </div>

      {isAdmin && users.length > 0 && (
        <div className={styles.userSelector}>
          <FilterOutlined />
          <span>{t('evolution.filterByUser', '按用户筛选')}:</span>
          <Select
            value={selectedUser}
            onChange={setSelectedUser}
            style={{ width: 250 }}
            options={users}
          />
        </div>
      )}

      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        type="card"
        size="large"
        items={tabItems}
      />
    </div>
  );
}

// =================================================================
// Overview Tab
// =================================================================

function OverviewTab({ selectedUser }: { selectedUser: string }) {
  const { t } = useTranslation();
  const [overview, setOverview] = useState<EvolutionOverview | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadOverview();
  }, [selectedUser]);

  const loadOverview = async () => {
    setLoading(true);
    try {
      const data = await getEvolutionOverview();
      setOverview(data);
    } catch (e) {
      message.error(t('evolution.fetchFailed', '获取进化数据失败'));
    } finally {
      setLoading(false);
    }
  };

  if (loading) return <Spin size="large" style={{ marginTop: 40 }} />;

  return (
    <Card>
      <Row gutter={16}>
        <Col span={6}>
          <Statistic
            title={t('evolution.totalExperiences', '总经验数')}
            value={overview?.total_experiences || 0}
            prefix={<ThunderboltOutlined />}
          />
        </Col>
        <Col span={6}>
          <Statistic
            title={t('evolution.promotedCount', '已晋升数')}
            value={overview?.promoted_count || 0}
            prefix={<ArrowUpOutlined />}
            valueStyle={{ color: '#3f8600' }}
          />
        </Col>
        <Col span={6}>
          <Statistic
            title={t('evolution.promotionRate', '晋升率')}
            value={overview?.promotion_rate || 0}
            suffix="%"
            precision={1}
            valueStyle={{ color: '#1890ff' }}
          />
        </Col>
        <Col span={6}>
          <Statistic
            title={t('evolution.activeUsers', '活跃用户')}
            value={overview?.active_users || 0}
            prefix={<UserOutlined />}
          />
        </Col>
      </Row>

      <Row gutter={16} style={{ marginTop: 24 }}>
        <Col span={12}>
          <Card size="small" title={t('evolution.bucketStats', '中间层统计')}>
            <Row gutter={16}>
              <Col span={12}>
                <Statistic
                  title={t('evolution.bucketB', 'B桶 (待审核)')}
                  value={overview?.bucket_b_count || 0}
                  valueStyle={{ color: '#faad14' }}
                />
              </Col>
              <Col span={12}>
                <Statistic
                  title={t('evolution.bucketA', 'A桶 (已纳入)')}
                  value={overview?.bucket_a_count || 0}
                  valueStyle={{ color: '#3f8600' }}
                />
              </Col>
            </Row>
          </Card>
        </Col>
        <Col span={12}>
          <Card size="small" title={t('evolution.userStats', '用户统计')}>
            <Table
              size="small"
              dataSource={overview?.users || []}
              rowKey="username"
              pagination={false}
              columns={[
                { title: t('evolution.user', '用户'), dataIndex: 'username', key: 'username' },
                { title: t('evolution.agentCount', 'Agent数'), dataIndex: 'agent_count', key: 'agent_count' },
                { title: t('evolution.experienceCount', '经验数'), dataIndex: 'experience_count', key: 'experience_count' },
                { title: t('evolution.promotedCount', '已晋升'), dataIndex: 'promoted_count', key: 'promoted_count' },
              ]}
            />
          </Card>
        </Col>
      </Row>
    </Card>
  );
}

// =================================================================
// User Level Tab
// =================================================================

function UserLevelTab({ selectedUser }: { selectedUser: string }) {
  const { t } = useTranslation();
  const [status, setStatus] = useState<UserEvolutionStatus | null>(null);
  const [experiences, setExperiences] = useState<ExperienceEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [expStatus, setExpStatus] = useState('all');

  useEffect(() => {
    if (selectedUser && selectedUser !== 'all') {
      loadData();
    }
  }, [selectedUser, expStatus]);

  const loadData = async () => {
    setLoading(true);
    try {
      const [statusData, expData] = await Promise.all([
        getUserEvolutionStatus(selectedUser),
        listUserExperiences(selectedUser, expStatus),
      ]);
      setStatus(statusData);
      setExperiences(expData.experiences || []);
    } catch (e) {
      message.error(t('evolution.fetchFailed', '获取数据失败'));
    } finally {
      setLoading(false);
    }
  };

  if (loading) return <Spin size="large" style={{ marginTop: 40 }} />;
  if (!selectedUser || selectedUser === 'all') {
    return <Alert message={t('evolution.selectUser', '请选择一个用户查看其进化状态')} type="info" showIcon />;
  }

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      <Row gutter={16}>
        <Col span={6}>
          <Statistic title={t('evolution.totalExperiences', '总经验数')} value={status?.total_experiences || 0} />
        </Col>
        <Col span={6}>
          <Statistic title={t('evolution.pending', '待审核')} value={status?.total_pending || 0} valueStyle={{ color: '#faad14' }} />
        </Col>
        <Col span={6}>
          <Statistic title={t('evolution.approved', '已通过')} value={status?.total_approved || 0} valueStyle={{ color: '#3f8600' }} />
        </Col>
        <Col span={6}>
          <Statistic title={t('evolution.rejected', '已拒绝')} value={status?.total_rejected || 0} valueStyle={{ color: '#ff4d4f' }} />
        </Col>
      </Row>

      <Card title={t('evolution.experiences', '经验列表')}>
        <Space style={{ marginBottom: 16 }}>
          <Select value={expStatus} onChange={setExpStatus} style={{ width: 120 }}>
            <Select.Option value="all">{t('common.all', '全部')}</Select.Option>
            <Select.Option value="pending">{t('evolution.pending', '待审核')}</Select.Option>
            <Select.Option value="approved">{t('evolution.approved', '已通过')}</Select.Option>
            <Select.Option value="rejected">{t('evolution.rejected', '已拒绝')}</Select.Option>
          </Select>
          <Button icon={<ReloadOutlined />} onClick={loadData}>
            {t('common.refresh', '刷新')}
          </Button>
        </Space>
        <Table
          size="small"
          dataSource={experiences}
          rowKey="id"
          pagination={false}
          columns={[
            { title: 'ID', dataIndex: 'id', key: 'id', width: 100, render: (id: string) => id?.slice(0, 8) },
            { title: t('evolution.content', '内容'), dataIndex: 'content', key: 'content', ellipsis: true },
            { title: t('evolution.category', '分类'), dataIndex: 'category', key: 'category', width: 100 },
            { title: t('evolution.sourceAgent', '来源Agent'), dataIndex: 'source_agent', key: 'source_agent', width: 120 },
            { title: t('evolution.confidence', '置信度'), dataIndex: 'confidence', key: 'confidence', width: 80, render: (v: number) => `${(v * 100).toFixed(0)}%` },
            {
              title: t('evolution.status', '状态'),
              dataIndex: 'status',
              key: 'status',
              width: 100,
              render: (status: string) => {
                const map: Record<string, { color: string; text: string }> = {
                  pending: { color: 'orange', text: t('evolution.pending', '待审核') },
                  approved: { color: 'green', text: t('evolution.approved', '已通过') },
                  rejected: { color: 'red', text: t('evolution.rejected', '已拒绝') },
                  promoted: { color: 'blue', text: t('evolution.promoted', '已晋升') },
                };
                const s = map[status] || { color: 'default', text: status };
                return <Tag color={s.color}>{s.text}</Tag>;
              },
            },
            { title: t('evolution.createdAt', '创建时间'), dataIndex: 'created_at', key: 'created_at', width: 160 },
          ]}
        />
      </Card>
    </Space>
  );
}

// =================================================================
// Middle Layer Tab (with promote button for Admin)
// =================================================================

function MiddleLayerTab({ selectedUser, isAdmin }: { selectedUser: string; isAdmin: boolean }) {
  const { t } = useTranslation();
  const [activeBucket, setActiveBucket] = useState('a');
  const [bucketA, setBucketA] = useState<BucketEntry[]>([]);
  const [bucketB, setBucketB] = useState<BucketEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterStatus, setFilterStatus] = useState('all');

  useEffect(() => {
    loadData();
  }, [activeBucket, filterStatus, selectedUser]);

  const loadData = async () => {
    setLoading(true);
    try {
      const [aData, bData] = await Promise.all([
        getBucketA(filterStatus, selectedUser === 'all' ? undefined : selectedUser),
        getBucketB(filterStatus, selectedUser === 'all' ? undefined : selectedUser),
      ]);
      setBucketA(aData.entries || []);
      setBucketB(bData.entries || []);
    } catch (e) {
      message.error(t('evolution.fetchFailed', '获取数据失败'));
    } finally {
      setLoading(false);
    }
  };

  const handleReview = (id: string, action: 'approve' | 'reject') => {
    const comment = prompt(action === 'approve' ? t('evolution.approveComment', '审核通过备注（可选）:') : t('evolution.rejectComment', '拒绝原因:'));
    reviewExperience(id, action, comment || '').then(() => {
      message.success(t('evolution.reviewed', '审核完成'));
      loadData();
    }).catch(() => {
      message.error(t('evolution.reviewFailed', '审核失败'));
    });
  };

  const handlePromote = (id: string) => {
    Modal.confirm({
      title: t('evolution.promoteConfirm', '确认晋升到全局基础层'),
      content: (
        <Input.TextArea
          placeholder={t('evolution.promotionComment', '晋升备注（可选）')}
          rows={3}
          onPressEnter={(e: any) => e.stopPropagation()}
        />
      ),
      onOk: () => {
        return promoteToFoundation(id, '').then(() => {
          message.success(t('evolution.promoted', '晋升成功'));
          loadData();
        }).catch(() => {
          message.error(t('evolution.promoteFailed', '晋升失败'));
        });
      },
    });
  };

  if (loading) return <Spin size="large" style={{ marginTop: 40 }} />;

  const currentData = activeBucket === 'a' ? bucketA : bucketB;

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      <Alert
        type="info"
        showIcon
        message={t('evolution.middleLayerDesc', '中间层包含双桶机制：B桶(待审核) → A桶(已纳入)')}
      />

      <Space>
        <Button
          type={activeBucket === 'b' ? 'primary' : 'default'}
          onClick={() => setActiveBucket('b')}
        >
          {t('evolution.bucketB', 'B桶')} ({bucketB.length} {t('evolution.pending', '待审核')})
        </Button>
        <Button
          type={activeBucket === 'a' ? 'primary' : 'default'}
          onClick={() => setActiveBucket('a')}
        >
          {t('evolution.bucketA', 'A桶')} ({bucketA.length} {t('evolution.reviewed', '已审核')})
        </Button>
        <Select value={filterStatus} onChange={setFilterStatus} style={{ width: 120 }}>
          <Select.Option value="all">{t('common.all', '全部')}</Select.Option>
          <Select.Option value="pending">{t('evolution.pending', '待审核')}</Select.Option>
          <Select.Option value="reviewed">{t('evolution.reviewed', '已审核')}</Select.Option>
        </Select>
        <Button icon={<ReloadOutlined />} onClick={loadData}>{t('common.refresh', '刷新')}</Button>
      </Space>

      <Table
        size="small"
        dataSource={currentData}
        rowKey="id"
        pagination={false}
        columns={[
          { title: 'ID', dataIndex: 'id', key: 'id', width: 100, render: (id: string) => id?.slice(0, 8) },
          { title: t('evolution.content', '内容'), dataIndex: 'content', key: 'content', ellipsis: true },
          { title: t('evolution.category', '分类'), dataIndex: 'category', key: 'category', width: 100 },
          { title: t('evolution.sourceUser', '来源用户'), dataIndex: 'source_user', key: 'source_user', width: 100 },
          { title: t('evolution.sourceAgent', '来源Agent'), dataIndex: 'source_agent', key: 'source_agent', width: 120 },
          { title: t('evolution.confidence', '置信度'), dataIndex: 'confidence', key: 'confidence', width: 80, render: (v: number) => `${(v * 100).toFixed(0)}%` },
          {
            title: t('evolution.status', '状态'),
            dataIndex: 'status',
            key: 'status',
            width: 100,
            render: (status: string) => {
              const map: Record<string, { color: string; text: string }> = {
                pending: { color: 'orange', text: t('evolution.pending', '待审核') },
                reviewed: { color: 'blue', text: t('evolution.reviewed', '已审核') },
                promoted: { color: 'green', text: t('evolution.promoted', '已晋升') },
                rejected: { color: 'red', text: t('evolution.rejected', '已拒绝') },
              };
              const s = map[status] || { color: 'default', text: status };
              return <Tag color={s.color}>{s.text}</Tag>;
            },
          },
          {
            title: t('evolution.actions', '操作'),
            key: 'action',
            width: 180,
            render: (_: any, record: BucketEntry) => {
              if (record.status === 'pending') {
                return (
                  <Space>
                    <Button size="small" type="primary" icon={<CheckCircleOutlined />} onClick={() => handleReview(record.id, 'approve')}>
                      {t('evolution.approve', '通过')}
                    </Button>
                    <Button size="small" danger icon={<CloseCircleOutlined />} onClick={() => handleReview(record.id, 'reject')}>
                      {t('evolution.reject', '拒绝')}
                    </Button>
                  </Space>
                );
              }
              if (record.status === 'approved' && isAdmin) {
                return (
                  <Button size="small" type="primary" icon={<ArrowUpOutlined />} onClick={() => handlePromote(record.id)}>
                    {t('evolution.promote', '晋升')}
                  </Button>
                );
              }
              return <Tag color="default">{t('evolution.processed', '已处理')}</Tag>;
            },
          },
        ]}
      />
    </Space>
  );
}

// =================================================================
// Foundation Tab (with admin-controlled demote)
// =================================================================

function FoundationTab({ isAdmin }: { isAdmin: boolean }) {
  const { t } = useTranslation();
  const [entries, setEntries] = useState<FoundationEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      const data = await listFoundationEntries();
      setEntries(data.entries || []);
    } catch (e) {
      message.error(t('evolution.fetchFailed', '获取数据失败'));
    } finally {
      setLoading(false);
    }
  };

  const handleDemote = (id: string) => {
    Modal.confirm({
      title: t('evolution.demoteConfirm', '确认从全局基础层降级'),
      content: (
        <Input.TextArea
          placeholder={t('evolution.demotionComment', '降级原因')}
          rows={3}
          onPressEnter={(e: any) => e.stopPropagation()}
        />
      ),
      onOk: () => {
        return demoteFromFoundation(id, '').then(() => {
          message.success(t('evolution.demoted', '降级成功'));
          loadData();
        }).catch(() => {
          message.error(t('evolution.demoteFailed', '降级失败'));
        });
      },
    });
  };

  if (loading) return <Spin size="large" style={{ marginTop: 40 }} />;

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      <Alert
        type="success"
        showIcon
        message={t('evolution.foundationDesc', '全局基础层包含已验证的共性知识，所有用户共享读取')}
      />

      <Space>
        <Button icon={<ReloadOutlined />} onClick={loadData}>{t('common.refresh', '刷新')}</Button>
        <Statistic title={t('evolution.foundationCount', '基础层条目')} value={entries.length} valueStyle={{ color: '#3f8600' }} />
      </Space>

      <Table
        size="small"
        dataSource={entries}
        rowKey="id"
        pagination={false}
        columns={[
          { title: 'ID', dataIndex: 'id', key: 'id', width: 100, render: (id: string) => id?.slice(0, 8) },
          { title: t('evolution.content', '内容'), dataIndex: 'content', key: 'content', ellipsis: true },
          { title: t('evolution.category', '分类'), dataIndex: 'category', key: 'category', width: 100 },
          { title: t('evolution.sourceUser', '来源用户'), dataIndex: 'source_user', key: 'source_user', width: 100 },
          { title: t('evolution.affectedUsers', '影响用户'), dataIndex: 'affected_users', key: 'affected_users', width: 150, render: (users: string[]) => users?.join(', ') || '-' },
          { title: t('evolution.promotedAt', '晋升时间'), dataIndex: 'promoted_at', key: 'promoted_at', width: 160 },
          { title: t('evolution.promotedBy', '晋升操作人'), dataIndex: 'promoted_by', key: 'promoted_by', width: 100 },
          {
            title: t('evolution.actions', '操作'),
            key: 'action',
            width: 120,
            render: (_: any, record: FoundationEntry) =>
              isAdmin ? (
                <Button size="small" danger icon={<ArrowDownOutlined />} onClick={() => handleDemote(record.id)}>
                  {t('evolution.demote', '降级')}
                </Button>
              ) : (
                <Tag color="green">{t('evolution.promoted', '已晋升')}</Tag>
              ),
          },
        ]}
      />
    </Space>
  );
}

// =================================================================
// Archive Tab (Phase 4 new feature)
// =================================================================

function ArchiveTab() {
  const { t } = useTranslation();
  const [entries, setEntries] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);

  const loadData = async () => {
    setLoading(true);
    try {
      const data = await listArchivedEntries(200);
      setEntries(data.entries || []);
      setTotal(data.total || 0);
    } catch (e) {
      message.error(t('evolution.fetchFailed', '获取归档数据失败'));
    } finally {
      setLoading(false);
    }
  };

  const handleCleanup = () => {
    Modal.confirm({
      title: t('evolution.cleanupConfirm', '确认清理过期归档'),
      content: t('evolution.cleanupDesc', '将删除超过保留期的归档文件，此操作不可恢复'),
      onOk: () => {
        return cleanupExpiredArchives().then((res) => {
          message.success(t('evolution.cleaned', `已清理 ${res.cleaned} 个过期归档文件`));
          loadData();
        }).catch(() => {
          message.error(t('evolution.cleanupFailed', '清理失败'));
        });
      },
    });
  };

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      <Alert
        type="warning"
        showIcon
        message={t('evolution.archiveDesc', '归档管理：查看已淘汰或降级的经验条目')}
      />

      <Space>
        <Button icon={<ReloadOutlined />} onClick={loadData} loading={loading}>
          {t('common.refresh', '刷新')}
        </Button>
        <Button danger icon={<DeleteOutlined />} onClick={handleCleanup}>
          {t('evolution.cleanup', '清理过期归档')}
        </Button>
        <Statistic title={t('evolution.archiveCount', '归档条目')} value={total} />
      </Space>

      {entries.length === 0 ? (
        <Alert message={t('evolution.noArchives', '暂无归档数据')} type="info" showIcon />
      ) : (
        <Table
          size="small"
          dataSource={entries}
          rowKey={(r: any) => `${r.id}-${r.created_at}`}
          pagination={{ pageSize: 50 }}
          columns={[
            { title: 'ID', dataIndex: 'id', key: 'id', width: 100, render: (id: string) => id?.slice(0, 8) },
            { title: t('evolution.content', '内容'), dataIndex: 'content', key: 'content', ellipsis: true },
            { title: t('evolution.category', '分类'), dataIndex: 'category', key: 'category', width: 100 },
            { title: t('evolution.sourceUser', '来源用户'), dataIndex: 'source_user', key: 'source_user', width: 100 },
            { title: t('evolution.status', '状态'), dataIndex: 'status', key: 'status', width: 100, render: (s: string) => <Tag>{s}</Tag> },
            { title: t('evolution.createdAt', '创建时间'), dataIndex: 'created_at', key: 'created_at', width: 160 },
          ]}
        />
      )}
    </Space>
  );
}

// ==================== 技能进化 Tab ====================

interface SkillMetric {
  skill_name: string;
  composite_score: number;
  precision: number;
  recall: number;
  reliability: number;
  satisfaction: number;
  total_triggers: number;
  successful_triggers: number;
  failed_triggers: number;
  last_triggered_at: string | null;
}

interface FunnelData {
  skill_name: string;
  funnel: Array<{ stage: string; count: number }>;
}

function SkillEvolutionTab() {
  const [subTab, setSubTab] = useState('dashboard');
  const subItems = [
    { key: 'dashboard', label: <><BarChartOutlined /> 效能看板</>, children: <MetricsDashboard /> },
    { key: 'triggers', label: <><SearchOutlined /> 触发分析</>, children: <TriggerAnalysis /> },
    { key: 'suggestions', label: <><FileTextOutlined /> 改进建议</>, children: <ImprovementSuggestions /> },
    { key: 'promotion', label: <>🚀 晋升/退役</>, children: <PromotionRetirement /> },
  ];
  return <Tabs activeKey={subTab} onChange={setSubTab} type="card" size="small" items={subItems} />;
}

function MetricsDashboard() {
  const [metrics, setMetrics] = useState<SkillMetric[]>([]);
  const [funnel, setFunnel] = useState<FunnelData | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchData = async (refresh = false) => {
    setLoading(true);
    try {
      const data = await skillApi.getSkillMetrics({ refresh }) as any;
      setMetrics(data.metrics || []);
      setFunnel(data.funnel || null);
    } catch {
      message.error('获取效能数据失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchData(); }, []);

  const scoreColor = (v: number) => v >= 0.7 ? '#52c41a' : v >= 0.4 ? '#faad14' : '#ff4d4f';

  const columns = [
    { title: '技能', dataIndex: 'skill_name', key: 'name', width: 120,
      render: (v: string) => <Tag color="blue">{v}</Tag> },
    { title: '综合分', dataIndex: 'composite_score', key: 'score', width: 160, sorter: (a: SkillMetric, b: SkillMetric) => a.composite_score - b.composite_score,
      render: (v: number) => <Progress percent={Math.round(v * 100)} size="small" strokeColor={scoreColor(v)} style={{ width: 100 }} /> },
    { title: '精确度', dataIndex: 'precision', key: 'precision', width: 100, render: (v: number) => <span style={{ color: scoreColor(v) }}>{(v * 100).toFixed(0)}%</span> },
    { title: '可靠性', dataIndex: 'reliability', key: 'reliability', width: 100, render: (v: number) => <span style={{ color: scoreColor(v) }}>{(v * 100).toFixed(0)}%</span> },
    { title: '满意度', dataIndex: 'satisfaction', key: 'satisfaction', width: 100, render: (v: number) => <span style={{ color: scoreColor(v) }}>{(v * 100).toFixed(0)}%</span> },
    { title: '触发次数', dataIndex: 'total_triggers', key: 'triggers', width: 90 },
    { title: '最近触发', dataIndex: 'last_triggered_at', key: 'last', width: 160,
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-' },
  ];

  return (
    <div>
      <Row justify="end" style={{ marginBottom: 12 }}>
        <Button icon={<ReloadOutlined />} loading={loading} onClick={() => fetchData(true)}>
          刷新数据
        </Button>
      </Row>
      {funnel && (
        <Card title="触发漏斗" size="small" style={{ marginBottom: 16 }}>
          <Row gutter={16}>
            {funnel.funnel.map((s, i) => (
              <Col key={i} span={6}>
                <Statistic title={s.stage} value={s.count} />
              </Col>
            ))}
          </Row>
        </Card>
      )}
      <Table
        size="small"
        dataSource={metrics}
        rowKey="skill_name"
        loading={loading}
        columns={columns}
        pagination={false}
        locale={{ emptyText: <Empty description="暂无效能数据" /> }}
      />
    </div>
  );
}

function TriggerAnalysis() {
  const [metrics, setMetrics] = useState<SkillMetric[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const data = await skillApi.getSkillMetrics() as any;
        setMetrics(data.metrics || []);
      } catch { /* silent */ }
      finally { setLoading(false); }
    })();
  }, []);

  const lowPrecision = metrics.filter(m => m.precision < 0.3 && m.total_triggers > 0)
    .sort((a, b) => a.precision - b.precision);
  const lowRecall = metrics.filter(m => m.recall < 0.3 && m.total_triggers > 0)
    .sort((a, b) => a.recall - b.recall);

  return (
    <Spin spinning={loading}>
      <Row gutter={16}>
        <Col span={12}>
          <Card title="误触发 Top 原因（精确度低）" size="small">
            {lowPrecision.length === 0 ? <Empty description="暂无误触发" /> : (
              <Table size="small" dataSource={lowPrecision} rowKey="skill_name" pagination={false} columns={[
                { title: '技能', dataIndex: 'skill_name', key: 'name' },
                { title: '精确度', dataIndex: 'precision', key: 'p', render: (v: number) => <Tag color="red">{(v * 100).toFixed(0)}%</Tag> },
                { title: '触发次数', dataIndex: 'total_triggers', key: 't' },
              ]} />
            )}
          </Card>
        </Col>
        <Col span={12}>
          <Card title="漏触发 Top 原因（召回率低）" size="small">
            {lowRecall.length === 0 ? <Empty description="暂无漏触发" /> : (
              <Table size="small" dataSource={lowRecall} rowKey="skill_name" pagination={false} columns={[
                { title: '技能', dataIndex: 'skill_name', key: 'name' },
                { title: '召回率', dataIndex: 'recall', key: 'r', render: (v: number) => <Tag color="orange">{(v * 100).toFixed(0)}%</Tag> },
                { title: '触发次数', dataIndex: 'total_triggers', key: 't' },
              ]} />
            )}
          </Card>
        </Col>
      </Row>
    </Spin>
  );
}

function ImprovementSuggestions() {
  const [suggestions, setSuggestions] = useState<Array<Record<string, unknown>>>([]);
  const [loading, setLoading] = useState(false);

  const fetchData = async () => {
    setLoading(true);
    try {
      const data = await skillApi.getSkillSuggestions({ status: 'pending' }) as any;
      setSuggestions(data.suggestions || []);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchData(); }, []);

  const handleApprove = async (id: string) => {
    try {
      await skillApi.approveSuggestion(id);
      message.success('已审批通过');
      fetchData();
    } catch {
      message.error('审批失败');
    }
  };

  const handleReject = async (id: string) => {
    try {
      await skillApi.rejectSuggestion(id);
      message.success('已拒绝');
      fetchData();
    } catch {
      message.error('操作失败');
    }
  };

  const columns = [
    { title: '技能', dataIndex: 'skill_name', key: 'name', width: 120, render: (v: string) => <Tag color="blue">{v}</Tag> },
    { title: '类型', dataIndex: 'type', key: 'type', width: 140, render: (v: string) => <Tag color={v === 'trigger_optimization' ? 'orange' : 'green'}>{v === 'trigger_optimization' ? '触发词优化' : '内容改进'}</Tag> },
    { title: '详情', key: 'detail', render: (_: unknown, r: Record<string, unknown>) => {
      if (r.type === 'trigger_optimization') {
        return <span>移除: {(r.removes as string[])?.join(', ') || '-'} | 添加: {(r.adds as string[])?.join(', ') || '-'}</span>;
      }
      return <span>{(r.improvements as string[])?.join('; ') || '-'}</span>;
    }},
    { title: '状态', dataIndex: 'status', key: 'status', width: 80, render: (v: string) => <Tag color={v === 'pending' ? 'gold' : v === 'approved' ? 'green' : 'red'}>{v}</Tag> },
    { title: '操作', key: 'action', width: 150, render: (_: unknown, r: Record<string, unknown>) =>
      r.status === 'pending' ? (
        <Space>
          <Button size="small" type="primary" onClick={() => handleApprove(r.id as string)}>通过</Button>
          <Button size="small" danger onClick={() => handleReject(r.id as string)}>拒绝</Button>
        </Space>
      ) : '-'
    },
  ];

  return (
    <div>
      <Row justify="end" style={{ marginBottom: 12 }}>
        <Button icon={<ReloadOutlined />} loading={loading} onClick={fetchData}>刷新</Button>
      </Row>
      <Table dataSource={suggestions} columns={columns} rowKey="id" size="small" pagination={false} />
    </div>
  );
}

function PromotionRetirement() {
  const [promotionCandidates, setPromotionCandidates] = useState<Array<Record<string, unknown>>>([]);
  const [retirementCandidates, setRetirementCandidates] = useState<Array<Record<string, unknown>>>([]);
  const [loading, setLoading] = useState(false);
  const [subView, setSubView] = useState<'promotion' | 'retirement'>('promotion');

  const fetchData = async () => {
    setLoading(true);
    try {
      const [promo, retire] = await Promise.all([
        skillApi.getPromotionCandidates(),
        skillApi.getRetirementCandidates(),
      ]);
      setPromotionCandidates(promo.candidates || []);
      setRetirementCandidates(retire.candidates || []);
    } catch {
      message.error('获取候选数据失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchData(); }, []);

  const handleApprovePromotion = async (skillName: string) => {
    try {
      await skillApi.approvePromotion(skillName);
      message.success(`已批准 ${skillName} 晋升为全局技能`);
      fetchData();
    } catch {
      message.error('操作失败');
    }
  };

  const handleRejectPromotion = async (skillName: string) => {
    try {
      await skillApi.rejectPromotion(skillName);
      message.success(`已拒绝 ${skillName} 的晋升`);
      fetchData();
    } catch {
      message.error('操作失败');
    }
  };

  const promotionColumns = [
    { title: '技能', dataIndex: 'skill_name', key: 'name', width: 120, render: (v: string) => <Tag color="blue">{v}</Tag> },
    { title: '综合分', dataIndex: 'composite_score', key: 'score', width: 100, sorter: (a: Record<string, unknown>, b: Record<string, unknown>) => (a.composite_score as number) - (b.composite_score as number),
      render: (v: number) => <Progress percent={Math.round(v * 100)} size="small" strokeColor={v >= 0.7 ? '#52c41a' : '#faad14'} style={{ width: 80 }} /> },
    { title: '用户数', dataIndex: 'user_count', key: 'users', width: 80 },
    { title: '年龄(天)', dataIndex: 'age_days', key: 'age', width: 90 },
    { title: '触发次数', dataIndex: 'total_triggers', key: 'triggers', width: 90 },
    { title: '状态', dataIndex: 'status', key: 'status', width: 80, render: (v: string) => <Tag color={v === 'pending' ? 'gold' : v === 'approved' ? 'green' : 'red'}>{v}</Tag> },
    { title: '操作', key: 'action', width: 150, render: (_: unknown, r: Record<string, unknown>) =>
      r.status === 'pending' ? (
        <Space>
          <Button size="small" type="primary" onClick={() => handleApprovePromotion(r.skill_name as string)}>晋升</Button>
          <Button size="small" danger onClick={() => handleRejectPromotion(r.skill_name as string)}>拒绝</Button>
        </Space>
      ) : '-'
    },
  ];

  const retirementColumns = [
    { title: '技能', dataIndex: 'skill_name', key: 'name', width: 120, render: (v: string) => <Tag color="red">{v}</Tag> },
    { title: '综合分', dataIndex: 'composite_score', key: 'score', width: 100, render: (v: number) => <span style={{ color: '#ff4d4f' }}>{(v * 100).toFixed(0)}%</span> },
    { title: '距上次触发(天)', dataIndex: 'days_since_last_trigger', key: 'days', width: 130 },
    { title: '连续失败', dataIndex: 'consecutive_failures', key: 'fails', width: 90 },
    { title: '退役原因', dataIndex: 'reasons', key: 'reasons', render: (v: string[]) => v?.join('；') || '-' },
    { title: '状态', dataIndex: 'status', key: 'status', width: 80, render: (v: string) => <Tag color={v === 'pending' ? 'gold' : v === 'approved' ? 'green' : 'default'}>{v}</Tag> },
  ];

  return (
    <div>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Space>
          <Button type={subView === 'promotion' ? 'primary' : 'default'} onClick={() => setSubView('promotion')}>
            晋升候选 ({promotionCandidates.length})
          </Button>
          <Button type={subView === 'retirement' ? 'primary' : 'default'} onClick={() => setSubView('retirement')}>
            退役候选 ({retirementCandidates.length})
          </Button>
        </Space>
        <Button icon={<ReloadOutlined />} loading={loading} onClick={fetchData}>刷新</Button>
      </Row>

      {subView === 'promotion' ? (
        <div>
          <Alert
            message="晋升条件：≥3 用户使用 + 综合效能分≥0.7 + 存在≥30 天"
            type="info"
            showIcon
            style={{ marginBottom: 12 }}
          />
          <Table dataSource={promotionCandidates} columns={promotionColumns} rowKey="skill_name" size="small" pagination={false} />
        </div>
      ) : (
        <div>
          <Alert
            message="退役条件：90 天零触发 或 连续 5 次工具执行失败"
            type="warning"
            showIcon
            style={{ marginBottom: 12 }}
          />
          <Table dataSource={retirementCandidates} columns={retirementColumns} rowKey="skill_name" size="small" pagination={false} />
        </div>
      )}
    </div>
  );
}
