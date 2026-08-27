import { useState, useEffect } from 'react';
import {
  Card,
  Table,
  Button,
  Tag,
  Space,
  Modal,
  Form,
  Input,
  Select,
  Switch,
  message,
  Tabs,
  Upload,
} from 'antd';
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  ReloadOutlined,
  ImportOutlined,
} from '@ant-design/icons';
import { PageHeader } from '@/components/PageHeader';
import api from '@/api';
import type { ColumnsType } from 'antd/es/table';

const { Option } = Select;

interface ExternalSystemConfig {
  provider_id: string;
  name: string;
  auth_type: string;
  client_id: string;
  shared_secret_use_global: boolean;
  shared_secret?: string;
  callback_url: string;
  status: number;
}

interface IdentityBinding {
  user_id: string;
  provider: string;
  external_id: string;
  status: number;
  created_at?: string;
  updated_at?: string;
}

function ExternalSystemAuthPage() {
  const [loading, setLoading] = useState(false);
  
  // Tab state
  const [activeTab, setActiveTab] = useState('systems');

  // Systems config state
  const [systemsConfig, setSystemsConfig] = useState<ExternalSystemConfig[]>([]);
  const [systemModalOpen, setSystemModalOpen] = useState(false);
  const [editingSystem, setEditingSystem] = useState<ExternalSystemConfig | null>(null);
  const [systemForm] = Form.useForm();

  // Identity bindings state
  const [bindings, setBindings] = useState<IdentityBinding[]>([]);
  const [bindingModalOpen, setBindingModalOpen] = useState(false);
  const [editingBinding, setEditingBinding] = useState<IdentityBinding | null>(null);
  const [bindingForm] = Form.useForm();

  // Load systems config
  const loadSystemsConfig = async () => {
    setLoading(true);
    try {
      const res: any = await api.get('/admin/external-systems/config');
      setSystemsConfig(res.data || []);
    } catch (e: any) {
      message.error('获取外部系统配置失败');
    } finally {
      setLoading(false);
    }
  };

  // Load identity bindings
  const loadBindings = async () => {
    try {
      const res: any = await api.get('/admin/users/identity-bindings');
      setBindings(res.data || []);
    } catch (e: any) {
      message.error('获取身份映射记录失败');
    }
  };

  useEffect(() => {
    if (activeTab === 'systems') {
      loadSystemsConfig();
    } else {
      loadBindings();
    }
  }, [activeTab]);

  // Handle add/edit system config
  const handleSystemModalOpen = (system?: ExternalSystemConfig) => {
    setEditingSystem(system || null);
    if (system) {
      systemForm.setFieldsValue(system);
    } else {
      systemForm.resetFields();
      systemForm.setFieldsValue({
        auth_type: 'hmac_callback',
        shared_secret_use_global: true,
        status: 1,
      });
    }
    setSystemModalOpen(true);
  };

  const handleSaveSystemConfig = async () => {
    try {
      const values = await systemForm.validateFields();
      if (editingSystem) {
        await api.put(`/admin/external-systems/config/${editingSystem.provider_id}`, values);
        message.success('外部系统配置更新成功');
      } else {
        await api.post('/admin/external-systems/config', values);
        message.success('外部系统配置添加成功');
      }
      setSystemModalOpen(false);
      loadSystemsConfig();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '保存失败');
    }
  };

  const handleDeleteSystem = async (provider_id: string) => {
    Modal.confirm({
      title: '确认删除',
      content: `确定要删除外部系统配置 "${provider_id}" 吗？`,
      onOk: async () => {
        try {
          await api.delete(`/admin/external-systems/config/${provider_id}`);
          message.success('外部系统配置已删除');
          loadSystemsConfig();
        } catch (e: any) {
          message.error('删除失败');
        }
      },
    });
  };

  // Handle add/edit binding
  const handleBindingModalOpen = (binding?: IdentityBinding) => {
    setEditingBinding(binding || null);
    if (binding) {
      bindingForm.setFieldsValue(binding);
    } else {
      bindingForm.resetFields();
    }
    setBindingModalOpen(true);
  };

  const handleSaveBinding = async () => {
    try {
      const values = await bindingForm.validateFields();
      if (editingBinding) {
        // Unbind first then bind new? Or just update status
        await api.post('/admin/users/identity-bindings/unbind', {
          user_id: editingBinding.user_id,
          provider: editingBinding.provider,
          external_id: editingBinding.external_id,
        });
      }
      await api.post('/admin/users/identity-bindings/bind', values);
      message.success('身份映射绑定成功');
      setBindingModalOpen(false);
      loadBindings();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '保存失败');
    }
  };

  const handleUnbind = async (binding: IdentityBinding) => {
    Modal.confirm({
      title: '确认解绑',
      content: `确定要解除 ${binding.user_id} 与 ${binding.provider} (${binding.external_id}) 的绑定关系吗？`,
      onOk: async () => {
        try {
          await api.post('/admin/users/identity-bindings/unbind', {
            user_id: binding.user_id,
            provider: binding.provider,
            external_id: binding.external_id,
          });
          message.success('身份映射已解绑');
          loadBindings();
        } catch (e: any) {
          message.error('解绑失败');
        }
      },
    });
  };

  // Handle batch import
  const handleBatchImport = async (file: File) => {
    try {
      const text = await file.text();
      const lines = text.split('\n').filter(line => line.trim());
      const bindingsData: Array<{ user_id: string; provider: string; external_id: string }> = [];

      // Skip header if exists
      const startLine = lines[0]?.includes('user_id') ? 1 : 0;
      
      for (let i = startLine; i < lines.length; i++) {
        const parts = lines[i].split(',');
        if (parts.length >= 3) {
          bindingsData.push({
            user_id: parts[0].trim(),
            provider: parts[1].trim(),
            external_id: parts[2].trim(),
          });
        }
      }

      if (bindingsData.length === 0) {
        message.error('CSV文件中没有有效的数据行');
        return;
      }

      const res: any = await api.post('/admin/users/identity-bindings/import-batch', { bindings: bindingsData });
      message.success(`批量导入完成。成功: ${res.stats?.success_count || 0}, 失败: ${res.stats?.failed_count || 0}`);
      loadBindings();
    } catch (e: any) {
      message.error('批量导入失败');
    }
  };

  // Systems config columns
  const systemColumns: ColumnsType<ExternalSystemConfig> = [
    {
      title: '系统编号',
      dataIndex: 'provider_id',
      key: 'provider_id',
    },
    {
      title: '系统名称',
      dataIndex: 'name',
      key: 'name',
    },
    {
      title: '认证类型',
      dataIndex: 'auth_type',
      key: 'auth_type',
      render: (type: string) => <Tag>{type}</Tag>,
    },
    {
      title: '客户端ID',
      dataIndex: 'client_id',
      key: 'client_id',
    },
    {
      title: '回调地址',
      dataIndex: 'callback_url',
      key: 'callback_url',
      ellipsis: true,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: number) => (
        <Tag color={status === 1 ? 'success' : 'error'}>
          {status === 1 ? '启用' : '禁用'}
        </Tag>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      render: (_: any, record: ExternalSystemConfig) => (
        <Space>
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => handleSystemModalOpen(record)}
          >
            编辑
          </Button>
          <Button
            type="link"
            size="small"
            danger
            icon={<DeleteOutlined />}
            onClick={() => handleDeleteSystem(record.provider_id)}
          >
            删除
          </Button>
        </Space>
      ),
    },
  ];

  // Identity bindings columns
  const bindingColumns: ColumnsType<IdentityBinding> = [
    {
      title: '内部用户ID',
      dataIndex: 'user_id',
      key: 'user_id',
    },
    {
      title: '系统名称/Provider',
      dataIndex: 'provider',
      key: 'provider',
    },
    {
      title: '外部系统OpenID/External ID',
      dataIndex: 'external_id',
      key: 'external_id',
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: number) => (
        <Tag color={status === 1 ? 'success' : 'default'}>
          {status === 1 ? '已绑定' : '未绑定'}
        </Tag>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (time?: string) => time || '-',
    },
    {
      title: '操作',
      key: 'actions',
      render: (_: any, record: IdentityBinding) => (
        <Space>
          <Button
            type="link"
            size="small"
            danger
            onClick={() => handleUnbind(record)}
          >
            解绑
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: '24px', minHeight: '100%' }}>
      <PageHeader
        parent="设置"
        current="外部系统用户绑定"
        subRow="管理外部系统集成、授权配置与身份映射关系"
      />

      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: 'systems',
            label: '外部系统配置',
            children: (
              <Card>
                <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between' }}>
                  <Button type="primary" icon={<PlusOutlined />} onClick={() => handleSystemModalOpen()}>
                    添加外部系统
                  </Button>
                  <Button icon={<ReloadOutlined />} onClick={loadSystemsConfig} loading={loading}>
                    刷新
                  </Button>
                </div>

                <Table
                  columns={systemColumns}
                  dataSource={systemsConfig}
                  loading={loading}
                  rowKey="provider_id"
                  locale={{ emptyText: '暂无外部系统配置' }}
                />
              </Card>
            ),
          },
          {
            key: 'bindings',
            label: '身份映射绑定',
            children: (
              <Card>
                <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between' }}>
                  <Space>
                    <Button type="primary" icon={<PlusOutlined />} onClick={() => handleBindingModalOpen()}>
                      手动绑定
                    </Button>
                    <Upload
                      accept=".csv,.txt"
                      beforeUpload={(file) => {
                        handleBatchImport(file);
                        return false; // Prevent auto-upload
                      }}
                    >
                      <Button icon={<ImportOutlined />}>批量导入</Button>
                    </Upload>
                  </Space>
                  <Button icon={<ReloadOutlined />} onClick={loadBindings} loading={loading}>
                    刷新
                  </Button>
                </div>

                <Table
                  columns={bindingColumns}
                  dataSource={bindings}
                  loading={loading}
                  rowKey={(record) => `${record.user_id}-${record.provider}-${record.external_id}`}
                  locale={{ emptyText: '暂无身份映射记录' }}
                />
              </Card>
            ),
          },
        ]}
      />

      {/* System Config Modal */}
      <Modal
        title={editingSystem ? '编辑外部系统配置' : '添加外部系统配置'}
        open={systemModalOpen}
        onCancel={() => setSystemModalOpen(false)}
        onOk={handleSaveSystemConfig}
        width={600}
      >
        <Form form={systemForm} layout="vertical">
          <Form.Item name="provider_id" label="系统编号 (Provider ID)" rules={[{ required: true }]}>
            <Input placeholder="例如: wecom, dingtalk, feishu" disabled={!!editingSystem} />
          </Form.Item>
          <Form.Item name="name" label="系统名称" rules={[{ required: true }]}>
            <Input placeholder="例如: 企业微信" />
          </Form.Item>
          <Form.Item name="auth_type" label="认证类型">
            <Select>
              <Option value="hmac_callback">HMAC回调</Option>
              <Option value="bearer_token">Bearer Token</Option>
              <Option value="api_key">API Key</Option>
            </Select>
          </Form.Item>
          <Form.Item name="client_id" label="客户端ID / App ID">
            <Input placeholder="外部系统的App ID或Client ID" />
          </Form.Item>
          <Form.Item label="共享密钥使用全局配置" name="shared_secret_use_global" valuePropName="checked">
            <Switch />
          </Form.Item>
          {!systemForm.getFieldValue('shared_secret_use_global') && (
            <Form.Item name="shared_secret" label="共享密钥 / Secret">
              <Input.Password placeholder="外部系统通信密钥" />
            </Form.Item>
          )}
          <Form.Item name="callback_url" label="回调地址">
            <Input placeholder="/api/auth/external/login" />
          </Form.Item>
          <Form.Item name="status" label="状态" valuePropName="checked" initialValue={1}>
            <Select>
              <Option value={1}>启用</Option>
              <Option value={0}>禁用</Option>
            </Select>
          </Form.Item>
        </Form>
      </Modal>

      {/* Binding Modal */}
      <Modal
        title={editingBinding ? '编辑身份映射' : '手动绑定外部系统用户'}
        open={bindingModalOpen}
        onCancel={() => setBindingModalOpen(false)}
        onOk={handleSaveBinding}
        width={500}
      >
        <Form form={bindingForm} layout="vertical">
          <Form.Item name="user_id" label="内部用户ID" rules={[{ required: true }]}>
            <Input placeholder="CoApis内部用户名或ID" />
          </Form.Item>
          <Form.Item name="provider" label="系统名称/Provider" rules={[{ required: true }]}>
            <Input placeholder="例如: wecom, dingtalk, feishu" />
          </Form.Item>
          <Form.Item name="external_id" label="外部系统OpenID / External ID" rules={[{ required: true }]}>
            <Input placeholder="外部系统的用户标识或OpenID" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

export default ExternalSystemAuthPage;
