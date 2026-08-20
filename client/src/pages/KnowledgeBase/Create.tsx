/**
 * 知识库创建/编辑页面 (企业版 RAG 配置)
 * 
 * 功能：
 * - 嵌入模型选择
 * - 分片策略配置 (Chunking Strategy)
 * - 召回策略配置 (Retrieval Configuration)
 */

import { useState, useEffect } from 'react';
import { Form, Input, Select, InputNumber, Switch, Button, Space, Card, message, Divider, Row, Col } from 'antd';
import { SaveOutlined, UserOutlined, TeamOutlined } from '@ant-design/icons';
import { useNavigate, useParams } from 'react-router-dom';
import { PageHeader } from '@/components/PageHeader';
import { knowledgeApi, type KnowledgeBaseConfig, type ModelProvider } from '@/api/modules/knowledge';

const { TextArea } = Input;

export default function KnowledgeBaseCreatePage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const isEdit = !!id;
  
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [modelProviders, setModelProviders] = useState<ModelProvider[]>([]);

  // Load model providers on mount
  useEffect(() => {
    loadModels();
  }, []);

  const loadModels = async () => {
    try {
      setModelsLoading(true);
      const res = await knowledgeApi.getModels();
      // Normalize response to ModelProvider array
      const providers: ModelProvider[] = (res || []).map((item: any) => ({
        provider_id: item.provider_id || item.id,
        name: item.name || item.provider_name,
        models: item.models || [],
      }));
      setModelProviders(providers);
    } catch (error) {
      console.error('加载模型列表失败:', error);
      message.error('加载模型列表失败');
    } finally {
      setModelsLoading(false);
    }
  };

  // Form submit handler
  const handleSubmit = async () => {
    try {
      setLoading(true);
      const values = await form.validateFields();
      
      const config: KnowledgeBaseConfig = {
        embedding_model_provider: values.embedding_model_provider,
        embedding_model_name: values.embedding_model_name,
        chunking_strategy: values.chunking_strategy,
        retrieval_config: values.retrieval_config,
      };

      if (isEdit) {
        await knowledgeApi.updateBaseConfig(id!, config);
        message.success('知识库配置更新成功');
      } else {
        await knowledgeApi.createBaseWithConfig({
          name: values.name,
          description: values.description,
          scope: values.scope || 'user',
          config,
        });
        message.success('创建知识库成功');
      }

      navigate('/knowledge/bases');
    } catch (error) {
      console.error(isEdit ? '更新配置失败:' : '创建知识库失败:', error);
      if (!(error as any).errorFields) {
        message.error(isEdit ? '更新配置失败' : '创建知识库失败');
      }
    } finally {
      setLoading(false);
    }
  };

  // Chunking strategy splitter type change handler
  const handleSplitterTypeChange = (value: string) => {
    form.setFieldsValue({
      chunking_strategy: {
        ...form.getFieldValue('chunking_strategy'),
        splitter_type: value,
      },
    });
  };

  return (
    <div style={{ padding: 24 }}>
      <PageHeader 
        parent="知识库管理"
        current={isEdit ? '编辑知识库配置' : '新建知识库'}
        backTo="/knowledge/bases"
      />

      <Card>
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            scope: 'user',
            embedding_model_provider: '',
            chunking_strategy: {
              splitter_type: 'recursive_character',
              chunk_size: 1000,
              chunk_overlap: 200,
              separators: ['\n\n', '\n', ' ', ''],
            },
            retrieval_config: {
              enable_hybrid_search: true,
              use_parent_document_retriever: false,
            },
          }}
        >
          {/* Basic Info */}
          <Divider orientation="left">基本信息</Divider>
          
          <Form.Item
            name="name"
            label="知识库名称"
            rules={[{ required: true, message: '请输入知识库名称' }]}
          >
            <Input placeholder="例如：产品文档库" maxLength={100} />
          </Form.Item>

          <Form.Item
            name="description"
            label="描述"
          >
            <TextArea rows={2} placeholder="知识库用途说明" maxLength={500} />
          </Form.Item>

          <Form.Item
            name="scope"
            label="作用域"
            rules={[{ required: true }]}
          >
            <Select>
              <Select.Option value="global">全局</Select.Option>
              <Select.Option value="user">用户</Select.Option>
              <Select.Option value="agent">智能体</Select.Option>
            </Select>
          </Form.Item>

          {/* 归属与权限分配 */}
          <Divider orientation="left">归属与权限分配</Divider>
          
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="owner_name" label="负责人姓名" tooltip="知识库负责人">
                <Input prefix={<UserOutlined />} placeholder="请输入负责人姓名" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="owner_id" label="负责人 ID">
                <Input placeholder="用户/账号 ID" />
              </Form.Item>
            </Col>
          </Row>

          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="department" label="部门">
                <Input placeholder="所属部门" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="team_id" label="团队 ID">
                <Input prefix={<TeamOutlined />} placeholder="团队 ID" />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item
            name="visibility"
            label="可见性"
            tooltip="控制知识库的访问范围"
            initialValue="team"
          >
            <Select>
              <Select.Option value="private">私有（仅自己可见）</Select.Option>
              <Select.Option value="team">团队可见</Select.Option>
              <Select.Option value="organization">组织可见</Select.Option>
            </Select>
          </Form.Item>

          <Divider orientation="left">角色权限分配</Divider>
          
          <Form.Item name="read_roles" label="读权限角色" tooltip="可读取知识库的角色">
            <Select mode="tags" placeholder="输入角色，回车添加（默认：team_member）" />
          </Form.Item>

          <Form.Item name="write_roles" label="写权限角色" tooltip="可向知识库添加/修改文档的角色">
            <Select mode="tags" placeholder="输入角色，回车添加（默认：team_admin）" />
          </Form.Item>

          <Form.Item name="admin_roles" label="管理权限角色" tooltip="可管理知识库配置与权限的角色">
            <Select mode="tags" placeholder="输入角色，回车添加（默认：owner）" />
          </Form.Item>

          {/* RAG Configuration */}
          <Divider orientation="left">RAG 配置</Divider>

          {/* Embedding Model Selection */}
          <Form.Item label="嵌入模型" required>
            <Row gutter={16}>
              <Col span={12}>
                <Form.Item
                  name="embedding_model_provider"
                  label="Provider"
                  rules={[{ required: true, message: '请选择 Provider' }]}
                >
                  <Select 
                    placeholder="选择嵌入模型 Provider"
                    loading={modelsLoading}
                    showSearch
                    optionFilterProp="children"
                  >
                    {modelProviders.map((provider) => (
                      <Select.Option key={provider.provider_id} value={provider.provider_id}>
                        {provider.name} ({provider.provider_id})
                      </Select.Option>
                    ))}
                  </Select>
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item
                  name="embedding_model_name"
                  label="模型名称"
                  rules={[{ required: true, message: '请选择或输入模型名称' }]}
                >
                  <Select 
                    placeholder="选择嵌入模型"
                    loading={modelsLoading}
                    showSearch
                    optionFilterProp="children"
                  >
                    {modelProviders.flatMap(p => 
                      (p.models || []).map(m => (
                        <Select.Option key={`${p.provider_id}:${m.model_id}`} value={m.model_id}>
                          {m.name || m.model_id} ({p.name})
                        </Select.Option>
                      ))
                    )}
                  </Select>
                </Form.Item>
              </Col>
            </Row>
          </Form.Item>

          {/* Chunking Strategy */}
          <Divider orientation="left">分片策略 (Chunking Strategy)</Divider>
          
          <Form.Item
            name={['chunking_strategy', 'splitter_type']}
            label="切分器类型"
            rules={[{ required: true }]}
          >
            <Select onChange={handleSplitterTypeChange}>
              <Select.Option value="recursive_character">递归字符切分 (Recursive Character)</Select.Option>
              <Select.Option value="markdown_header">Markdown 标题切分</Select.Option>
              <Select.Option value="token">Token 切分</Select.Option>
            </Select>
          </Form.Item>

          <Row gutter={16}>
            <Col span={8}>
              <Form.Item
                name={['chunking_strategy', 'chunk_size']}
                label="块大小 (Chunk Size)"
                rules={[{ required: true, type: 'number', min: 100, max: 5000 }]}
              >
                <InputNumber style={{ width: '100%' }} placeholder="默认 1000" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                name={['chunking_strategy', 'chunk_overlap']}
                label="重叠度 (Overlap)"
                rules={[{ required: true, type: 'number', min: 0, max: 1000 }]}
              >
                <InputNumber style={{ width: '100%' }} placeholder="默认 200" />
              </Form.Item>
            </Col>
          </Row>

          {/* Retrieval Configuration */}
          <Divider orientation="left">召回策略 (Retrieval Configuration)</Divider>

          <Form.Item
            name={['retrieval_config', 'enable_hybrid_search']}
            label="混合搜索 (Hybrid Search)"
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>

          <Form.Item
            name={['retrieval_config', 'use_parent_document_retriever']}
            label="父子文档检索 (Parent Document Retriever)"
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>

          {/* Submit Buttons */}
          <Divider />
          <Form.Item>
            <Space>
              <Button onClick={() => navigate('/knowledge/bases')}>取消</Button>
              <Button type="primary" icon={<SaveOutlined />} loading={loading} onClick={handleSubmit}>
                {isEdit ? '保存配置' : '创建知识库'}
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
}
