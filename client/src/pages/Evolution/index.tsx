import { useState, useEffect } from 'react';
import { Card, Row, Col, Statistic, Table, Tag, Button, Space, Modal, Descriptions, Tabs, Alert, Spin, Badge, Progress, Empty, message, Popconfirm, Input, Select } from 'antd';
import {
  ThunderboltOutlined, DatabaseOutlined, ClockCircleOutlined, CheckCircleOutlined,
  CloseCircleOutlined, PlayCircleOutlined, PauseCircleOutlined, ReloadOutlined,
  TrophyOutlined, UnorderedListOutlined, FileTextOutlined, SearchOutlined,
  ArrowUpOutlined, ExperimentOutlined, BarChartOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import {
  getEvolutionStatus,
  listExperiences,
  triggerExtraction,
  approveExperience,
  rejectExperience,
  getKnowledgeFlowStatus,
  listPendingFlows,
  approveFlow,
  rejectFlow,
  getReviewStatus,
  getReviewHistory,
  startReview,
  stopReview,
} from '@/api/modules/evolution';
import { skillApi } from '@/api/modules/skill';
import styles from './index.module.css';

export default function EvolutionPage() {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState('status');

  const tabItems = [
    {
      key: 'status',
      label: <><ThunderboltOutlined /> {t('evolution.status')}</>,
      children: <StatusTab />,
    },
    {
      key: 'experiences',
      label: (
        <span>
          <TrophyOutlined /> {t('evolution.experiences')}
        </span>
      ),
      children: <ExperiencesTab />,
    },
    {
      key: 'knowledge-flow',
      label: (
        <span>
          <ArrowUpOutlined /> {t('evolution.knowledgeFlow')}
        </span>
      ),
      children: <KnowledgeFlowTab />,
    },
    {
      key: 'review',
      label: (
        <span>
          <ExperimentOutlined /> {t('evolution.review')}
        </span>
      ),
      children: <ReviewTab />,
    },
    {
      key: 'skill-evolution',
      label: (
        <span>
          <BarChartOutlined /> 技能进化
        </span>
      ),
      children: <SkillEvolutionTab />,
    },
  ];

  return (
    <div className={styles.evolutionContainer}>
      <h1 className={styles.evolutionTitle}>
        <ThunderboltOutlined /> {t('evolution.title')}
      </h1>

      <Alert
        type="info"
        showIcon
        message={t('evolution.description')}
        description={t('evolution.descriptionDetail')}
        style={{ marginBottom: 24 }}
      />

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

// =========================================================================
// Status Tab
// =========================================================================

function StatusTab() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  const fetchStatus = async () => {
    setLoading(true);
    try {
      const data = await getEvolutionStatus();
      setStatus(data);
    } catch (e: any) {
      message.error(t('evolution.fetchFailed'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchStatus(); }, []);

  if (loading) return <Spin size="large" style={{ marginTop: 40 }} />;

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card>
            <Statistic
              title={t('evolution.enabled')}
              value={status?.enabled ? t('common.yes') : t('common.no')}
              prefix={<ThunderboltOutlined />}
              valueStyle={{ color: status?.enabled ? '#3f8600' : '#cf1322' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title={t('evolution.currentSession')}
              value={status?.current_session || '-'}
              prefix={<FileTextOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title={t('evolution.trajectoryCount')}
              value={status?.trajectory_count ?? 0}
              prefix={<UnorderedListOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title={t('evolution.pendingExperiences')}
              value={status?.pending_experiences ?? 0}
              prefix={<TrophyOutlined />}
              valueStyle={{ color: (status?.pending_experiences ?? 0) > 0 ? '#faad14' : '#3f8600' }}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={16}>
        <Col span={12}>
          <Card title={t('evolution.nudgeIntervals')} bordered={false}>
            <Descriptions column={1} bordered size="small">
              <Descriptions.Item label={t('evolution.memoryNudgeInterval')}>
                {status?.memory_nudge_interval} {t('evolution.turns')}
              </Descriptions.Item>
              <Descriptions.Item label={t('evolution.skillNudgeInterval')}>
                {status?.skill_nudge_interval} {t('evolution.tools')}
              </Descriptions.Item>
              <Descriptions.Item label={t('evolution.turnsSinceMemoryReview')}>
                {status?.turns_since_memory_review}
              </Descriptions.Item>
              <Descriptions.Item label={t('evolution.toolsSinceSkillReview')}>
                {status?.tools_since_skill_review}
              </Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>
        <Col span={12}>
          <Card title={t('evolution.knowledgeFlowSummary')} bordered={false}>
            {status?.knowledge_flow ? (
              <Descriptions column={1} bordered size="small">
                <Descriptions.Item label={t('evolution.pendingReviews')}>
                  {status.knowledge_flow.pending_reviews}
                </Descriptions.Item>
                <Descriptions.Item label={t('evolution.completedFlows')}>
                  {status.knowledge_flow.completed_flows}
                </Descriptions.Item>
                <Descriptions.Item label={t('evolution.trackedExperiences')}>
                  {status.knowledge_flow.tracked_experiences}
                </Descriptions.Item>
                <Descriptions.Item label={t('evolution.requireReview')}>
                  {status.knowledge_flow.require_review ? t('common.yes') : t('common.no')}
                </Descriptions.Item>
              </Descriptions>
            ) : (
              <Empty description={t('evolution.notConfigured')} image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
          </Card>
        </Col>
      </Row>

      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={12}>
          <Card title={t('evolution.backendReviewSummary')} bordered={false}>
            {status?.backend_review ? (
              <Descriptions column={1} bordered size="small">
                <Descriptions.Item label={t('evolution.running')}>
                  <Badge
                    status={status.backend_review.running ? 'success' : 'default'}
                    text={status.backend_review.running ? t('common.yes') : t('common.no')}
                  />
                </Descriptions.Item>
                <Descriptions.Item label={t('evolution.activeTasks')}>
                  {status.backend_review.active_tasks}
                </Descriptions.Item>
                <Descriptions.Item label={t('evolution.totalReviews')}>
                  {status.backend_review.total_reviews}
                </Descriptions.Item>
                <Descriptions.Item label={t('evolution.pendingHumanReview')}>
                  {status.backend_review.pending_human_review}
                </Descriptions.Item>
              </Descriptions>
            ) : (
              <Empty description={t('evolution.notConfigured')} image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
          </Card>
        </Col>
        <Col span={12}>
          <Card title={t('evolution.reviewSchedule')} bordered={false}>
            {status?.backend_review?.schedule ? (
              <Descriptions column={1} bordered size="small">
                <Descriptions.Item label={t('evolution.memoryReviewInterval')}>
                  {status.backend_review.schedule.memory_review_interval}s
                </Descriptions.Item>
                <Descriptions.Item label={t('evolution.skillReviewInterval')}>
                  {status.backend_review.schedule.skill_review_interval}s
                </Descriptions.Item>
                <Descriptions.Item label={t('evolution.experienceReviewInterval')}>
                  {status.backend_review.schedule.experience_review_interval}s
                </Descriptions.Item>
                <Descriptions.Item label={t('evolution.knowledgeFlowInterval')}>
                  {status.backend_review.schedule.knowledge_flow_interval}s
                </Descriptions.Item>
              </Descriptions>
            ) : (
              <Empty description={t('evolution.notConfigured')} image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
          </Card>
        </Col>
      </Row>

      <div style={{ textAlign: 'right', marginTop: 16 }}>
        <Button icon={<ReloadOutlined />} onClick={fetchStatus}>
          {t('common.refresh')}
        </Button>
      </div>
    </div>
  );
}

// =========================================================================
// Experiences Tab
// =========================================================================

function ExperiencesTab() {
  const { t } = useTranslation();
  const [experiences, setExperiences] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [filterStatus, setFilterStatus] = useState('all');
  const [detailModal, setDetailModal] = useState<{ open: boolean; exp: any }>({ open: false, exp: null });

  const fetchExperiences = async () => {
    setLoading(true);
    try {
      const data = await listExperiences('default', filterStatus) as any;
      setExperiences(data?.experiences || []);
    } catch (e: any) {
      message.error(t('evolution.fetchFailed'));
    } finally {
      setLoading(false);
    }
  };

  const handleExtraction = async () => {
    try {
      const data = await triggerExtraction() as any;
      message.success(t('evolution.extractionSuccess', { count: data?.extracted }));
      fetchExperiences();
    } catch (e: any) {
      message.error(e.message || t('evolution.extractionFailed'));
    }
  };

  const handleApprove = async (id: string) => {
    try {
      await approveExperience(id);
      message.success(t('evolution.approved'));
      fetchExperiences();
    } catch (e: any) {
      message.error(e.message || t('evolution.approveFailed'));
    }
  };

  const handleReject = async (id: string) => {
    try {
      await rejectExperience(id);
      message.success(t('evolution.rejected'));
      fetchExperiences();
    } catch (e: any) {
      message.error(e.message || t('evolution.rejectFailed'));
    }
  };

  useEffect(() => { fetchExperiences(); }, [filterStatus]);

  const columns = [
    {
      title: t('evolution.category'),
      dataIndex: 'category',
      key: 'category',
      width: 120,
      render: (v: string) => <Tag color="blue">{v}</Tag>,
    },
    {
      title: t('evolution.type'),
      dataIndex: 'memory_type',
      key: 'memory_type',
      width: 100,
      render: (v: string) => {
        const colorMap: any = { long_term: 'green', short_term: 'orange', core: 'red' };
        return <Tag color={colorMap[v] || 'default'}>{v}</Tag>;
      },
    },
    {
      title: t('evolution.status'),
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (v: string) => {
        const colorMap: any = { pending: 'orange', approved: 'green', rejected: 'red' };
        return <Tag color={colorMap[v] || 'default'}>{v}</Tag>;
      },
    },
    {
      title: t('evolution.confidence'),
      dataIndex: 'confidence',
      key: 'confidence',
      width: 100,
      render: (v: number) => <Progress percent={Math.round((v || 0) * 100)} size="small" />,
    },
    {
      title: t('evolution.content'),
      dataIndex: 'content',
      key: 'content',
      ellipsis: true,
      render: (v: string) => v?.substring(0, 80) + (v?.length > 80 ? '...' : ''),
    },
    {
      title: t('common.actions'),
      key: 'actions',
      width: 200,
      render: (_: any, record: any) => (
        <Space>
          <Button size="small" onClick={() => setDetailModal({ open: true, exp: record })}>
            {t('common.details')}
          </Button>
          {record.status === 'pending' && (
            <>
              <Popconfirm
                title={t('evolution.confirmApprove')}
                onConfirm={() => handleApprove(record.experience_id)}
              >
                <Button size="small" type="primary" icon={<CheckCircleOutlined />}>
                  {t('evolution.approve')}
                </Button>
              </Popconfirm>
              <Popconfirm
                title={t('evolution.confirmReject')}
                onConfirm={() => handleReject(record.experience_id)}
              >
                <Button size="small" danger icon={<CloseCircleOutlined />}>
                  {t('evolution.reject')}
                </Button>
              </Popconfirm>
            </>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Row justify="end" gutter={16} style={{ marginBottom: 16 }}>
        <Col>
          <Space>
            <Select
              value={filterStatus}
              onChange={setFilterStatus}
              style={{ width: 120 }}
              options={[
                { value: 'all', label: t('evolution.all') },
                { value: 'pending', label: t('evolution.pending') },
                { value: 'approved', label: t('evolution.approved') },
                { value: 'rejected', label: t('evolution.rejected') },
              ]}
            />
            <Button icon={<ReloadOutlined />} onClick={fetchExperiences}>
              {t('common.refresh')}
            </Button>
            <Button type="primary" icon={<TrophyOutlined />} onClick={handleExtraction}>
              {t('evolution.extract')}
            </Button>
          </Space>
        </Col>
      </Row>

      <Table
        columns={columns}
        dataSource={experiences}
        rowKey="experience_id"
        loading={loading}
        locale={{ emptyText: t('evolution.noExperiences') }}
        scroll={{ x: 800 }}
        size="small"
      />

      <Modal
        title={t('evolution.experienceDetails')}
        open={detailModal.open}
        onCancel={() => setDetailModal({ open: false, exp: null })}
        footer={null}
        width={700}
      >
        {detailModal.exp && (
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label={t('evolution.experienceId')}>
              {detailModal.exp.experience_id}
            </Descriptions.Item>
            <Descriptions.Item label={t('evolution.category')}>
              {detailModal.exp.category}
            </Descriptions.Item>
            <Descriptions.Item label={t('evolution.type')}>
              {detailModal.exp.memory_type}
            </Descriptions.Item>
            <Descriptions.Item label={t('evolution.status')}>
              {detailModal.exp.status}
            </Descriptions.Item>
            <Descriptions.Item label={t('evolution.confidence')}>
              {(detailModal.exp.confidence * 100).toFixed(1)}%
            </Descriptions.Item>
            <Descriptions.Item label={t('evolution.tags')}>
              <Space wrap>
                {detailModal.exp.tags?.map((tag: string) => (
                  <Tag key={tag}>{tag}</Tag>
                ))}
              </Space>
            </Descriptions.Item>
            <Descriptions.Item label={t('evolution.content')}>
              <pre style={{ whiteSpace: 'pre-wrap', maxHeight: 300, overflow: 'auto' }}>
                {detailModal.exp.content}
              </pre>
            </Descriptions.Item>
            <Descriptions.Item label={t('evolution.sourceSession')}>
              {detailModal.exp.source_session}
            </Descriptions.Item>
            <Descriptions.Item label={t('evolution.createdAt')}>
              {detailModal.exp.created_at}
            </Descriptions.Item>
          </Descriptions>
        )}
      </Modal>
    </div>
  );
}

// =========================================================================
// Knowledge Flow Tab
// =========================================================================

function KnowledgeFlowTab() {
  const { t } = useTranslation();
  const [flowStatus, setFlowStatus] = useState<any>(null);
  const [pendingFlows, setPendingFlows] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [comment, setComment] = useState('');

  const fetchAll = async () => {
    setLoading(true);
    try {
      const [status, pending] = await Promise.all([
        getKnowledgeFlowStatus(),
        listPendingFlows(),
      ]) as any;
      setFlowStatus(status);
      setPendingFlows(pending?.pending || []);
    } catch (e: any) {
      message.error(t('evolution.fetchFailed'));
    } finally {
      setLoading(false);
    }
  };

  const handleApproveFlow = async (id: string) => {
    try {
      await approveFlow(id, 'default', comment);
      message.success(t('evolution.flowApproved'));
      setComment('');
      fetchAll();
    } catch (e: any) {
      message.error(e.message || t('evolution.approveFailed'));
    }
  };

  const handleRejectFlow = async (id: string) => {
    try {
      await rejectFlow(id, 'default', comment);
      message.success(t('evolution.flowRejected'));
      setComment('');
      fetchAll();
    } catch (e: any) {
      message.error(e.message || t('evolution.rejectFailed'));
    }
  };

  useEffect(() => { fetchAll(); }, []);

  const flowColumns = [
    {
      title: t('evolution.recordId'),
      dataIndex: 'record_id',
      key: 'record_id',
      width: 150,
    },
    {
      title: t('evolution.sourceLevel'),
      dataIndex: 'source_level',
      key: 'source_level',
      width: 100,
      render: (v: string) => <Tag color="blue">{v}</Tag>,
    },
    {
      title: t('evolution.targetLevel'),
      dataIndex: 'target_level',
      key: 'target_level',
      width: 100,
      render: (v: string) => <Tag color="green">{v}</Tag>,
    },
    {
      title: t('evolution.content'),
      dataIndex: 'content',
      key: 'content',
      ellipsis: true,
    },
    {
      title: t('common.actions'),
      key: 'actions',
      width: 200,
      render: (_: any, record: any) => (
        <Space>
          <Popconfirm
            title={t('evolution.confirmApprove')}
            onConfirm={() => handleApproveFlow(record.record_id)}
          >
            <Button size="small" type="primary" icon={<CheckCircleOutlined />}>
              {t('evolution.approve')}
            </Button>
          </Popconfirm>
          <Popconfirm
            title={t('evolution.confirmReject')}
            onConfirm={() => handleRejectFlow(record.record_id)}
          >
            <Button size="small" danger icon={<CloseCircleOutlined />}>
              {t('evolution.reject')}
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card>
            <Statistic
              title={t('evolution.pendingReviews')}
              value={flowStatus?.pending_reviews ?? 0}
              prefix={<ClockCircleOutlined />}
              valueStyle={{ color: (flowStatus?.pending_reviews ?? 0) > 0 ? '#faad14' : '#3f8600' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title={t('evolution.completedFlows')}
              value={flowStatus?.completed_flows ?? 0}
              prefix={<CheckCircleOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title={t('evolution.trackedExperiences')}
              value={flowStatus?.tracked_experiences ?? 0}
              prefix={<DatabaseOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title={t('evolution.requireReview')}
              value={flowStatus?.require_review ? t('common.yes') : t('common.no')}
              prefix={<SearchOutlined />}
            />
          </Card>
        </Col>
      </Row>

      <Card title={t('evolution.pendingFlows')} bordered={false}>
        <Input
          placeholder={t('evolution.reviewComment')}
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          style={{ marginBottom: 16 }}
        />
        <Table
          columns={flowColumns}
          dataSource={pendingFlows}
          rowKey="record_id"
          loading={loading}
          locale={{ emptyText: t('evolution.noPendingFlows') }}
          size="small"
        />
      </Card>

      <div style={{ textAlign: 'right', marginTop: 16 }}>
        <Button icon={<ReloadOutlined />} onClick={fetchAll}>
          {t('common.refresh')}
        </Button>
      </div>
    </div>
  );
}

// =========================================================================
// Review Tab
// =========================================================================

function ReviewTab() {
  const { t } = useTranslation();
  const [reviewStatus, setReviewStatus] = useState<any>(null);
  const [history, setHistory] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchAll = async () => {
    setLoading(true);
    try {
      const [status, hist] = await Promise.all([
        getReviewStatus(),
        getReviewHistory(),
      ]) as any;
      setReviewStatus(status);
      setHistory(hist?.history || []);
    } catch (e: any) {
      message.error(t('evolution.fetchFailed'));
    } finally {
      setLoading(false);
    }
  };

  const handleStartReview = async () => {
    try {
      await startReview();
      message.success(t('evolution.reviewStarted'));
      fetchAll();
    } catch (e: any) {
      message.error(e.message || t('evolution.startFailed'));
    }
  };

  const handleStopReview = async () => {
    try {
      await stopReview();
      message.success(t('evolution.reviewStopped'));
      fetchAll();
    } catch (e: any) {
      message.error(e.message || t('evolution.stopFailed'));
    }
  };

  useEffect(() => { fetchAll(); }, []);

  const historyColumns = [
    {
      title: t('evolution.reviewType'),
      dataIndex: 'review_type',
      key: 'review_type',
      width: 120,
      render: (v: string) => <Tag color="purple">{v}</Tag>,
    },
    {
      title: t('evolution.result'),
      dataIndex: 'result',
      key: 'result',
      width: 100,
      render: (v: string) => {
        const colorMap: any = { approved: 'green', rejected: 'red', pending: 'orange' };
        return <Tag color={colorMap[v] || 'default'}>{v}</Tag>;
      },
    },
    {
      title: t('evolution.summary'),
      dataIndex: 'summary',
      key: 'summary',
      ellipsis: true,
    },
    {
      title: t('evolution.timestamp'),
      dataIndex: 'timestamp',
      key: 'timestamp',
      width: 180,
    },
  ];

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card>
            <Statistic
              title={t('evolution.running')}
              value={reviewStatus?.running ? t('common.yes') : t('common.no')}
              prefix={<PlayCircleOutlined />}
              valueStyle={{ color: reviewStatus?.running ? '#3f8600' : '#d9d9d9' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title={t('evolution.activeTasks')}
              value={reviewStatus?.active_tasks ?? 0}
              prefix={<ThunderboltOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title={t('evolution.totalReviews')}
              value={reviewStatus?.total_reviews ?? 0}
              prefix={<FileTextOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title={t('evolution.pendingHumanReview')}
              value={reviewStatus?.pending_human_review ?? 0}
              prefix={<ClockCircleOutlined />}
              valueStyle={{ color: (reviewStatus?.pending_human_review ?? 0) > 0 ? '#faad14' : '#3f8600' }}
            />
          </Card>
        </Col>
      </Row>

      <Row justify="end" gutter={16} style={{ marginBottom: 16 }}>
        <Col>
          <Space>
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              onClick={handleStartReview}
              disabled={reviewStatus?.running}
            >
              {t('evolution.startReview')}
            </Button>
            <Button
              danger
              icon={<PauseCircleOutlined />}
              onClick={handleStopReview}
              disabled={!reviewStatus?.running}
            >
              {t('evolution.stopReview')}
            </Button>
            <Button icon={<ReloadOutlined />} onClick={fetchAll}>
              {t('common.refresh')}
            </Button>
          </Space>
        </Col>
      </Row>

      <Card title={t('evolution.reviewHistory')} bordered={false}>
        <Table
          columns={historyColumns}
          dataSource={history}
          rowKey="id"
          loading={loading}
          locale={{ emptyText: t('evolution.noHistory') }}
          scroll={{ x: 800 }}
          size="small"
          pagination={{ pageSize: 10 }}
        />
      </Card>
    </div>
  );
}

// =========================================================================
// Skill Evolution Tab — 效能看板 / 触发分析 / 改进建议
// =========================================================================

interface SkillMetric {
  skill_name: string;
  precision: number;
  reliability: number;
  effectiveness: number;
  satisfaction: number;
  robustness: number;
  composite_score: number;
  total_triggers: number;
  skill_tool_used_count: number;
  tool_success_count: number;
  tool_error_count: number;
  user_followup_count: number;
  last_triggered_at: string;
  last_computed_at: string;
  top_keywords: string[];
}

interface FunnelData {
  funnel: Array<{ stage: string; count: number }>;
  rates: {
    trigger_to_use: number;
    use_to_success: number;
    overall_satisfaction: number;
  };
}

function SkillEvolutionTab() {
  const [subTab, setSubTab] = useState('dashboard');
  const subItems = [
    { key: 'dashboard', label: <><BarChartOutlined /> 效能看板</>, children: <MetricsDashboard /> },
    { key: 'triggers', label: <><SearchOutlined /> 触发分析</>, children: <TriggerAnalysis /> },
    { key: 'suggestions', label: <><FileTextOutlined /> 改进建议</>, children: <ImprovementSuggestions /> },
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
      const data = await skillApi.getSkillMetrics({ refresh });
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
          <Row gutter={16} style={{ marginTop: 8 }}>
            <Col span={8}><Statistic title="触发→使用率" value={funnel.rates.trigger_to_use} precision={2} suffix="" valueStyle={{ fontSize: 16 }} /></Col>
            <Col span={8}><Statistic title="使用→成功率" value={funnel.rates.use_to_success} precision={2} suffix="" valueStyle={{ fontSize: 16 }} /></Col>
            <Col span={8}><Statistic title="整体满意度" value={funnel.rates.overall_satisfaction} precision={2} suffix="" valueStyle={{ fontSize: 16 }} /></Col>
          </Row>
        </Card>
      )}
      <Card title={`技能效能排名（${metrics.length} 个技能）`} size="small">
        <Table
          columns={columns}
          dataSource={metrics}
          rowKey="skill_name"
          loading={loading}
          size="small"
          pagination={false}
          scroll={{ x: 700 }}
          locale={{ emptyText: <Empty description="暂无效能数据，技能触发后自动采集" /> }}
        />
      </Card>
    </div>
  );
}

function TriggerAnalysis() {
  const [metrics, setMetrics] = useState<SkillMetric[]>([]);

  useEffect(() => {
    (async () => {
      try {
        const data = await skillApi.getSkillMetrics();
        setMetrics(data.metrics || []);
      } catch { /* ignore */ }
    })();
  }, []);

  // 误触发：precision < 0.3
  const misfired = metrics.filter(m => m.precision < 0.3 && m.total_triggers >= 2);
  // 漏触发：skill_tool_used > 0 but satisfaction < 0.5
  const missed = metrics.filter(m => m.satisfaction < 0.5 && m.total_triggers >= 2);

  const allKeywords = metrics.flatMap(m => m.top_keywords.map(k => ({ keyword: k, skill: m.skill_name, score: m.composite_score })));

  return (
    <div>
      <Row gutter={16}>
        <Col span={12}>
          <Card title="⚠️ 误触发 Top（精确度 < 30%）" size="small" style={{ marginBottom: 16 }}>
            {misfired.length === 0 ? <Empty description="暂无误触发数据" /> : (
              <Table dataSource={misfired} rowKey="skill_name" size="small" pagination={false}
                columns={[
                  { title: '技能', dataIndex: 'skill_name', width: 100 },
                  { title: '精确度', dataIndex: 'precision', width: 80, render: (v: number) => `${(v * 100).toFixed(0)}%` },
                  { title: '触发次数', dataIndex: 'total_triggers', width: 80 },
                  { title: 'Top 关键词', dataIndex: 'top_keywords', render: (k: string[]) => k.slice(0, 3).join(', ') },
                ]}
              />
            )}
          </Card>
        </Col>
        <Col span={12}>
          <Card title="🔻 漏触发 Top（满意度 < 50%）" size="small" style={{ marginBottom: 16 }}>
            {missed.length === 0 ? <Empty description="暂无漏触发数据" /> : (
              <Table dataSource={missed} rowKey="skill_name" size="small" pagination={false}
                columns={[
                  { title: '技能', dataIndex: 'skill_name', width: 100 },
                  { title: '满意度', dataIndex: 'satisfaction', width: 80, render: (v: number) => `${(v * 100).toFixed(0)}%` },
                  { title: '触发次数', dataIndex: 'total_triggers', width: 80 },
                  { title: '重复提问', dataIndex: 'user_followup_count', width: 80 },
                ]}
              />
            )}
          </Card>
        </Col>
      </Row>
      <Card title="触发词总览" size="small">
        <Table
          dataSource={allKeywords}
          rowKey={(_, i) => String(i)}
          size="small"
          pagination={{ pageSize: 20 }}
          columns={[
            { title: '触发词', dataIndex: 'keyword', width: 150 },
            { title: '所属技能', dataIndex: 'skill', width: 120, render: (v: string) => <Tag>{v}</Tag> },
            { title: '效能分', dataIndex: 'score', width: 100, sorter: (a: any, b: any) => a.score - b.score,
              render: (v: number) => <Progress percent={Math.round(v * 100)} size="small" strokeColor={v >= 0.7 ? '#52c41a' : v >= 0.4 ? '#faad14' : '#ff4d4f'} style={{ width: 80 }} /> },
          ]}
          locale={{ emptyText: <Empty description="暂无触发词数据" /> }}
        />
      </Card>
    </div>
  );
}

function ImprovementSuggestions() {
  // 改进建议：效能分 < 0.5 的技能自动建议
  const [metrics, setMetrics] = useState<SkillMetric[]>([]);

  useEffect(() => {
    (async () => {
      try {
        const data = await skillApi.getSkillMetrics();
        setMetrics(data.metrics || []);
      } catch { /* ignore */ }
    })();
  }, []);

  const suggestions = metrics
    .filter(m => m.composite_score < 0.5 && m.total_triggers >= 2)
    .map(m => ({
      skill_name: m.skill_name,
      score: m.composite_score,
      issues: [
        m.precision < 0.3 && '精确度低：触发词过于宽泛，需收窄关键词',
        m.reliability < 0.5 && '可靠性低：工具执行频繁失败，需检查工具实现',
        m.satisfaction < 0.5 && '满意度低：用户频繁重复提问，需优化技能效果',
        m.robustness < 0.5 && '稳健性低：错误率较高，需加强异常处理',
      ].filter(Boolean) as string[],
    }));

  return (
    <div>
      <Card title={`待改进技能（${suggestions.length} 个）`} size="small">
        {suggestions.length === 0 ? (
          <Empty description="所有技能运行良好，暂无改进建议 🎉" />
        ) : (
          <Table
            dataSource={suggestions}
            rowKey="skill_name"
            size="small"
            pagination={false}
            columns={[
              { title: '技能', dataIndex: 'skill_name', width: 120, render: (v: string) => <Tag color="red">{v}</Tag> },
              { title: '效能分', dataIndex: 'score', width: 120,
                render: (v: number) => <Progress percent={Math.round(v * 100)} size="small" strokeColor="#ff4d4f" style={{ width: 80 }} /> },
              { title: '问题 & 建议', dataIndex: 'issues',
                render: (issues: string[]) => (
                  <ul style={{ margin: 0, paddingLeft: 16 }}>
                    {issues.map((iss, i) => <li key={i}>{iss}</li>)}
                  </ul>
                ) },
            ]}
          />
        )}
      </Card>
    </div>
  );
}
