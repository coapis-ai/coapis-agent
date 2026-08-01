// Admin tag management page
import React, { useState, useEffect } from 'react';
import {
  Table,
  Button,
  Space,
  Modal,
  Form,
  Input,
  Select,
  Tag,
  message,
  Popconfirm,
  Radio,
  InputNumber,
  Switch,
} from 'antd';
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  FolderOutlined,
  TagOutlined,
  AppstoreOutlined,
  DashboardOutlined,
  DownloadOutlined,
  UploadOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import styles from './SceneManagement.module.less';
import { getApiToken } from '../../api/config';

const { Option } = Select;
const { TextArea } = Input;

// Tag types
type TagType = 'dimension' | 'category' | 'industry' | 'frequency';

// Tag config interface
interface TagConfig {
  id: string;
  name: string;
  icon: string;
  type: TagType;
  parent_id?: string;
  description?: string;
  keywords: string[];
  related_skills: string[];
  sort_order: number;
  show_in_menu: boolean;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

// Tag list response
interface TagListResponse {
  tags: TagConfig[];
  total: number;
}

const TagManagement: React.FC = () => {
  const [tags, setTags] = useState<TagConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalVisible, setModalVisible] = useState(false);
  const [editingTag, setEditingTag] = useState<TagConfig | null>(null);
  const [form] = Form.useForm();
  const [filterType, setFilterType] = useState<TagType | 'all'>('all');
  const [dimensionTags, setDimensionTags] = useState<TagConfig[]>([]);
  const [expandedRowKeys, setExpandedRowKeys] = useState<string[]>([]);

  useEffect(() => {
    loadTags();
  }, []);

  const loadTags = async () => {
    try {
      setLoading(true);
      const token = getApiToken();
      
      // Load flat list for dimension selection
      const listRes = await fetch('/api/admin/tags', {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      });
      if (!listRes.ok) {
        throw new Error('Failed to load tags');
      }
      const listData: TagListResponse = await listRes.json();
      setTags(listData.tags || []);
      
      // Extract dimension tags for parent selection
      const dims = (listData.tags || []).filter(t => t.type === 'dimension');
      setDimensionTags(dims);
      
      // Auto-expand all dimension tags
      setExpandedRowKeys(dims.map(d => d.id));
    } catch (error) {
      console.error('Failed to load tags:', error);
      message.error('加载标签失败');
    } finally {
      setLoading(false);
    }
  };

  // Build tree data for table display
  const buildTreeData = (flatTags: TagConfig[]): TagConfig[] => {
    if (filterType !== 'all') {
      // When filtering, show flat list
      return flatTags.filter(t => t.type === filterType);
    }
    
    // Build tree: dimension tags with children
    const dimensionTags = flatTags.filter(t => t.type === 'dimension');
    const categoryTags = flatTags.filter(t => t.type === 'category');
    const otherTags = flatTags.filter(t => t.type !== 'dimension' && t.type !== 'category');
    
    // Map children to dimensions
    const tree = dimensionTags.map(dim => {
      const children = categoryTags.filter(cat => cat.parent_id === dim.id);
      return {
        ...dim,
        children: children.length > 0 ? children : undefined,
      };
    });
    
    // Add other tags (industry, frequency) at the end
    return [...tree, ...otherTags];
  };

  const handleCreate = () => {
    setEditingTag(null);
    form.resetFields();
    form.setFieldsValue({
      icon: '📁',
      type: 'category',
      sort_order: 100,
      show_in_menu: true,
      enabled: true,
      keywords: [],
      related_skills: [],
    });
    setModalVisible(true);
  };

  const handleEdit = (tag: TagConfig) => {
    setEditingTag(tag);
    form.setFieldsValue({
      name: tag.name,
      icon: tag.icon,
      type: tag.type,
      parent_id: tag.parent_id,
      description: tag.description,
      keywords: tag.keywords?.join(', '),
      related_skills: tag.related_skills?.join(', '),
      sort_order: tag.sort_order,
      show_in_menu: tag.show_in_menu,
      enabled: tag.enabled,
    });
    setModalVisible(true);
  };

  const handleDelete = async (tagId: string) => {
    try {
      const token = getApiToken();
      const response = await fetch(`/api/admin/tags/${tagId}`, {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to delete tag');
      }

      message.success('标签已删除');
      loadTags();
    } catch (error: any) {
      console.error('Failed to delete tag:', error);
      message.error(error.message || '删除标签失败');
    }
  };

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      const token = getApiToken();

      const payload = {
        ...values,
        keywords: values.keywords ? values.keywords.split(',').map((k: string) => k.trim()).filter(Boolean) : [],
        related_skills: values.related_skills ? values.related_skills.split(',').map((k: string) => k.trim()).filter(Boolean) : [],
      };

      const url = editingTag
        ? `/api/admin/tags/${editingTag.id}`
        : '/api/admin/tags';
      const method = editingTag ? 'PUT' : 'POST';

      const response = await fetch(url, {
        method,
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to save tag');
      }

      message.success(editingTag ? '标签已更新' : '标签已创建');
      setModalVisible(false);
      loadTags();
    } catch (error: any) {
      console.error('Failed to save tag:', error);
      message.error(error.message || '保存标签失败');
    }
  };

  const handleExport = () => {
    try {
      // Export all tags to JSON file
      const exportData = {
        version: '1.0',
        exportTime: new Date().toISOString(),
        total: tags.length,
        tags: tags,
      };

      const blob = new Blob([JSON.stringify(exportData, null, 2)], {
        type: 'application/json',
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `tags-${new Date().toISOString().split('T')[0]}.json`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);

      message.success(`已导出 ${tags.length} 个标签`);
    } catch (error) {
      console.error('Export failed:', error);
      message.error('导出失败');
    }
  };

  const handleImport = () => {
    // Create file input
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json';
    
    input.onchange = async (e: any) => {
      const file = e.target.files[0];
      if (!file) return;

      try {
        const text = await file.text();
        const data = JSON.parse(text);

        // Validate import data
        if (!data.tags || !Array.isArray(data.tags)) {
          throw new Error('无效的标签数据格式');
        }

        // Import tags via API
        const token = getApiToken();
        let successCount = 0;
        let failCount = 0;

        for (const tag of data.tags) {
          try {
            const payload = {
              ...tag,
              keywords: tag.keywords || [],
              related_skills: tag.related_skills || [],
            };

            const response = await fetch('/api/admin/tags', {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`,
              },
              body: JSON.stringify(payload),
            });

            if (response.ok) {
              successCount++;
            } else {
              failCount++;
            }
          } catch (err) {
            failCount++;
          }
        }

        if (successCount > 0) {
          message.success(`成功导入 ${successCount} 个标签${failCount > 0 ? `，失败 ${failCount} 个` : ''}`);
          loadTags();
        } else {
          message.error('导入失败，所有标签可能已存在');
        }
      } catch (error: any) {
        console.error('Import failed:', error);
        message.error(error.message || '导入失败');
      }
    };

    input.click();
  };

  const getTagTypeLabel = (type: TagType) => {
    const labels: Record<TagType, string> = {
      dimension: '维度',
      category: '分类',
      industry: '行业',
      frequency: '频率',
    };
    return labels[type] || type;
  };

  const getTagTypeIcon = (type: TagType) => {
    const icons: Record<TagType, React.ReactNode> = {
      dimension: <FolderOutlined />,
      category: <TagOutlined />,
      industry: <AppstoreOutlined />,
      frequency: <DashboardOutlined />,
    };
    return icons[type] || <TagOutlined />;
  };

  const columns: ColumnsType<TagConfig> = [
    {
      title: 'ID',
      dataIndex: 'id',
      key: 'id',
      width: 180,
      ellipsis: true,
      render: (id: string, record) => {
        // Show icon before ID
        return (
          <span>
            <span style={{ fontSize: '16px', marginRight: '8px' }}>{record.icon}</span>
            {id}
          </span>
        );
      },
    },
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 150,
    },
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
      width: 100,
      render: (type: TagType) => (
        <Tag color={type === 'dimension' ? 'blue' : type === 'category' ? 'green' : 'orange'}>
          {getTagTypeIcon(type)} {getTagTypeLabel(type)}
        </Tag>
      ),
    },
    {
      title: '父级',
      dataIndex: 'parent_id',
      key: 'parent_id',
      width: 120,
      render: (parentId: string | undefined) => {
        if (!parentId) return '-';
        const parent = tags.find(t => t.id === parentId);
        return parent ? parent.name : parentId;
      },
    },
    {
      title: '排序',
      dataIndex: 'sort_order',
      key: 'sort_order',
      width: 80,
      sorter: (a, b) => a.sort_order - b.sort_order,
    },
    {
      title: '菜单显示',
      dataIndex: 'show_in_menu',
      key: 'show_in_menu',
      width: 100,
      render: (show: boolean) => (
        <Tag color={show ? 'success' : 'default'}>
          {show ? '是' : '否'}
        </Tag>
      ),
    },
    {
      title: '状态',
      dataIndex: 'enabled',
      key: 'enabled',
      width: 80,
      render: (enabled: boolean) => (
        <Tag color={enabled ? 'success' : 'error'}>
          {enabled ? '启用' : '禁用'}
        </Tag>
      ),
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
    },
    {
      title: '操作',
      key: 'action',
      width: 150,
      fixed: 'right',
      render: (_, record) => (
        <Space size="small">
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => handleEdit(record)}
          >
            编辑
          </Button>
          <Popconfirm
            title="确定要删除此标签吗？"
            onConfirm={() => handleDelete(record.id)}
            okText="确定"
            cancelText="取消"
          >
            <Button
              type="link"
              size="small"
              danger
              icon={<DeleteOutlined />}
            >
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const treeData = buildTreeData(tags);

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h2>标签管理</h2>
        <Space>
          <Radio.Group value={filterType} onChange={e => setFilterType(e.target.value)}>
            <Radio.Button value="all">全部（树形）</Radio.Button>
            <Radio.Button value="dimension">维度</Radio.Button>
            <Radio.Button value="category">分类</Radio.Button>
            <Radio.Button value="industry">行业</Radio.Button>
            <Radio.Button value="frequency">频率</Radio.Button>
          </Radio.Group>
          <Button
            icon={<UploadOutlined />}
            onClick={handleImport}
          >
            导入
          </Button>
          <Button
            icon={<DownloadOutlined />}
            onClick={handleExport}
          >
            导出
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={handleCreate}
          >
            创建标签
          </Button>
        </Space>
      </div>

      <Table
        columns={columns}
        dataSource={treeData}
        rowKey="id"
        loading={loading}
        pagination={false}
        scroll={{ x: 1200 }}
        size="small"
        expandable={{
          expandedRowKeys: expandedRowKeys,
          onExpandedRowsChange: (keys) => setExpandedRowKeys(keys as string[]),
          defaultExpandAllRows: true,
          indentSize: 15,
        }}
      />

      <Modal
        title={editingTag ? '编辑标签' : '创建标签'}
        open={modalVisible}
        onOk={handleSubmit}
        onCancel={() => setModalVisible(false)}
        width={600}
        okText="保存"
        cancelText="取消"
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            icon: '📁',
            type: 'category',
            sort_order: 100,
            show_in_menu: true,
            enabled: true,
          }}
        >
          <Form.Item
            name="name"
            label="标签名称"
            rules={[{ required: true, message: '请输入标签名称' }]}
          >
            <Input placeholder="输入标签名称" />
          </Form.Item>

          <Form.Item
            name="id"
            label="标签ID"
            rules={[
              { required: !editingTag, message: '请输入标签ID' },
              { pattern: /^[a-z0-9-]+$/, message: 'ID只能包含小写字母、数字和连字符' },
            ]}
            extra="创建后不可修改"
          >
            <Input 
              placeholder="例如: office-common" 
              disabled={!!editingTag}
            />
          </Form.Item>

          <Form.Item
            name="icon"
            label="图标"
            rules={[{ required: true, message: '请输入图标' }]}
          >
            <Input placeholder="例如: 📁" style={{ width: 100 }} />
          </Form.Item>

          <Form.Item
            name="type"
            label="类型"
            rules={[{ required: true, message: '请选择类型' }]}
          >
            <Select>
              <Option value="dimension">
                <Space><FolderOutlined /> 维度</Space>
              </Option>
              <Option value="category">
                <Space><TagOutlined /> 分类</Space>
              </Option>
              <Option value="industry">
                <Space><AppstoreOutlined /> 行业</Space>
              </Option>
              <Option value="frequency">
                <Space><DashboardOutlined /> 频率</Space>
              </Option>
            </Select>
          </Form.Item>

          <Form.Item
            noStyle
            shouldUpdate={(prevValues, currentValues) => prevValues.type !== currentValues.type}
          >
            {({ getFieldValue }) => {
              const type = getFieldValue('type');
              return type === 'category' ? (
                <Form.Item
                  name="parent_id"
                  label="父级维度"
                  rules={[{ required: true, message: '请选择父级维度' }]}
                >
                  <Select placeholder="选择父级维度">
                    {dimensionTags.map(dim => (
                      <Option key={dim.id} value={dim.id}>
                        {dim.icon} {dim.name}
                      </Option>
                    ))}
                  </Select>
                </Form.Item>
              ) : null;
            }}
          </Form.Item>

          <Form.Item
            name="description"
            label="描述"
          >
            <TextArea rows={2} placeholder="标签描述" />
          </Form.Item>

          <Form.Item
            name="keywords"
            label="关键词"
            extra="用逗号分隔多个关键词"
          >
            <Input placeholder="例如: 办公, 会议, 文档" />
          </Form.Item>

          <Form.Item
            name="related_skills"
            label="关联技能"
            extra="用逗号分隔多个技能ID"
          >
            <Input placeholder="例如: meeting_minutes, document_draft" />
          </Form.Item>

          <Form.Item
            name="sort_order"
            label="排序"
            extra="数字越大越靠前"
          >
            <InputNumber min={0} max={1000} style={{ width: '100%' }} />
          </Form.Item>

          <Form.Item
            name="show_in_menu"
            label="在菜单中显示"
            valuePropName="checked"
          >
            <Switch checkedChildren="是" unCheckedChildren="否" />
          </Form.Item>

          <Form.Item
            name="enabled"
            label="启用状态"
            valuePropName="checked"
          >
            <Switch checkedChildren="启用" unCheckedChildren="禁用" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default TagManagement;
