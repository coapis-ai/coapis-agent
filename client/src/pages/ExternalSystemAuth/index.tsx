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
  InputNumber,
  message,
  Tabs,
  Upload,
  Collapse,
} from 'antd';
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  ReloadOutlined,
  ImportOutlined,
  UploadOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { PageHeader } from '@/components/PageHeader';
import api from '@/api';
import ExternalSystemIcon from '@/utils/externalSystemIcon';
import type { ColumnsType } from 'antd/es/table';

const { Option } = Select;

// ---------------------------------------------------------------------------
// 类型定义（新 schema）
// ---------------------------------------------------------------------------

interface SsoCallbackConfig {
  params?: Record<string, string>;
  sign_algorithm?: string;
  sign_string?: string;
  timestamp_ttl?: number;
}

interface SsoConfig {
  login_url?: string;
  login_method?: string;
  post_form_url?: string;
  post_fields?: Record<string, string>;
  callback?: SsoCallbackConfig;
}

interface CredentialConfig {
  api?: Record<string, any>;
  response?: Record<string, any>;
  external_token?: Record<string, any>;
  timeout?: number;
}

interface UserMappingConfig {
  auto_create?: boolean;
  match_existing?: boolean;
  match_by?: string;
  username_prefix?: string;
  seq_start?: number;
  seq_padding?: number;
  display_name_source?: string;
  default_role?: string;
}

interface ExternalSystemConfig {
  provider_id: string;
  name: string;
  icon?: string;
  description?: string;
  login_type?: string; // sso_redirect | credential | none
  sso?: SsoConfig;
  credential?: CredentialConfig;
  user_mapping?: UserMappingConfig;
  show_on_login?: boolean;
  display_order?: number;
  client_id?: string;
  shared_secret_use_global?: boolean;
  shared_secret?: string;
  base_urls?: string[];
  identity_token_ttl?: number;
  status: number;
}

interface IdentityBinding {
  user_id: string;
  provider: string;
  external_id: string;
  external_name?: string | null;
  source?: string; // auto | auto_matched | manual
  status: number;
  created_at?: string;
  last_login_at?: string;
  login_count?: number;
  updated_at?: string;
}

const LOGIN_TYPE_LABELS: Record<string, string> = {
  sso_redirect: 'SSO跳转(A)',
  credential: '凭证直登(B)',
  none: '不登录',
};

const CREDENTIAL_EXAMPLE_RESPONSE = [
  '{',
  '  "code": 0,',
  '  "msg": "ok",',
  '  "data": {',
  '    "userId": "ext_12345",',
  '    "name": "张三",',
  '    "accessToken": "eyJhbGciOi..."',
  '  }',
  '}',
].join('\n');

const CREDENTIAL_EXAMPLE_CONFIG = [
  'success_field = "code"',
  'success_value = 0',
  'openid_field  = "data.userId"',
  'name_field    = "data.name"',
  'token_field   = "data.accessToken"',
].join('\n');

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
      systemForm.setFieldsValue({
        ...system,
        sso: {
          login_method: 'get',
          callback: { sign_algorithm: 'hmac_sha256', timestamp_ttl: 300 },
          ...(system.sso || {}),
        },
        credential: {
          api: { method: 'POST', content_type: 'application/json', url: '', body: '' },
          response: { success_field: 'code', success_value: 0, error_field: 'msg', openid_field: '', name_field: '' },
          profile: { token_field: 'data.accessToken', name_field: '' },
          timeout: 15,
          ...(system.credential || {}),
        },
        user_mapping: {
          auto_create: true,
          match_existing: true,
          match_by: 'username',
          seq_start: 1,
          seq_padding: 4,
          display_name_source: 'external_name',
          default_role: 'user',
          ...(system.user_mapping || {}),
        },
        show_on_login: system.show_on_login !== false,
        display_order: system.display_order ?? 100,
        base_urls: system.base_urls || [],
      });
    } else {
      systemForm.resetFields();
      systemForm.setFieldsValue({
        login_type: 'sso_redirect',
        shared_secret_use_global: true,
        status: 1,
        show_on_login: true,
        display_order: 100,
        sso: {
          login_method: 'get',
          callback: { sign_algorithm: 'hmac_sha256', timestamp_ttl: 300 },
        },
        credential: {
          api: { method: 'POST', content_type: 'application/json', url: '', body: '' },
          response: { success_field: 'code', success_value: 0, error_field: 'msg', openid_field: '', name_field: '' },
          profile: { token_field: 'data.accessToken', name_field: '' },
          timeout: 15,
        },
        user_mapping: {
          auto_create: true,
          match_existing: true,
          match_by: 'username',
          seq_start: 1,
          seq_padding: 4,
          display_name_source: 'external_name',
          default_role: 'user',
        },
        base_urls: [],
      });
    }
    setSystemModalOpen(true);
  };

  const handleSaveSystemConfig = async () => {
    try {
      const values = await systemForm.validateFields();
      // 后端 POST 是 upsert（按 provider_id 更新或新增），新增/编辑统一走 POST
      await api.post('/admin/external-systems/config', values);
      message.success(editingSystem ? '外部系统配置更新成功' : '外部系统配置添加成功');
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
        // 编辑：先解绑再绑
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
      const bindingsData: Array<{ user_id: string; provider: string; external_id: string; external_name?: string }> = [];

      // Skip header if exists
      const startLine = lines[0]?.includes('user_id') ? 1 : 0;

      for (let i = startLine; i < lines.length; i++) {
        const parts = lines[i].split(',');
        if (parts.length >= 3) {
          bindingsData.push({
            user_id: parts[0].trim(),
            provider: parts[1].trim(),
            external_id: parts[2].trim(),
            external_name: parts[3]?.trim() || undefined,
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
      title: '系统',
      dataIndex: 'name',
      key: 'name',
      render: (name: string, record: ExternalSystemConfig) => (
        <Space>
          <ExternalSystemIcon icon={record.icon} name={name} size={28} />
          <span>
            {name}
            <div style={{ fontSize: 12, color: '#999' }}>{record.provider_id}</div>
          </span>
        </Space>
      ),
    },
    {
      title: '登录方式',
      dataIndex: 'login_type',
      key: 'login_type',
      render: (type?: string) => (
        <Tag color={type === 'sso_redirect' ? 'blue' : type === 'credential' ? 'purple' : 'default'}>
          {LOGIN_TYPE_LABELS[type || 'none'] || type || '未配置'}
        </Tag>
      ),
    },
    {
      title: '登录页展示',
      dataIndex: 'show_on_login',
      key: 'show_on_login',
      render: (v?: boolean) => (
        <Tag color={v !== false ? 'success' : 'default'}>{v !== false ? '显示' : '隐藏'}</Tag>
      ),
    },
    {
      title: '出站断言',
      dataIndex: 'base_urls',
      key: 'base_urls',
      render: (urls?: string[]) =>
        urls && urls.length > 0 ? (
          <span style={{ fontSize: 12 }} title={urls.join('\n')}>
            {urls.length} 个域名
          </span>
        ) : (
          <span style={{ color: '#bbb' }}>-</span>
        ),
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
      title: '内部用户',
      dataIndex: 'user_id',
      key: 'user_id',
    },
    {
      title: '显示名',
      dataIndex: 'external_name',
      key: 'external_name',
      render: (v?: string | null) => v || <span style={{ color: '#bbb' }}>-</span>,
    },
    {
      title: '系统 Provider',
      dataIndex: 'provider',
      key: 'provider',
    },
    {
      title: '外部ID',
      dataIndex: 'external_id',
      key: 'external_id',
    },
    {
      title: '来源',
      dataIndex: 'source',
      key: 'source',
      render: (v?: string) => {
        const map: Record<string, { label: string; color: string }> = {
          auto: { label: '自动创建', color: 'blue' },
          auto_matched: { label: '自动匹配', color: 'green' },
          manual: { label: '手动绑定', color: 'default' },
        };
        const item = v ? map[v] : undefined;
        return item ? <Tag color={item.color}>{item.label}</Tag> : <Tag>-</Tag>;
      },
    },
    {
      title: '最近登录',
      dataIndex: 'last_login_at',
      key: 'last_login_at',
      render: (v?: string) => v || <span style={{ color: '#bbb' }}>-</span>,
    },
    {
      title: '登录次数',
      dataIndex: 'login_count',
      key: 'login_count',
      render: (v?: number) => v ?? 0,
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
      title: '操作',
      key: 'actions',
      render: (_: any, record: IdentityBinding) => (
        <Space>
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => handleBindingModalOpen(record)}
          >
            编辑
          </Button>
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
        subRow="管理外部系统集成、登录配置、出站身份断言与身份映射关系"
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
        width={720}
        destroyOnClose
      >
        <Form form={systemForm} layout="vertical">
          <Form.Item
            label="基础信息"
            style={{ marginBottom: 0, fontSize: 13, fontWeight: 600, color: '#888' }}
          />
          <Form.Item name="provider_id" label="系统编号 (Provider ID)" rules={[{ required: true }]}>
            <Input placeholder="例如: wecom, dingtalk, feishu, sczrsz_oa" disabled={!!editingSystem} />
          </Form.Item>
          <div style={{ display: 'flex', gap: 12 }}>
            <Form.Item name="name" label="系统名称" rules={[{ required: true }]} style={{ flex: 1 }}>
              <Input placeholder="例如: 企业微信" />
            </Form.Item>
            <Form.Item name="icon" label="图标" style={{ width: 180 }}
              tooltip="支持上传图片（自动压缩为 96px base64）或输入 emoji"
            >
              <Upload
                listType="picture"
                accept="image/*"
                maxCount={1}
                beforeUpload={(file) => {
                  // 前端压缩为 96px base64
                  const reader = new FileReader();
                  reader.onload = (e) => {
                    const img = new Image();
                    img.onload = () => {
                      const canvas = document.createElement('canvas');
                      const size = 96;
                      canvas.width = size;
                      canvas.height = size;
                      const ctx = canvas.getContext('2d')!;
                      // 居中裁切
                      const minDim = Math.min(img.width, img.height);
                      const sx = (img.width - minDim) / 2;
                      const sy = (img.height - minDim) / 2;
                      ctx.drawImage(img, sx, sy, minDim, minDim, 0, 0, size, size);
                      const dataUrl = canvas.toDataURL('image/png');
                      systemForm.setFieldValue('icon', dataUrl);
                    };
                    img.src = e.target?.result as string;
                  };
                  reader.readAsDataURL(file);
                  return false; // Prevent auto-upload
                }}
              >
                <Button icon={<UploadOutlined />}>上传图标</Button>
              </Upload>
            </Form.Item>
          </div>
          {/* 图标预览 */}
          <Form.Item noStyle shouldUpdate={(prev, cur) => prev.icon !== cur.icon}>
            {({ getFieldValue }) => {
              const icon = getFieldValue('icon');
              return icon ? (
                <div style={{ marginBottom: 12 }}>
                  <span style={{ fontSize: 12, color: '#888', marginRight: 8 }}>预览：</span>
                  <ExternalSystemIcon icon={icon} size={36} />
                </div>
              ) : null;
            }}
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input placeholder="可选，备注说明" />
          </Form.Item>
          <Form.Item name="status" label="状态" valuePropName="checked" initialValue={1}>
            <Select>
              <Option value={1}>启用</Option>
              <Option value={0}>禁用</Option>
            </Select>
          </Form.Item>

          <Form.Item
            label="登录配置（用户在登录页通过外部系统登录）"
            style={{ marginBottom: 0, fontSize: 13, fontWeight: 600, color: '#888', marginTop: 8 }}
          />
          <div style={{ display: 'flex', gap: 12 }}>
            <Form.Item name={['login_type']} label="登录方式" style={{ flex: 1 }} rules={[{ required: true }]}>
              <Select>
                <Option value="sso_redirect">SSO 跳转（模型A）</Option>
                <Option value="credential">凭证直登（模型B，二期）</Option>
                <Option value="none">不登录（仅出站身份断言）</Option>
              </Select>
            </Form.Item>
            <Form.Item name="show_on_login" label="登录页显示" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Form.Item name="display_order" label="排序" style={{ width: 90 }}>
              <InputNumber min={0} max={9999} />
            </Form.Item>
          </div>

          {/* 模型A：SSO 跳转 */}
          <Form.Item noStyle shouldUpdate={(prev, cur) => prev.login_type !== cur.login_type}>
            {({ getFieldValue }) =>
              getFieldValue('login_type') === 'sso_redirect' ? (
                <>
                  <Form.Item
                    name={['sso', 'login_url']}
                    label="外部系统登录页 URL 模板"
                    tooltip="占位符：{client_id} {state} {redirect}（redirect 自动渲染为 CoApis 绝对回调地址）"
                    rules={[{ required: true, message: 'SSO 跳转方式必须配置登录页 URL' }]}
                  >
                    <Input placeholder="https://oa.example.com/sso/login?client_id={client_id}&state={state}&redirect={redirect}" />
                  </Form.Item>
                  <div style={{ display: 'flex', gap: 12 }}>
                    <Form.Item name={['sso', 'login_method']} label="跳转方式" style={{ flex: 1 }}>
                      <Select>
                        <Option value="get">GET 跳转（302）</Option>
                        <Option value="post">POST 表单（复杂场景）</Option>
                      </Select>
                    </Form.Item>
                    <Form.Item name={['client_id']} label="Client ID" style={{ flex: 1 }}>
                      <Input placeholder="外部系统分配给 CoApis 的 Client ID" />
                    </Form.Item>
                  </div>
                  <Form.Item
                    name={['sso', 'callback', 'sign_string']}
                    label="签名串模板"
                    tooltip="外部系统按此模板 + 共享密钥计算 HMAC-SHA256 签名。占位符：{provider} {external_id} {timestamp}。留空使用默认格式 provider=..&external_id=..&timestamp=.."
                  >
                    <Input placeholder="provider={provider}&external_id={external_id}&timestamp={timestamp}" />
                  </Form.Item>
                  <Form.Item name={['sso', 'callback', 'timestamp_ttl']} label="回调防重放窗口（秒）" initialValue={300}>
                    <InputNumber min={30} max={3600} style={{ width: 200 }} />
                  </Form.Item>
                </>
              ) : null
            }
          </Form.Item>

          {/* 模型B：凭证直登 — 完整配置 */}
          <Form.Item noStyle shouldUpdate={(prev, cur) => prev.login_type !== cur.login_type}>
            {({ getFieldValue }) =>
              getFieldValue('login_type') === 'credential' ? (
                <>
                  <Collapse
                    defaultActiveKey={['api', 'response']}
                    style={{ marginBottom: 12 }}
                    items={[
                      {
                        key: 'api',
                        label: '登录 API 配置',
                        children: (
                          <>
                            <Form.Item
                              name={['credential', 'api', 'url']}
                              label="登录接口 URL"
                              rules={[{ required: true, message: '请输入登录接口 URL' }]}
                            >
                              <Input placeholder="https://oa.example.com/api/login" />
                            </Form.Item>
                            <div style={{ display: 'flex', gap: 12 }}>
                              <Form.Item name={['credential', 'api', 'method']} label="方法" initialValue="POST">
                                <Select>
                                  <Option value="POST">POST</Option>
                                  <Option value="GET">GET</Option>
                                </Select>
                              </Form.Item>
                              <Form.Item name={['credential', 'api', 'content_type']} label="Content-Type" initialValue="application/json">
                                <Select>
                                  <Option value="application/json">application/json</Option>
                                  <Option value="application/x-www-form-urlencoded">form-urlencoded</Option>
                                </Select>
                              </Form.Item>
                            </div>
                            <Form.Item
                              name={['credential', 'api', 'body']}
                              label="请求 Body 模板"
                              tooltip="JSON 格式，支持 {username} {password} 占位符"
                              rules={[{ required: true, message: '请输入请求 Body' }]}
                            >
                              <Input.TextArea
                                rows={3}
                                placeholder={'{"username": "{username}", "password": "{password}"}'}
                              />
                            </Form.Item>
                            <Form.Item
                              name={['credential', 'api', 'headers']}
                              label="自定义 Headers"
                              tooltip={'JSON 格式，如 {"X-App-Id": "12345"}'}
                            >
                              <Input.TextArea rows={2} placeholder='{"X-App-Id": "12345"}' />
                            </Form.Item>
                          </>
                        ),
                      },
                      {
                        key: 'response',
                        label: '响应解析配置',
                        children: (
                          <>
                            <div style={{ display: 'flex', gap: 12 }}>
                              <Form.Item name={['credential', 'response', 'success_field']} label="成功字段" initialValue="code">
                                <Input placeholder="如 code" />
                              </Form.Item>
                              <Form.Item name={['credential', 'response', 'success_value']} label="成功值" initialValue={0}>
                                <Input placeholder="如 0" />
                              </Form.Item>
                              <Form.Item name={['credential', 'response', 'error_field']} label="错误信息字段" initialValue="msg">
                                <Input placeholder="如 msg" />
                              </Form.Item>
                            </div>
                            <div style={{ display: 'flex', gap: 12 }}>
                              <Form.Item
                                name={['credential', 'response', 'openid_field']}
                                label="用户ID字段（openid）"
                                tooltip="支持点号路径，如 data.userId"
                                rules={[{ required: true, message: '必填' }]}
                              >
                                <Input placeholder="如 data.userId" />
                              </Form.Item>
                              <Form.Item name={['credential', 'response', 'name_field']} label="姓名字段（可选）" tooltip="支持点号路径，如 data.name">
                                <Input placeholder="如 data.name" />
                              </Form.Item>
                            </div>
                            <div style={{ display: 'flex', gap: 12 }}>
                              <Form.Item name={['credential', 'profile', 'url']} label="Profile 接口（可选）" tooltip="登录响应无姓名时，用 access token 调此接口获取">
                                <Input placeholder="https://oa.example.com/api/profile" />
                              </Form.Item>
                              <Form.Item name={['credential', 'profile', 'token_field']} label="Token 字段" initialValue="data.accessToken" tooltip="从登录响应中提取 token 的点号路径">
                                <Input placeholder="data.accessToken" />
                              </Form.Item>
                              <Form.Item name={['credential', 'profile', 'name_field']} label="Profile 姓名字段">
                                <Input placeholder="如 name" />
                              </Form.Item>
                            </div>
                          </>
                        ),
                      },
                      {
                        key: 'example',
                        label: '数据示例（参考）',
                        children: (
                          <div style={{ fontSize: 12, background: '#f6f8fa', padding: 12, borderRadius: 6, overflow: 'auto' }}>
                            <p style={{ marginBottom: 8, fontWeight: 600 }}>响应示例：</p>
                            <pre style={{ margin: 0, fontSize: 11, whiteSpace: 'pre-wrap' }}>{CREDENTIAL_EXAMPLE_RESPONSE}</pre>
                            <p style={{ margin: '8px 0 8px', fontWeight: 600 }}>配置对应：</p>
                            <pre style={{ margin: 0, fontSize: 11, whiteSpace: 'pre-wrap' }}>{CREDENTIAL_EXAMPLE_CONFIG}</pre>
                          </div>
                        ),
                      },
                    ]}
                  />
                  {/* 测试连接 */}
                  <Form.Item noStyle shouldUpdate>
                    {() => {
                      const provider = systemForm.getFieldValue('provider_id');
                      return (
                        <Button
                          type="dashed"
                          icon={<ThunderboltOutlined />}
                          onClick={async () => {
                            // 让用户输入测试账号
                            Modal.confirm({
                              title: '测试连接 — 输入测试账号',
                              content: (
                                <div>
                                  <p>使用配置的 API 测试连通性（不会建用户）</p>
                                  <Input id="test-username" placeholder="测试用户名" />
                                  <br />
                                  <Input.Password id="test-password" placeholder="测试密码" style={{ marginTop: 8 }} />
                                </div>
                              ),
                              onOk: async () => {
                                const u = (document.getElementById('test-username') as HTMLInputElement)?.value || '';
                                const p = (document.getElementById('test-password') as HTMLInputElement)?.value || '';
                                if (!u || !p) { message.warning('请输入测试账号'); return; }
                                try {
                                  const res: any = await api.post('/auth/external/credential-test', {
                                    provider, username: u, password: p,
                                  });
                                  if (res.success) {
                                    message.success(`连接成功！external_id=${res.external_id || '(未配置)'}, name=${res.external_name || '(无)'}`);
                                  } else {
                                    message.error(res.error || '测试失败');
                                  }
                                } catch (e: any) {
                                  message.error(e?.response?.data?.detail || '测试失败');
                                }
                              },
                            });
                          }}
                          disabled={!provider}
                          style={{ marginBottom: 12 }}
                        >
                          测试连接
                        </Button>
                      );
                    }}
                  </Form.Item>
                </>
              ) : null
            }
          </Form.Item>

          <Form.Item
            label="用户映射（SSO 登录时自动创建用户）"
            style={{ marginBottom: 0, fontSize: 13, fontWeight: 600, color: '#888', marginTop: 8 }}
          />
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            <Form.Item name={['user_mapping', 'auto_create']} label="自动创建用户" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Form.Item
              name={['user_mapping', 'match_existing']}
              label="匹配已有用户"
              valuePropName="checked"
              tooltip="自动建用户前，先按匹配键大小写不敏感查找本地已有用户；匹配到则补全绑定关系（不新建用户）"
            >
              <Switch />
            </Form.Item>
            <Form.Item name={['user_mapping', 'match_by']} label="匹配键" style={{ width: 220 }}>
              <Select>
                <Option value="username">用户名（外部登录名 → 本地用户名）</Option>
                <Option value="external_name">姓名（外部姓名 → 本地显示名）</Option>
              </Select>
            </Form.Item>
            <Form.Item name={['user_mapping', 'username_prefix']} label="用户名前缀" style={{ width: 150 }}>
              <Input placeholder="如 oa（生成 oa_0001）" />
            </Form.Item>
            <Collapse
              ghost
              size="small"
              style={{ width: 240 }}
              items={[{
                key: 'seq',
                label: <span style={{ fontSize: 12, color: '#888' }}>序号配置（高级）</span>,
                children: (
                  <div style={{ display: 'flex', gap: 12 }}>
                    <Form.Item name={['user_mapping', 'seq_padding']} label="位数" style={{ marginBottom: 0 }}>
                      <InputNumber min={1} max={8} style={{ width: 70 }} />
                    </Form.Item>
                    <Form.Item name={['user_mapping', 'seq_start']} label="起始" style={{ marginBottom: 0 }}>
                      <InputNumber min={1} style={{ width: 70 }} />
                    </Form.Item>
                  </div>
                ),
              }]}
            />
          </div>
          <div style={{ display: 'flex', gap: 12 }}>
            <Form.Item name={['user_mapping', 'display_name_source']} label="显示名来源" style={{ flex: 1 }}>
              <Select>
                <Option value="external_name">外部系统姓名（external_name）</Option>
                <Option value="external_id">外部ID（external_id）</Option>
                <Option value="username">用户名（username）</Option>
              </Select>
            </Form.Item>
            <Form.Item name={['user_mapping', 'default_role']} label="默认角色" style={{ flex: 1 }}>
              <Select>
                <Option value="user">普通用户 (user)</Option>
                <Option value="advanced">高级用户 (advanced)</Option>
                <Option value="admin">管理员 (admin)</Option>
              </Select>
            </Form.Item>
          </div>

          <Form.Item
            label="出站身份断言（CoApis 访问外部系统时携带签名身份）"
            style={{ marginBottom: 0, fontSize: 13, fontWeight: 600, color: '#888', marginTop: 8 }}
          />
          <Form.Item
            name="base_urls"
            label="外部系统域名前缀"
            tooltip="最长前缀匹配，命中即注入签名身份。与已有其他系统的域名重叠会被拦截（409）"
          >
            <Select mode="tags" placeholder="输入域名后回车，如 https://oa.example.com" open={false} />
          </Form.Item>
          <Form.Item label="共享密钥使用全局配置" name="shared_secret_use_global" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(prev, cur) => prev.shared_secret_use_global !== cur.shared_secret_use_global}>
            {({ getFieldValue }) =>
              getFieldValue('shared_secret_use_global') === false ? (
                <Form.Item name="shared_secret" label="共享密钥 / Secret" tooltip="与出站身份断言共用；外部系统用它验签">
                  <Input.Password placeholder="外部系统通信密钥" />
                </Form.Item>
              ) : null
            }
          </Form.Item>
          <Form.Item name="identity_token_ttl" label="身份断言有效期（秒）" initialValue={3600}>
            <InputNumber min={60} max={86400} style={{ width: 200 }} />
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
          <Form.Item name="provider" label="系统编号 / Provider" rules={[{ required: true }]}>
            <Input placeholder="例如: wecom, dingtalk, feishu" disabled={!!editingBinding} />
          </Form.Item>
          <Form.Item name="external_id" label="外部系统OpenID / External ID" rules={[{ required: true }]}>
            <Input placeholder="外部系统的用户标识或OpenID" disabled={!!editingBinding} />
          </Form.Item>
          <Form.Item name="external_name" label="显示名（外部系统姓名）">
            <Input placeholder="可选，如: 张三" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

export default ExternalSystemAuthPage;
