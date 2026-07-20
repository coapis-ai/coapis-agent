// Admin scene management page
import React, { useState, useEffect, useMemo } from 'react';
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
  Tooltip,
} from 'antd';
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import type { SceneConfig } from '../Workbench/types';
import styles from './SceneManagement.module.less';
import { getApiToken } from '../../api/config';
import { PrimaryTagSelector, OtherTagsSelector } from './TagSelectors';

const { Option } = Select;
const { TextArea } = Input;

// Tag interface
interface TagConfig {
  id: string;
  name: string;
  icon: string;
  type: 'dimension' | 'category' | 'industry' | 'frequency';
  parent_id?: string;
  enabled: boolean;
}

const SceneManagement: React.FC = () => {
  const [scenes, setScenes] = useState<SceneConfig[]>([]);
  const [tags, setTags] = useState<TagConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalVisible, setModalVisible] = useState(false);
  const [editingScene, setEditingScene] = useState<SceneConfig | null>(null);
  const [filterTag, setFilterTag] = useState<string>('all');
  const [form] = Form.useForm();

  // Build tag id -> name map
  const tagNameMap = useMemo(() => {
    const map: Record<string, string> = {};
    tags.forEach(tag => {
      map[tag.id] = `${tag.icon} ${tag.name}`;
    });
    return map;
  }, [tags]);

  // Filter scenes by tag
  const filteredScenes = useMemo(() => {
    if (filterTag === 'all') {
      return scenes;
    }
    return scenes.filter(scene => {
      // Check primary_tag_id
      if (scene.primary_tag_id === filterTag) {
        return true;
      }
      // Check tag_ids
      if (scene.tag_ids && scene.tag_ids.includes(filterTag)) {
        return true;
      }
      return false;
    });
  }, [scenes, filterTag]);

  // Get category tags for filter dropdown
  const categoryTags = useMemo(() => {
    return tags.filter(tag => tag.type === 'category' && tag.enabled);
  }, [tags]);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    await Promise.all([loadScenes(), loadTags()]);
  };

  const loadScenes = async () => {
    try {
      setLoading(true);
      const token = getApiToken();
      const response = await fetch('/api/admin/scenes', {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      });
      if (!response.ok) {
        throw new Error('Failed to load scenes');
      }
      const data = await response.json();
      setScenes(data.scenes);
    } catch (error) {
      console.error('Failed to load scenes:', error);
      message.error('加载场景失败');
    } finally {
      setLoading(false);
    }
  };

  const loadTags = async () => {
    try {
      const token = getApiToken();
      const response = await fetch('/api/admin/tags?enabled=true', {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      });
      if (!response.ok) {
        throw new Error('Failed to load tags');
      }
      const data = await response.json();
      setTags(data.tags);
    } catch (error) {
      console.error('Failed to load tags:', error);
    }
  };

  const handleCreate = () => {
    setEditingScene(null);
    form.resetFields();
    setModalVisible(true);
  };

  const handleEdit = (scene: SceneConfig) => {
    setEditingScene(scene);
    form.setFieldsValue({
      name: scene.name,
      icon: scene.icon,
      description: scene.description,
      short_description: scene.short_description,
      primary_tag_id: scene.primary_tag_id,
      tag_ids: scene.tag_ids,
      skills: scene.skills,
      system_prompt: scene.system_prompt,
      welcome_message: scene.welcome_message,
      status: scene.status,
    });
    setModalVisible(true);
  };

  const handleDelete = async (sceneId: string, hardDelete: boolean = false) => {
    try {
      const token = getApiToken();
      const response = await fetch(
        `/api/admin/scenes/${sceneId}?hard_delete=${hardDelete}`,
        {
          method: 'DELETE',
          headers: {
            'Authorization': `Bearer ${token}`,
          },
        }
      );

      if (!response.ok) {
        throw new Error('Failed to delete scene');
      }

      message.success(hardDelete ? '场景已永久删除' : '场景已删除');
      loadScenes();
    } catch (error) {
      console.error('Failed to delete scene:', error);
      message.error('删除场景失败');
    }
  };

  const handleSubmit = async (values: any) => {
    try {
      const token = getApiToken();
      const url = editingScene
        ? `/api/admin/scenes/${editingScene.id}`
        : '/api/admin/scenes';
      const method = editingScene ? 'PATCH' : 'POST';

      // Clean up empty values
      const cleanedValues = { ...values };
      if (!cleanedValues.skills || cleanedValues.skills.length === 0) {
        delete cleanedValues.skills;
      }
      if (!cleanedValues.primary_tag_id) {
        delete cleanedValues.primary_tag_id;
      }
      if (!cleanedValues.tag_ids || cleanedValues.tag_ids.length === 0) {
        delete cleanedValues.tag_ids;
      }

      const response = await fetch(url, {
        method,
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify(cleanedValues),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        const errorMsg = errorData.detail || errorData.message || '保存失败';
        throw new Error(errorMsg);
      }

      message.success(editingScene ? '场景已更新' : '场景已创建');
      setModalVisible(false);
      loadScenes();
    } catch (error: any) {
      console.error('Failed to save scene:', error);
      message.error(error.message || '保存场景失败');
    }
  };

  const columns: ColumnsType<SceneConfig> = [
    {
      title: '场景ID',
      dataIndex: 'id',
      key: 'id',
      width: 150,
      render: (id: string) => <code style={{ fontSize: 12 }}>{id}</code>,
    },
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 120,
      render: (name: string) => <span style={{ fontWeight: 500 }}>{name}</span>,
    },
    {
      title: '图标',
      dataIndex: 'icon',
      key: 'icon',
      width: 60,
      align: 'center',
      render: (icon: string) => <span style={{ fontSize: 20 }}>{icon}</span>,
    },
    {
      title: '标签',
      dataIndex: 'primary_tag_id',
      key: 'tags',
      width: 150,
      render: (primary_tag_id: string, record) => {
        const tags: string[] = [];
        // Add primary tag
        if (primary_tag_id && tagNameMap[primary_tag_id]) {
          tags.push(tagNameMap[primary_tag_id]);
        } else if (record.category) {
          tags.push(record.category);
        }
        // Add other tags
        if (record.tag_ids && record.tag_ids.length > 0) {
          record.tag_ids.forEach(tagId => {
            if (tagNameMap[tagId] && !tags.includes(tagNameMap[tagId])) {
              tags.push(tagNameMap[tagId]);
            }
          });
        }
        
        if (tags.length === 0) return '-';
        
        return (
          <Space size={[2, 2]} wrap>
            {tags.slice(0, 2).map((tag, idx) => (
              <Tag key={idx} style={{ margin: 0, fontSize: 11 }}>{tag}</Tag>
            ))}
            {tags.length > 2 && <span style={{ fontSize: 11, color: '#999' }}>+{tags.length - 2}</span>}
          </Space>
        );
      },
    },
    {
      title: '场景描述',
      dataIndex: 'short_description',
      key: 'description',
      width: 200,
      ellipsis: true,
      render: (desc: string, record) => {
        const text = desc || record.description || '-';
        return <span style={{ color: '#666', fontSize: 12 }}>{text}</span>;
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 80,
      align: 'center',
      render: (status: string) => {
        const colorMap: Record<string, string> = {
          active: 'green',
          disabled: 'orange',
          deleted: 'red',
        };
        const textMap: Record<string, string> = {
          active: '启用',
          disabled: '禁用',
          deleted: '已删除',
        };
        return <Tag color={colorMap[status]} style={{ margin: 0 }}>{textMap[status] || status}</Tag>;
      },
    },
    {
      title: '使用次数',
      dataIndex: 'usage_count',
      key: 'usage_count',
      width: 80,
      align: 'center',
      sorter: (a, b) => (a.usage_count || 0) - (b.usage_count || 0),
      render: (count: number) => <span style={{ fontWeight: 500 }}>{count || 0}</span>,
    },
    {
      title: '操作',
      key: 'actions',
      width: 100,
      fixed: 'right',
      align: 'center',
      render: (_, record) => (
        <Space size="small">
          <Tooltip title="编辑">
            <Button
              type="text"
              size="small"
              icon={<EditOutlined />}
              onClick={() => handleEdit(record)}
            />
          </Tooltip>
          <Popconfirm
            title="确定要删除此场景吗？"
            onConfirm={() => handleDelete(record.id)}
            okText="确定"
            cancelText="取消"
          >
            <Tooltip title="删除">
              <Button type="text" size="small" danger icon={<DeleteOutlined />} />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div className={styles.sceneManagement}>
      {/* Header with filter and create button */}
      <div style={{ 
        display: 'flex', 
        justifyContent: 'space-between', 
        alignItems: 'center', 
        marginBottom: 16 
      }}>
        <Space>
          <span style={{ fontWeight: 500 }}>按标签筛选：</span>
          <Select
            value={filterTag}
            onChange={setFilterTag}
            style={{ width: 200 }}
            options={[
              { label: '全部标签', value: 'all' },
              ...categoryTags.map(tag => ({
                label: `${tag.icon} ${tag.name}`,
                value: tag.id,
              })),
            ]}
          />
          {filterTag !== 'all' && (
            <Button onClick={() => setFilterTag('all')}>重置</Button>
          )}
          <span style={{ color: '#999', fontSize: 12, marginLeft: 16 }}>
            共 {filteredScenes.length} 个场景
          </span>
        </Space>
        
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={handleCreate}
        >
          新建场景
        </Button>
      </div>

      <Table
        columns={columns}
        dataSource={filteredScenes}
        rowKey="id"
        loading={loading}
        size="small"
        pagination={{
          pageSize: 20,
          showSizeChanger: true,
          showTotal: (total) => `共 ${total} 个场景`,
        }}
        scroll={{ x: 1000 }}
      />

      <Modal
        title={editingScene ? '编辑场景' : '新建场景'}
        open={modalVisible}
        onCancel={() => setModalVisible(false)}
        onOk={() => form.submit()}
        width={600}
        destroyOnClose
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={handleSubmit}
        >
          {!editingScene && (
            <Form.Item
              name="id"
              label="场景ID"
              rules={[
                { required: true, message: '请输入场景ID' },
                { pattern: /^[a-z0-9-]+$/, message: '只能包含小写字母、数字和连字符' },
              ]}
            >
              <Input placeholder="meeting-minutes" />
            </Form.Item>
          )}

          <Form.Item
            name="name"
            label="场景名称"
            rules={[{ required: true, message: '请输入场景名称' }]}
          >
            <Input placeholder="会议纪要助手" />
          </Form.Item>

          <Form.Item
            name="icon"
            label="场景图标"
          >
            <Input placeholder="📝" style={{ width: 100 }} />
          </Form.Item>

          <Form.Item
            name="description"
            label="场景描述"
          >
            <TextArea rows={2} placeholder="专业会议纪要生成助手..." />
          </Form.Item>

          <Form.Item
            name="short_description"
            label="简短描述"
            extra="用于场景卡片显示，建议50字以内"
          >
            <Input placeholder="支持音频转写" />
          </Form.Item>

          <Form.Item
            name="primary_tag_id"
            label="主标签"
            extra="决定场景归属哪个菜单分区"
          >
            <PrimaryTagSelector placeholder="选择主标签" />
          </Form.Item>

          <Form.Item
            name="tag_ids"
            label="其他标签"
            extra="场景属性标签（行业、频率等）"
          >
            <OtherTagsSelector placeholder="选择其他标签" />
          </Form.Item>

          <Form.Item
            name="skills"
            label="关联技能"
          >
            <Select mode="tags" placeholder="输入技能ID后回车" />
          </Form.Item>

          <Form.Item
            name="system_prompt"
            label="系统提示词"
          >
            <TextArea rows={4} placeholder="你是一个专业的会议纪要助手..." />
          </Form.Item>

          <Form.Item
            name="welcome_message"
            label="欢迎消息"
          >
            <TextArea rows={2} placeholder="您好！我是会议纪要助手..." />
          </Form.Item>

          {editingScene && (
            <Form.Item
              name="status"
              label="状态"
            >
              <Select>
                <Option value="active">启用</Option>
                <Option value="disabled">禁用</Option>
              </Select>
            </Form.Item>
          )}
        </Form>
      </Modal>
    </div>
  );
};

export default SceneManagement;
