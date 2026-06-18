import { useEffect, useState } from 'react';
import { Card, Button, Space, Tag, message, Modal, Alert, Table, Switch, Typography } from 'antd';
import { ToolOutlined, WarningOutlined, ScanOutlined, DeleteOutlined, CloudServerOutlined, ReloadOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { adminApi } from '@/api/modules/admin';

const { Paragraph } = Typography;

export default function ToolsTab() {
  const { t } = useTranslation();
  const [scanning, setScanning] = useState(false);
  const [cleaning, setCleaning] = useState(false);
  const [diagnosing, setDiagnosing] = useState(false);
  const [cleanupResults, setCleanupResults] = useState<any>(null);
  const [diagnoseResults, setDiagnoseResults] = useState<any>(null);
  const [externalAgents, setExternalAgents] = useState<any[]>([]);
  const [loadingExternal, setLoadingExternal] = useState(false);

  // ── Scan & Cleanup ────────────────────────────────────────────────
  const handleScan = async () => {
    setScanning(true);
    try {
      const res: any = await adminApi.scanCleanup();
      setCleanupResults(res);
      message.success(t('admin.scanComplete'));
    } catch (e: any) {
      message.error(e?.message || t('admin.scanFailed'));
    } finally {
      setScanning(false);
    }
  };

  const handleCleanup = () => {
    if (!cleanupResults?.dirs?.length) {
      message.warning(t('admin.nothingToCleanup'));
      return;
    }
    Modal.confirm({
      title: t('admin.confirmCleanup'),
      content: (
        <div>
          <p>{t('admin.cleanupDesc')}</p>
          <ul style={{ maxHeight: 200, overflow: 'auto' }}>
            {cleanupResults.dirs.map((d: string) => (
              <li key={d} style={{ fontFamily: 'monospace', fontSize: 12 }}>{d}</li>
            ))}
          </ul>
        </div>
      ),
      onOk: async () => {
        setCleaning(true);
        try {
          const res: any = await adminApi.executeCleanup(cleanupResults.dirs);
          message.success(t('admin.cleanupComplete', { count: res.removed?.length || 0 }));
          setCleanupResults(null);
        } catch (e: any) {
          message.error(e?.message || t('admin.cleanupFailed'));
        } finally {
          setCleaning(false);
        }
      },
    });
  };

  // ── System Diagnose ───────────────────────────────────────────────
  const handleDiagnose = async () => {
    setDiagnosing(true);
    try {
      const res: any = await adminApi.systemDiagnose();
      setDiagnoseResults(res);
      message.success(t('admin.diagnoseComplete'));
    } catch (e: any) {
      message.error(e?.message || t('admin.diagnoseFailed'));
    } finally {
      setDiagnosing(false);
    }
  };

  // ── External Agents ───────────────────────────────────────────────
  const loadExternalAgents = async () => {
    setLoadingExternal(true);
    try {
      const res: any = await adminApi.listExternalAgents();
      setExternalAgents(res.agents || res || []);
    } catch (e: any) {
      message.error(e?.message || t('admin.externalAgentsLoadFailed'));
    } finally {
      setLoadingExternal(false);
    }
  };

  useEffect(() => { loadExternalAgents(); }, []);

  const handleToggleExternal = async (agentId: string, enabled: boolean) => {
    try {
      await adminApi.toggleExternalAgent(agentId, enabled);
      message.success(t('admin.externalAgentUpdated'));
      loadExternalAgents();
    } catch (e: any) {
      message.error(e?.message || t('admin.externalAgentUpdateFailed'));
    }
  };

  const externalColumns = [
    {
      title: t('admin.agentId'),
      dataIndex: 'id',
      key: 'id',
      width: 200,
    },
    {
      title: t('admin.agentName'),
      dataIndex: 'name',
      key: 'name',
    },
    {
      title: t('admin.workspace'),
      dataIndex: 'workspace_dir',
      key: 'workspace_dir',
      ellipsis: true,
    },
    {
      title: t('admin.enabled'),
      dataIndex: 'enabled',
      key: 'enabled',
      width: 100,
      render: (v: boolean, record: any) => (
        <Switch
          size="small"
          checked={v}
          onChange={(checked: boolean) => handleToggleExternal(record.id, checked)}
        />
      ),
    },
    {
      title: t('admin.username'),
      dataIndex: 'username',
      key: 'username',
      width: 100,
      render: (v: string) => v || <Tag color="default">Global</Tag>,
    },
  ];

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      <Alert
        message={t('admin.toolsWarning')}
        description={t('admin.toolsWarningDesc')}
        type="error"
        showIcon
        icon={<WarningOutlined />}
      />

      {/* ── System Cleanup ──────────────────────────────────────── */}
      <Card
        title={
          <Space>
            <ScanOutlined />
            {t('admin.systemCleanup')}
          </Space>
        }
      >
        <Paragraph>
          {t('admin.cleanupDesc')}
        </Paragraph>
        <Space>
          <Button
            icon={<ScanOutlined />}
            loading={scanning}
            onClick={handleScan}
          >
            {t('admin.scanSystem')}
          </Button>
          <Button
            danger
            icon={<DeleteOutlined />}
            loading={cleaning}
            disabled={!cleanupResults?.dirs?.length}
            onClick={handleCleanup}
          >
            {t('admin.cleanup')} ({cleanupResults?.dirs?.length || 0})
          </Button>
        </Space>
        {cleanupResults?.dirs?.length > 0 && (
          <div style={{ marginTop: 16 }}>
            <Tag color="orange">{t('admin.detectedItems')}: {cleanupResults.dirs.length}</Tag>
          </div>
        )}
      </Card>

      {/* ── System Diagnose ─────────────────────────────────────── */}
      <Card
        title={
          <Space>
            <ToolOutlined />
            {t('admin.systemDiagnose')}
          </Space>
        }
      >
        <Paragraph>
          {t('admin.diagnoseDesc')}
        </Paragraph>
        <Button
          type="primary"
          icon={<ReloadOutlined />}
          loading={diagnosing}
          onClick={handleDiagnose}
        >
          {t('admin.runDiagnose')}
        </Button>
        {diagnoseResults && (
          <div style={{ marginTop: 16 }}>
            <pre style={{
              background: '#f5f5f5',
              padding: 12,
              borderRadius: 4,
              maxHeight: 300,
              overflow: 'auto',
              fontSize: 12,
              fontFamily: 'monospace',
            }}>
              {JSON.stringify(diagnoseResults, null, 2)}
            </pre>
          </div>
        )}
      </Card>

      {/* ── External Agents ─────────────────────────────────────── */}
      <Card
        title={
          <Space>
            <CloudServerOutlined />
            {t('admin.externalAgents')}
          </Space>
        }
        extra={
          <Button icon={<ReloadOutlined />} onClick={loadExternalAgents} loading={loadingExternal}>
            {t('common.reload')}
          </Button>
        }
      >
        <Paragraph>
          {t('admin.externalAgentsDesc')}
        </Paragraph>
        <Table
          columns={externalColumns}
          dataSource={externalAgents}
          rowKey="id"
          loading={loadingExternal}
          size="small"
        />
      </Card>
    </Space>
  );
}
