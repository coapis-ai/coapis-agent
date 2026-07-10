import { useEffect, useState } from 'react';
import {
  Card, Button, Space, Tag, message, Modal, Alert, Table, Switch, Typography,
  Input, Select, Row, Col, Statistic
} from 'antd';
import {
  ToolOutlined, WarningOutlined, ScanOutlined, DeleteOutlined,
  CloudServerOutlined, ReloadOutlined, SearchOutlined, CheckCircleOutlined,
  StopOutlined
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { adminApi } from '@/api/modules/admin';
import toolsApi from '@/api/modules/tools';

const { Paragraph } = Typography;

interface ToolInfo {
  name: string;
  enabled: boolean;
  description: string;
  category: string;
  group: string;
  tags: string[];
  scene: string;
  async_execution: boolean;
  icon: string;
  builtin: boolean;
}

interface ToolStats {
  total: number;
  enabled: number;
  disabled: number;
  groups: Record<string, number>;
  categories: Record<string, number>;
  builtin_count: number;
  plugin_count: number;
}

export default function ToolsTab() {
  const { t } = useTranslation();
  const [scanning, setScanning] = useState(false);
  const [cleaning, setCleaning] = useState(false);
  const [diagnosing, setDiagnosing] = useState(false);
  const [cleanupResults, setCleanupResults] = useState<any>(null);
  const [diagnoseResults, setDiagnoseResults] = useState<any>(null);
  const [externalAgents, setExternalAgents] = useState<any[]>([]);
  const [loadingExternal, setLoadingExternal] = useState(false);

  // ── Built-in tools management ─────────────────────────────────────
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [toolStats, setToolStats] = useState<ToolStats | null>(null);
  const [loadingTools, setLoadingTools] = useState(false);
  const [searchText, setSearchText] = useState('');
  const [filterGroup, setFilterGroup] = useState<string | undefined>(undefined);
  const [filterEnabled, setFilterEnabled] = useState<string | undefined>(undefined);
  const [toolGroups, setToolGroups] = useState<{ group: string; count: number }[]>([]);

  const loadTools = async () => {
    setLoadingTools(true);
    try {
      const [list, stats, groups] = await Promise.all([
        toolsApi.list({ search: searchText || undefined, group: filterGroup }),
        toolsApi.stats(),
        toolsApi.listGroups(),
      ]);
      setTools(list || []);
      setToolStats(stats || null);
      setToolGroups(groups || []);
    } catch (e: any) {
      message.error(e?.message || t('admin.toolsLoadFailed'));
    } finally {
      setLoadingTools(false);
    }
  };

  useEffect(() => {
    loadTools();
  }, [searchText, filterGroup]);

  const handleToggleTool = async (toolName: string, enabled: boolean) => {
    try {
      await toolsApi.toggle(toolName, enabled);
      message.success(t('admin.toolUpdated'));
      setTools((prev) =>
        prev.map((tool) => (tool.name === toolName ? { ...tool, enabled } : tool))
      );
      if (toolStats) {
        setToolStats({
          ...toolStats,
          enabled: toolStats.enabled + (enabled ? 1 : -1),
          disabled: toolStats.disabled + (enabled ? -1 : 1),
        });
      }
    } catch (e: any) {
      message.error(e?.message || t('admin.toolUpdateFailed'));
    }
  };

  const handleEnableAll = async () => {
    Modal.confirm({
      title: t('admin.confirmEnableAllTools'),
      content: t('admin.enableAllToolsDesc'),
      onOk: async () => {
        try {
          await toolsApi.enableAll();
          message.success(t('admin.allToolsEnabled'));
          loadTools();
        } catch (e: any) {
          message.error(e?.message || t('admin.toolUpdateFailed'));
        }
      },
    });
  };

  const handleDisableAll = async () => {
    Modal.confirm({
      title: t('admin.confirmDisableAllTools'),
      content: t('admin.disableAllToolsDesc'),
      onOk: async () => {
        try {
          await toolsApi.disableAll();
          message.success(t('admin.allToolsDisabled'));
          loadTools();
        } catch (e: any) {
          message.error(e?.message || t('admin.toolUpdateFailed'));
        }
      },
    });
  };

  // Apply client-side enabled filter
  const displayedTools = tools.filter((tool) => {
    if (filterEnabled === 'enabled') return tool.enabled;
    if (filterEnabled === 'disabled') return !tool.enabled;
    return true;
  });

  const toolColumns = [
    {
      title: t('admin.toolName'),
      dataIndex: 'name',
      key: 'name',
      width: 220,
      render: (_: string, record: ToolInfo) => (
        <Space>
          <span>{record.icon || '🔧'}</span>
          <span style={{ fontFamily: 'monospace', fontWeight: 500 }}>{record.name}</span>
        </Space>
      ),
    },
    {
      title: t('admin.toolDescription'),
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
    },
    {
      title: t('admin.group'),
      dataIndex: 'group',
      key: 'group',
      width: 120,
      render: (v: string) => <Tag color={groupColor(v)}>{v}</Tag>,
    },
    {
      title: t('admin.enabled'),
      dataIndex: 'enabled',
      key: 'enabled',
      width: 100,
      fixed: 'right' as const,
      render: (v: boolean, record: ToolInfo) => (
        <Switch
          size="small"
          checked={v}
          checkedChildren={<CheckCircleOutlined />}
          unCheckedChildren={<StopOutlined />}
          onChange={(checked: boolean) => handleToggleTool(record.name, checked)}
        />
      ),
    },
  ];

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

  const groupColor = (g: string) => {
    const map: Record<string, string> = {
      basic: 'blue',
      web: 'cyan',
      media: 'purple',
      agent: 'geekblue',
      data: 'green',
      other: 'default',
    };
    return map[g] || 'default';
  };

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      <Alert
        message={t('admin.toolsWarning')}
        description={t('admin.toolsWarningDesc')}
        type="error"
        showIcon
        icon={<WarningOutlined />}
      />

      {/* ── Built-in Tools Management ─────────────────────────── */}
      <Card
        title={
          <Space>
            <ToolOutlined />
            {t('admin.toolsManagement')}
          </Space>
        }
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={loadTools} loading={loadingTools}>
              {t('common.reload')}
            </Button>
            <Button icon={<CheckCircleOutlined />} onClick={handleEnableAll}>
              {t('admin.enableAll')}
            </Button>
            <Button icon={<StopOutlined />} onClick={handleDisableAll}>
              {t('admin.disableAll')}
            </Button>
          </Space>
        }
      >
        <Paragraph>
          {t('admin.toolsManagementDesc')}
        </Paragraph>
        {toolStats && (
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={4}><Statistic title={t('admin.total')} value={toolStats.total} /></Col>
            <Col span={4}><Statistic title={t('admin.enabled')} value={toolStats.enabled} /></Col>
            <Col span={4}><Statistic title={t('admin.disabled')} value={toolStats.disabled} /></Col>
            <Col span={4}><Statistic title={t('admin.builtin')} value={toolStats.builtin_count} /></Col>
            <Col span={4}><Statistic title={t('admin.plugin')} value={toolStats.plugin_count} /></Col>
          </Row>
        )}
        <Space style={{ marginBottom: 16 }} wrap>
          <Input
            placeholder={t('admin.searchTools')}
            prefix={<SearchOutlined />}
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            allowClear
            style={{ width: 240 }}
          />
          <Select
            placeholder={t('admin.filterByGroup')}
            allowClear
            style={{ width: 160 }}
            value={filterGroup}
            onChange={setFilterGroup}
            options={toolGroups.map((g) => ({ label: `${g.group} (${g.count})`, value: g.group }))}
          />
          <Select
            placeholder={t('admin.filterByStatus')}
            allowClear
            style={{ width: 160 }}
            value={filterEnabled}
            onChange={setFilterEnabled}
            options={[
              { label: t('admin.enabled'), value: 'enabled' },
              { label: t('admin.disabled'), value: 'disabled' },
            ]}
          />
        </Space>
        <Table
          columns={toolColumns}
          dataSource={displayedTools}
          rowKey="name"
          loading={loadingTools}
          size="small"
          scroll={{ x: 1100 }}
          pagination={{ pageSize: 20, showSizeChanger: true }}
        />
      </Card>

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
