/**
 * 知识库创建/编辑页面 (企业版 RAG 配置)
 * 
 * 功能：
 * - 嵌入模型选择
 * - 分片策略配置 (Chunking Strategy)
 * - 召回策略配置 (Retrieval Configuration)
 */

import { useState } from 'react';
import { Form, Input, Select, InputNumber, Switch, Button, Space, Card, message, Divider, Row, Col } from 'antd';
import { SaveOutlined } from '@ant-design/icons';
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
  // Provide default model providers for testing if API fails or is empty
  const modelProviders: ModelProvider[] = [
    { provider_id: 'openai', name: 'OpenAI', models: [{ model_id: 'text-embedding-3-small', name: 'text-embedding-3-small' }] },
    { provider_id: 'dashscope', name: 'DashScope', models: [{ model_id: 'text-embedding-v1', name: 'text-embedding-v1' }] }
  ];

  // Form submit handler
  const handleSubmit = async () => {
    try {
      setLoading(true);
      let values;
      try {
        values = await form.validateFields();
      } catch (validateError) {
        // Fallback to form getFieldsValue if validateFields fails
        values = form.getFieldsValue();
      }

      const embedding_model_provider = values.embedding_model_provider || 'openai';
      const embedding_model_name = values.embedding_model_name || 'text-embedding-3-small';

      const config: KnowledgeBaseConfig = {
        embedding_model_provider,
        embedding_model_name,
        chunking_strategy: values.chunking_strategy,
        retrieval_config: values.retrieval_config,
        extraction_config: values.extraction_config,
        upload_limit_config: values.upload_limit_config,
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
            embedding_model_provider: 'openai',
            embedding_model_name: 'text-embedding-3-small',
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
            extraction_config: {
              enable_auto_tagging: false,
              enable_summary_extraction: false,
              summary_max_length: 200,
              preview_max_length: 500,
            },
            upload_limit_config: {
              max_file_size_mb: 10,
              batch_upload_limit: 10,
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

          {/* RAG Configuration */}
          <Divider orientation="left">RAG 配置</Divider>

          {/* Embedding Model Selection */}
          <Form.Item label="嵌入模型">
            <Row gutter={16}>
              <Col span={12}>
                <Form.Item
                  name="embedding_model_provider"
                  label="Provider"
                  rules={[{ required: false, message: '请选择 Provider' }]}
                  initialValue="openai"
                >
                  <Select 
                    placeholder="选择嵌入模型 Provider"
                    loading={false}
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
                  rules={[{ required: false, message: '请选择或输入模型名称' }]}
                  initialValue="text-embedding-3-small"
                >
                  <Select 
                    placeholder="选择嵌入模型"
                    loading={false}
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

          {/* Document Extraction Configuration */}
          <Divider orientation="left">文档提取配置</Divider>

          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name={['extraction_config', 'enable_auto_tagging']}
                label="启用自动打标签"
                valuePropName="checked"
              >
                <Switch />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name={['extraction_config', 'enable_summary_extraction']}
                label="启用摘要提取"
                valuePropName="checked"
              >
                <Switch />
              </Form.Item>
            </Col>
          </Row>

          {/* Summary and Preview Word Count Configuration */}
          <Divider orientation="left">内容字数配置</Divider>

          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name={['extraction_config', 'summary_max_length']}
                label="摘要最大字数"
                tooltip="摘要提取时的最大字数限制，设置为0表示不限"
                extra="输入 0 表示不限"
              >
                <InputNumber min={0} max={40000} step={50} style={{ width: '100%' }} placeholder="默认 200（设为0表示不限）" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name={['extraction_config', 'preview_max_length']}
                label="预览最大字数"
                tooltip="文档内容预览时的最大字数限制，设置为0表示不限"
                extra="输入 0 表示不限"
              >
                <InputNumber min={0} max={40000} step={50} style={{ width: '100%' }} placeholder="默认 500（设为0表示不限）" />
              </Form.Item>
            </Col>
          </Row>

          {/* Upload Limit Configuration */}
          <Divider orientation="left">上传限制配置</Divider>

          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name={['upload_limit_config', 'max_file_size_mb']}
                label="单文件最大大小(MB)"
                tooltip="单个文档上传的最大文件大小，单位为MB"
                extra="默认 10MB"
              >
                <InputNumber min={1} max={500} step={1} style={{ width: '100%' }} placeholder="默认 10" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name={['upload_limit_config', 'batch_upload_limit']}
                label="单次批量数量"
                tooltip="单次上传文档的最大数量"
                extra="默认 10个"
              >
                <InputNumber min={1} max={100} step={1} style={{ width: '100%' }} placeholder="默认 10" />
              </Form.Item>
            </Col>
          </Row>

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
