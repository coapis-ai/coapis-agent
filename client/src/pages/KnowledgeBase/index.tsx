/**
 * 知识库管理页面
 * 
 * 基于社区版架构，扩展企业版功能
 * 
 * 功能：
 * - 知识库CRUD（社区版基础）
 * - 文档管理（社区版基础）
 * - 权限管理（企业版扩展）
 * - 部门关联（企业版扩展）
 */

import { useState, useEffect } from 'react';
import { 
  Table, Button, Space, Tag, Drawer, Form, Input, message, Card, Descriptions, Popconfirm, Upload
} from 'antd';
import { useNavigate } from 'react-router-dom';
import { 
  PlusOutlined, DeleteOutlined, FileTextOutlined, SafetyOutlined, UploadOutlined, EditOutlined
} from '@ant-design/icons';
import type { UploadProps } from 'antd';
import { knowledgeApi, type KnowledgeBase, type KnowledgeDocument } from '@/api/modules/knowledge';
import { PageHeader } from '@/components/PageHeader';

export default function KnowledgeBasePage() {
  const navigate = useNavigate();
  const [bases, setBases] = useState<KnowledgeBase[]>([]);
  const [loading, setLoading] = useState(false);
  
  // 文档管理抽屉
  const [docDrawerOpen, setDocDrawerOpen] = useState(false);
  const [currentKb, setCurrentKb] = useState<KnowledgeBase | null>(null);
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [docLoading, setDocLoading] = useState(false);
  
  // 权限管理抽屉（企业版功能）
  const [permissionDrawerOpen, setPermissionDrawerOpen] = useState(false);
  
  // 编辑知识库抽屉
  const [editDrawerOpen, setEditDrawerOpen] = useState(false);
  const [editingKb, setEditingKb] = useState<KnowledgeBase | null>(null);
  const [editForm] = Form.useForm();

  // 加载知识库列表
  useEffect(() => {
    loadBases();
  }, []);

  const loadBases = async () => {
    setLoading(true);
    try {
      const res = await knowledgeApi.listBases();
      // 后端返回 kb_id，前端组件使用 id，统一映射避免 undefined
      const mapped = (res.items || []).map((item: any) => ({
        ...item,
        id: item.kb_id || item.id || item._id,
      }));
      setBases(mapped);
    } catch (error) {
      console.error('加载知识库失败:', error);
      message.error('加载知识库失败');
    } finally {
      setLoading(false);
    }
  };

  // 删除知识库
  const handleDelete = async (kbId: string) => {
    try {
      await knowledgeApi.deleteBase(kbId);
      message.success('删除成功');
      loadBases();
    } catch (error) {
      console.error('删除知识库失败:', error);
      message.error('删除失败');
    }
  };

  // 打开编辑抽屉
  const openEditDrawer = (kb: KnowledgeBase) => {
    setEditingKb(kb);
    editForm.setFieldsValue({
      name: kb.name,
      description: kb.description,
    });
    setEditDrawerOpen(true);
  };

  // 保存编辑
  const handleEditSave = async () => {
    try {
      const values = await editForm.validateFields();
      if (!editingKb) return;
      
      await knowledgeApi.updateBase(editingKb.id, values);
      message.success('更新成功');
      setEditDrawerOpen(false);
      loadBases();
    } catch (error) {
      console.error('更新知识库失败:', error);
      message.error('更新失败');
    }
  };

  // 打开文档管理
  const openDocDrawer = async (kb: KnowledgeBase) => {
    setCurrentKb(kb);
    setDocDrawerOpen(true);
    setDocLoading(true);
    try {
      const res = await knowledgeApi.listDocuments(kb.id);
      setDocuments(res.documents || []);
    } catch (error) {
      console.error('加载文档失败:', error);
      message.error('加载文档失败');
    } finally {
      setDocLoading(false);
    }
  };

  // 上传文档
  const uploadProps: UploadProps = {
    name: 'file',
    multiple: true,
    showUploadList: false,
    customRequest: async (options) => {
      const { file, onSuccess, onError } = options;
      if (!currentKb) return;
      
      try {
        await knowledgeApi.uploadDocument(currentKb.id, file as File);
        message.success('上传成功');
        onSuccess?.(file);
        // 刷新文档列表
        const res = await knowledgeApi.listDocuments(currentKb.id);
        setDocuments(res.documents || []);
      } catch (error) {
        console.error('上传文档失败:', error);
        message.error('上传失败');
        onError?.(new Error('上传失败'));
      }
    },
  };

  // 删除文档
  const handleDeleteDoc = async (docId: string) => {
    try {
      await knowledgeApi.deleteDocument(docId);
      message.success('删除成功');
      // 刷新文档列表
      if (currentKb) {
        const res = await knowledgeApi.listDocuments(currentKb.id);
        setDocuments(res.documents || []);
      }
    } catch (error) {
      console.error('删除文档失败:', error);
      message.error('删除失败');
    }
  };

  // 表格列
  const columns = [
    {
      title: '知识库名称',
      dataIndex: 'name',
      key: 'name',
      width: 200,
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      width: 250,
      ellipsis: true,
    },
    {
      title: '作用域',
      dataIndex: 'scope',
      key: 'scope',
      width: 100,
      render: (scope: string) => {
        const map: Record<string, string> = {
          global: '全局',
          user: '用户',
          agent: '智能体',
        };
        return map[scope] || scope;
      },
    },
    {
      title: '文档数',
      dataIndex: 'chunk_count',
      key: 'chunk_count',
      width: 100,
      render: (count: number) => count || 0,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string) => {
        const map: Record<string, { color: string; text: string }> = {
          active: { color: 'success', text: '正常' },
          inactive: { color: 'default', text: '停用' },
        };
        const config = map[status] || map.active;
        return <Tag color={config.color}>{config.text}</Tag>;
      },
    },
    {
      title: '操作',
      key: 'actions',
      width: 200,
      render: (_: unknown, record: KnowledgeBase) => (
        <Space>
          <Button 
            size="small" 
            icon={<FileTextOutlined />}
            onClick={() => openDocDrawer(record)}
          >
            文档
          </Button>
          {/* 企业版：权限管理按钮 */}
          <Button 
            size="small" 
            icon={<SafetyOutlined />}
            onClick={() => {
              setCurrentKb(record);
              setPermissionDrawerOpen(true);
            }}
          >
            权限
          </Button>
          <Button 
            size="small" 
            icon={<EditOutlined />}
            onClick={() => openEditDrawer(record)}
          >
            编辑
          </Button>
          <Popconfirm
            title="确定删除此知识库？"
            onConfirm={() => handleDelete(record.id)}
          >
            <Button size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  // 文档表格列
  const docColumns = [
    {
      title: '文档标题',
      dataIndex: 'title',
      key: 'title',
    },
    {
      title: '来源',
      dataIndex: 'source',
      key: 'source',
      width: 150,
    },
    {
      title: '分片数',
      dataIndex: 'chunk_count',
      key: 'chunk_count',
      width: 100,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string) => {
        const map: Record<string, { color: string; text: string }> = {
          completed: { color: 'success', text: '已完成' },
          processing: { color: 'processing', text: '处理中' },
          failed: { color: 'error', text: '失败' },
        };
        const config = map[status] || map.completed;
        return <Tag color={config.color}>{config.text}</Tag>;
      },
    },
    {
      title: '操作',
      key: 'actions',
      width: 100,
      render: (_: unknown, record: KnowledgeDocument) => (
        <Popconfirm
          title="确定删除此文档？"
          onConfirm={() => handleDeleteDoc(record.id)}
        >
          <Button size="small" danger>删除</Button>
        </Popconfirm>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <PageHeader 
        parent="设置"
        current="知识库管理"
      />

      <Card>
        <div style={{ marginBottom: 16 }}>
          <Button 
            type="primary" 
            icon={<PlusOutlined />}
            onClick={() => navigate('/knowledge/bases/create')}
          >
            创建知识库（高级配置）
          </Button>
        </div>

        <Table
          dataSource={bases}
          columns={columns}
          rowKey="id"
          loading={loading}
          pagination={{ pageSize: 10 }}
        />
      </Card>

      {/* 文档管理抽屉 */}
      <Drawer
        title={`文档管理 - ${currentKb?.name || ''}`}
        width={800}
        open={docDrawerOpen}
        onClose={() => setDocDrawerOpen(false)}
      >
        <div style={{ marginBottom: 16 }}>
          <Upload {...uploadProps}>
            <Button icon={<UploadOutlined />}>上传文档</Button>
          </Upload>
        </div>

        <Table
          dataSource={documents}
          columns={docColumns}
          rowKey="id"
          loading={docLoading}
          pagination={{ pageSize: 10 }}
        />
      </Drawer>

      {/* 编辑知识库抽屉 */}
      <Drawer
        title={`编辑知识库 - ${editingKb?.name || ''}`}
        width={500}
        open={editDrawerOpen}
        onClose={() => setEditDrawerOpen(false)}
        extra={
          <Button type="primary" onClick={handleEditSave}>
            保存
          </Button>
        }
      >
        <Form form={editForm} layout="vertical">
          <Form.Item
            label="知识库名称"
            name="name"
            rules={[
              { required: true, message: '请输入知识库名称' },
              { min: 2, message: '名称至少需要 2 个字符' },
            ]}
          >
            <Input placeholder="请输入知识库名称" />
          </Form.Item>
          <Form.Item
            label="描述"
            name="description"
          >
            <Input.TextArea rows={4} placeholder="请输入知识库描述" />
          </Form.Item>
        </Form>
      </Drawer>

      {/* 权限管理抽屉（企业版功能） */}
      <Drawer
        title={`权限管理 - ${currentKb?.name || ''}`}
        width={600}
        open={permissionDrawerOpen}
        onClose={() => setPermissionDrawerOpen(false)}
      >
        <Card title="当前设置" size="small">
          <Descriptions column={2}>
            <Descriptions.Item label="范围">
              <Tag>{currentKb?.scope || 'private'}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="创建者">
              {currentKb?.created_at || '-'}
            </Descriptions.Item>
          </Descriptions>
        </Card>

        <Card title="权限列表" style={{ marginTop: 16 }} size="small">
          <div style={{ padding: 20, textAlign: 'center', color: '#999' }}>
            权限管理功能开发中...
          </div>
        </Card>
      </Drawer>
    </div>
  );
}
