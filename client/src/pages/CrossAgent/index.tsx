import { useState, useEffect } from 'react';
import {
  Card,
  Statistic,
  Row,
  Col,
  Table,
  Tag,
  Button,
  Space,
  Switch,
  message,
  Modal,
  Input,
  Select,
  Typography,
  Badge,
  Collapse,
  Progress,
  Slider,
} from 'antd';
import {
  ThunderboltOutlined,
  CloudUploadOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  PlayCircleOutlined,
  DeleteOutlined,
  PlusOutlined,
  GlobalOutlined,
} from '@ant-design/icons';
import { crossAgentApi, type CrossAgentStatus, type ExperienceEntry } from '@/api/modules/cross_agent';
import { useTranslation } from 'react-i18next';
import styles from './index.module.css';

const { Title, Text } = Typography;

const CrossAgentPage: React.FC = () => {
  const { t } = useTranslation();
  const [status, setStatus] = useState<CrossAgentStatus | null>(null);
  const [bucketA, setBucketA] = useState<ExperienceEntry[]>([]);
  const [bucketB, setBucketB] = useState<ExperienceEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [reportModalVisible, setReportModalVisible] = useState(false);
  const [reportContent, setReportContent] = useState('');
  const [reportCategory, setReportCategory] = useState('general');
  const [reportConfidence, setReportConfidence] = useState(0.8);

  const refresh = async () => {
    setLoading(true);
    try {
      const [statusRes, aRes, bRes] = await Promise.all([
        crossAgentApi.getStatus(),
        crossAgentApi.getBucketA(),
        crossAgentApi.getBucketB(),
      ]);
      setStatus(statusRes as any);
      setBucketA((aRes as any)?.entries ?? []);
      setBucketB((bRes as any)?.entries ?? []);
    } catch (e: any) {
      message.error(t('crossAgent.error', 'Failed to load data'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const handleReport = async () => {
    if (!reportContent.trim()) {
      message.warning(t('crossAgent.enterContent', 'Please enter experience content'));
      return;
    }
    try {
      await crossAgentApi.reportExperience(reportContent, reportCategory, reportConfidence);
      message.success(t('crossAgent.reported', 'Experience reported successfully'));
      setReportModalVisible(false);
      setReportContent('');
      refresh();
    } catch (e: any) {
      message.error(t('crossAgent.reportFailed', 'Failed to report experience'));
    }
  };

  const handleToggle = async () => {
    try {
      await crossAgentApi.enable();
      message.success(t('crossAgent.enabled', 'Cross-agent evolution enabled'));
      refresh();
    } catch (e: any) {
      message.error(t('crossAgent.toggleFailed', 'Failed to toggle'));
    }
  };

  const handleReviewCycle = async () => {
    try {
      const res = await crossAgentApi.triggerReviewCycle();
      const data = res as any;
      message.success(
        t('crossAgent.reviewDone', 'Review completed: {{promoted}} promoted, {{total}} reviewed', {
          promoted: data?.promoted ?? 0,
          total: data?.total_reviewed ?? 0,
        }),
      );
      refresh();
    } catch (e: any) {
      message.error(t('crossAgent.reviewFailed', 'Review failed'));
    }
  };

  const handleCleanup = async () => {
    try {
      const res = await crossAgentApi.cleanupArchives();
      const data = res as any;
      message.success(t('crossAgent.cleaned', 'Cleaned {{count}} expired archives', { count: data?.cleaned ?? 0 }));
      refresh();
    } catch (e: any) {
      message.error(t('crossAgent.cleanupFailed', 'Cleanup failed'));
    }
  };

  const statusColumns = [
    {
      title: t('crossAgent.content', 'Content'),
      dataIndex: 'content',
      key: 'content',
      ellipsis: true,
      render: (text: string) => <Text ellipsis>{text}</Text>,
    },
    {
      title: t('crossAgent.category', 'Category'),
      dataIndex: 'category',
      key: 'category',
      width: 120,
      render: (cat: string) => <Tag color="blue">{cat}</Tag>,
    },
    {
      title: t('crossAgent.source', 'Source'),
      dataIndex: 'source_user',
      key: 'source_user',
      width: 120,
    },
    {
      title: t('crossAgent.confidence', 'Confidence'),
      dataIndex: 'confidence',
      key: 'confidence',
      width: 100,
      render: (val: number) => (
        <Progress percent={Math.round(val * 100)} size="small" strokeColor={val >= 0.6 ? '#52c41a' : '#faad14'} />
      ),
    },
    {
      title: t('crossAgent.keywords', 'Keywords'),
      dataIndex: 'keywords',
      key: 'keywords',
      width: 200,
      render: (kw: string[]) => (kw ?? []).map((k: string) => <Tag key={k} style={{ fontSize: 11 }}>{k}</Tag>),
    },
    {
      title: t('crossAgent.createdAt', 'Created'),
      dataIndex: 'created_at',
      key: 'created_at',
      width: 160,
      render: (ts: string) => new Date(ts).toLocaleString(),
    },
    {
      title: t('crossAgent.status', 'Status'),
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (s: string) => {
        const map: Record<string, { color: string; icon: React.ReactNode }> = {
          pending: { color: 'orange', icon: <ClockCircleOutlined /> },
          promoted: { color: 'green', icon: <CheckCircleOutlined /> },
          reviewed: { color: 'blue', icon: <GlobalOutlined /> },
          archived: { color: 'default', icon: <DeleteOutlined /> },
        };
        const item = map[s] ?? { color: 'default', icon: null };
        return <Badge status={item.color as any} text={s} />;
      },
    },
  ];

  return (
    <div className={styles.pageContainer}>
      <div className={styles.headerBar}>
        <Space align="center">
          <ThunderboltOutlined style={{ fontSize: 24, color: '#722ed1' }} />
          <Title level={4} style={{ margin: 0 }}>
            {t('crossAgent.title', 'Cross-Agent Evolution')}
          </Title>
          <Switch
            checked={status?.enabled}
            onChange={handleToggle}
            checkedChildren={t('crossAgent.on', 'ON')}
            unCheckedChildren={t('crossAgent.off', 'OFF')}
          />
        </Space>
        <Space>
          <Button icon={<PlayCircleOutlined />} onClick={handleReviewCycle} loading={loading}>
            {t('crossAgent.review', 'Run Review')}
          </Button>
          <Button icon={<DeleteOutlined />} onClick={handleCleanup} danger>
            {t('crossAgent.cleanup', 'Cleanup')}
          </Button>
          <Button icon={<PlusOutlined />} type="primary" onClick={() => setReportModalVisible(true)}>
            {t('crossAgent.report', 'Report Experience')}
          </Button>
        </Space>
      </div>

      {/* Stats */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card>
            <Statistic
              title={t('crossAgent.bucketA', 'Bucket A (Promoted)')}
              value={status?.buckets?.bucket_a?.total ?? 0}
              suffix={`/ ${status?.config?.bucket_a_capacity ?? 200}`}
              prefix={<CheckCircleOutlined style={{ color: '#52c41a' }} />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title={t('crossAgent.bucketB', 'Bucket B (Pending)')}
              value={status?.buckets?.bucket_b?.total ?? 0}
              suffix={`/ ${status?.config?.bucket_b_capacity ?? 2000}`}
              prefix={<ClockCircleOutlined style={{ color: '#faad14' }} />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title={t('crossAgent.pending', 'Pending Review')}
              value={status?.buckets?.bucket_b?.pending ?? 0}
              prefix={<CloudUploadOutlined style={{ color: '#1890ff' }} />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title={t('crossAgent.reviewLog', 'Review Log')}
              value={status?.buckets?.review_log?.total ?? 0}
              prefix={<ThunderboltOutlined style={{ color: '#722ed1' }} />}
            />
          </Card>
        </Col>
      </Row>

      {/* Config */}
      <Collapse
        items={[
          {
            key: 'config',
            label: t('crossAgent.config', 'Configuration'),
            children: (
              <Row gutter={24}>
                {Object.entries(status?.config ?? {}).map(([key, val]) => (
                  <Col span={6} key={key}>
                    <Text type="secondary">{key}:</Text>
                    <Text strong style={{ marginLeft: 8 }}>{val}</Text>
                  </Col>
                ))}
              </Row>
            ),
          },
        ]}
        style={{ marginBottom: 24 }}
      />

      {/* Buckets */}
      <Row gutter={24}>
        <Col span={12}>
          <Card title={t('crossAgent.bucketA', 'Bucket A (Promoted)')} size="small" bordered={false}>
            <Table
              columns={statusColumns}
              dataSource={bucketA}
              rowKey="id"
              size="small"
              pagination={false}
              scroll={{ y: 400 }}
              locale={{ emptyText: t('crossAgent.empty', 'No entries') }}
            />
          </Card>
        </Col>
        <Col span={12}>
          <Card title={t('crossAgent.bucketB', 'Bucket B (Pending)')} size="small" bordered={false}>
            <Table
              columns={statusColumns}
              dataSource={bucketB}
              rowKey="id"
              size="small"
              pagination={false}
              scroll={{ y: 400 }}
              locale={{ emptyText: t('crossAgent.empty', 'No entries') }}
            />
          </Card>
        </Col>
      </Row>

      {/* Report Modal */}
      <Modal
        title={t('crossAgent.reportTitle', 'Report Experience')}
        open={reportModalVisible}
        onOk={handleReport}
        onCancel={() => setReportModalVisible(false)}
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <div>
            <Text>{t('crossAgent.content', 'Content')}</Text>
            <Input.TextArea
              rows={4}
              value={reportContent}
              onChange={(e) => setReportContent(e.target.value)}
              placeholder={t('crossAgent.contentPlaceholder', 'Describe the experience or pattern you observed...')}
            />
          </div>
          <div>
            <Text>{t('crossAgent.category', 'Category')}</Text>
            <Select
              value={reportCategory}
              onChange={setReportCategory}
              style={{ width: '100%' }}
              options={[
                { label: 'General', value: 'general' },
                { label: 'Skill', value: 'skill' },
                { label: 'Preference', value: 'preference' },
                { label: 'Behavior', value: 'behavior' },
                { label: 'Domain Knowledge', value: 'domain' },
              ]}
            />
          </div>
          <div>
            <Text>{t('crossAgent.confidence', 'Confidence')}: {Math.round(reportConfidence * 100)}%</Text>
            <Slider
              min={0}
              max={1}
              step={0.1}
              value={reportConfidence}
              onChange={setReportConfidence}
            />
          </div>
        </Space>
      </Modal>
    </div>
  );
};

export default CrossAgentPage;
