import { useEffect, useState } from 'react';
import { Card, Table, Button, Space, Tag, message, Modal, Input, Alert, Switch, Select, InputNumber, Tooltip } from 'antd';
import {
  GlobalOutlined,
  EditOutlined,
  WarningOutlined,
  SyncOutlined,
  ReloadOutlined,
  EyeOutlined,
  PlusOutlined,
  DeleteOutlined,
  StopOutlined,
  PlayCircleOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { adminApi } from '@/api/modules/admin';
import GlobalAgentDetail from './GlobalAgentDetail';

const PROTECTED_AGENTS = ['global_default', 'global_qa_agent'];

const ROLE_OPTIONS = [
  { value: 'template', label: 'Template（模板继承）' },
  { value: 'service', label: 'Service（系统服务）' },
  { value: 'hybrid', label: 'Hybrid（混合型）' },
];

const ROLE_COLORS: Record<string, string> = {
  template: 'blue',
  service: 'green',
  hybrid: 'orange',
};

export default function GlobalAgentsTab() {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(false);
  const [agents, setAgents] = useState<any[]>([]);
  const [editModal, setEditModal] = useState<{ open: boolean; agent?: any }>({ open: false });
  const [editData, setEditData] = useState<any>({});
  const [createModal, setCreateModal] = useState(false);
  const [createData, setCreateData] = useState<any>({
    id: '', name: '', description: '', role: 'template', priority: 100,
  });
  const [creating, setCreating] = useState(false);
  const [viewingAgent, setViewingAgent] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const res: any = await adminApi.listGlobalAgents();
      setAgents(res.agents || res || []);
    } catch (e: any) {
      message.error(e?.message || t('admin.agentsLoadFailed'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  // ── 启用/禁用 ──
  const handleToggle = async (agent: any) => {
    try {
      const res: any = await adminApi.toggleGlobalAgent(agent.id);
      message.success(`${agent.name}: ${res.enabled ? '已启用' : '已禁用'}`);
      load();
    } catch (e: any) {
      message.error(e?.message || '切换失败');
    }
  };

  // ── 编辑 ──
  const handleEdit = (agent: any) => {
    setEditModal({ open: true, agent });
    setEditData({
      name: agent.name || '',
      description: agent.description || '',
      role: agent.role || 'template',
      priority: agent.priority ?? 100,
    });
  };

  const handleSave = async () => {
    if (!editModal.agent) return;
    try {
      await adminApi.updateGlobalAgent(editModal.agent.id, {
        agent_json: {
          name: editData.name,
          description: editData.description,
          role: editData.role,
          priority: editData.priority,
        },
      });
      message.success(t('admin.agentUpdated'));
      setEditModal({ open: false });
      load();
    } catch (e: any) {
      message.error(e?.message || t('admin.agentUpdateFailed'));
    }
  };

  // ── 新增 ──
  const handleCreate = async () => {
    if (!createData.id.trim()) {
      message.warning('请输入智能体 ID');
      return;
    }
    setCreating(true);
    try {
      await adminApi.createGlobalAgent(createData);
      message.success(`全局智能体 ${createData.id} 创建成功`);
      setCreateModal(false);
      setCreateData({ id: '', name: '', description: '', role: 'template', priority: 100 });
      load();
    } catch (e: any) {
      message.error(e?.message || '创建失败');
    } finally {
      setCreating(false);
    }
  };

  // ── 删除 ──
  const handleDelete = (agent: any) => {
    if (PROTECTED_AGENTS.includes(agent.id)) {
      message.warning(`${agent.name} 是受保护的智能体，不可删除`);
      return;
    }
    Modal.confirm({
      title: `确认删除全局智能体？`,
      content: (
        <div>
          <p><strong>ID:</strong> {agent.id}</p>
          <p><strong>名称:</strong> {agent.name}</p>
          <p style={{ color: '#ff4d4f' }}>删除后将备份到 backups 目录，此操作可恢复。</p>
        </div>
      ),
      okText: '确认删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          await adminApi.deleteGlobalAgent(agent.id);
          message.success(`${agent.id} 已删除`);
          load();
        } catch (e: any) {
          message.error(e?.message || '删除失败');
        }
      },
    });
  };

  // ── 详情 ──
  const handleView = (agentId: string) => setViewingAgent(agentId);
  const handleBackToList = () => setViewingAgent(null);

  // ── 初始化身份 ──
  const handleInitIdentity = async (agentId: string) => {
    Modal.confirm({
      title: t('admin.initIdentityConfirm'),
      content: t('admin.initIdentityConfirmDesc', { agentId }),
      onOk: async () => {
        try {
          await adminApi.initGlobalAgentIdentity(agentId);
          message.success(t('admin.identityInitialized'));
          load();
        } catch (e: any) {
          message.error(e?.message || t('admin.identityInitFailed'));
        }
      },
    });
  };

  const columns = [
    {
      title: t('admin.agentId'),
      dataIndex: 'id',
      key: 'id',
      width: 200,
      render: (v: string) => (
        <Space>
          <span style={{ fontFamily: 'monospace' }}>{v}</span>
          {PROTECTED_AGENTS.includes(v) && <Tag color="gold">🔒</Tag>}
        </Space>
      ),
    },
    {
      title: t('admin.agentName'),
      dataIndex: 'name',
      key: 'name',
    },
    {
      title: '角色',
      dataIndex: 'role',
      key: 'role',
      width: 160,
      render: (v: string) => (
        <Tag color={ROLE_COLORS[v] || 'default'}>{v || 'template'}</Tag>
      ),
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      key: 'priority',
      width: 80,
      render: (v: number) => v ?? 100,
    },
    {
      title: t('admin.enabled'),
      dataIndex: 'enabled',
      key: 'enabled',
      width: 100,
      render: (v: boolean, record: any) => (
        <Switch
          checked={v}
          checkedChildren={<PlayCircleOutlined />}
          unCheckedChildren={<StopOutlined />}
          onChange={() => handleToggle(record)}
          disabled={PROTECTED_AGENTS.includes(record.id)}
        />
      ),
    },
    {
      title: t('common.actions'),
      key: 'actions',
      width: 280,
      render: (_: any, record: any) => (
        <Space>
          <Tooltip title="查看详情">
            <Button size="small" type="primary" icon={<EyeOutlined />} onClick={() => handleView(record.id)} />
          </Tooltip>
          <Tooltip title="编辑">
            <Button size="small" icon={<EditOutlined />} onClick={() => handleEdit(record)} />
          </Tooltip>
          <Tooltip title="从模板初始化身份文件">
            <Button size="small" icon={<SyncOutlined />} onClick={() => handleInitIdentity(record.id)} />
          </Tooltip>
          {!PROTECTED_AGENTS.includes(record.id) && (
            <Tooltip title="删除">
              <Button size="small" danger icon={<DeleteOutlined />} onClick={() => handleDelete(record)} />
            </Tooltip>
          )}
        </Space>
      ),
    },
  ];

  if (viewingAgent) {
    return <GlobalAgentDetail agentId={viewingAgent} onBack={handleBackToList} />;
  }

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      <Alert
        message={t('admin.globalAgentsWarning')}
        description={t('admin.globalAgentsWarningDesc')}
        type="warning"
        showIcon
        icon={<WarningOutlined />}
      />

      <Card
        title={
          <Space>
            <GlobalOutlined />
            {t('admin.globalAgents')}
          </Space>
        }
        extra={
          <Space>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateModal(true)}>
              新增全局智能体
            </Button>
            <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>
              {t('common.reload')}
            </Button>
          </Space>
        }
      >
        <Table
          columns={columns}
          dataSource={agents}
          rowKey="id"
          loading={loading}
          pagination={false}
        />
      </Card>

      {/* ── 新增弹窗 ── */}
      <Modal
        title="新增全局智能体"
        open={createModal}
        onOk={handleCreate}
        onCancel={() => setCreateModal(false)}
        confirmLoading={creating}
        okText="创建"
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <div>
            <strong>ID *</strong>
            <Input
              value={createData.id}
              onChange={(e) => setCreateData({ ...createData, id: e.target.value })}
              placeholder="例如: global_helper"
              style={{ marginTop: 4 }}
            />
            <div style={{ fontSize: 12, color: '#999', marginTop: 2 }}>
              只能包含字母、数字、短横线和下划线
            </div>
          </div>
          <div>
            <strong>名称</strong>
            <Input
              value={createData.name}
              onChange={(e) => setCreateData({ ...createData, name: e.target.value })}
              placeholder="显示名称"
              style={{ marginTop: 4 }}
            />
          </div>
          <div>
            <strong>描述</strong>
            <Input.TextArea
              value={createData.description}
              onChange={(e) => setCreateData({ ...createData, description: e.target.value })}
              placeholder="智能体描述"
              rows={3}
              style={{ marginTop: 4 }}
            />
          </div>
          <div>
            <strong>角色</strong>
            <Select
              value={createData.role}
              onChange={(v) => setCreateData({ ...createData, role: v })}
              options={ROLE_OPTIONS}
              style={{ width: '100%', marginTop: 4 }}
            />
          </div>
          <div>
            <strong>优先级</strong>
            <InputNumber
              value={createData.priority}
              onChange={(v) => setCreateData({ ...createData, priority: v })}
              min={0}
              max={9999}
              style={{ width: '100%', marginTop: 4 }}
            />
            <div style={{ fontSize: 12, color: '#999', marginTop: 2 }}>
              数字越小越优先（作为基础层），默认 100
            </div>
          </div>
        </Space>
      </Modal>

      {/* ── 编辑弹窗 ── */}
      <Modal
        title={`编辑: ${editModal.agent?.id}`}
        open={editModal.open}
        onOk={handleSave}
        onCancel={() => setEditModal({ open: false })}
        okText="保存"
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <div>
            <strong>ID:</strong> <code>{editModal.agent?.id}</code>
          </div>
          <div>
            <strong>名称</strong>
            <Input
              value={editData.name || ''}
              onChange={(e) => setEditData({ ...editData, name: e.target.value })}
              style={{ marginTop: 4 }}
            />
          </div>
          <div>
            <strong>描述</strong>
            <Input.TextArea
              value={editData.description || ''}
              onChange={(e) => setEditData({ ...editData, description: e.target.value })}
              rows={3}
              style={{ marginTop: 4 }}
            />
          </div>
          <div>
            <strong>角色</strong>
            <Select
              value={editData.role || 'template'}
              onChange={(v) => setEditData({ ...editData, role: v })}
              options={ROLE_OPTIONS}
              style={{ width: '100%', marginTop: 4 }}
            />
          </div>
          <div>
            <strong>优先级</strong>
            <InputNumber
              value={editData.priority ?? 100}
              onChange={(v) => setEditData({ ...editData, priority: v })}
              min={0}
              max={9999}
              style={{ width: '100%', marginTop: 4 }}
            />
          </div>
        </Space>
      </Modal>
    </Space>
  );
}
