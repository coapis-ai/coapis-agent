// Admin scene management page
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
  Tooltip,
} from 'antd';
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  EyeOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import type { SceneConfig, SceneConfigCreate, SceneConfigUpdate } from '../Workbench/types';
import styles from './SceneManagement.module.less';

const { Option } = Select;
const { TextArea } = Input;

const SceneManagement: React.FC = () => {
  const [scenes, setScenes] = useState<SceneConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalVisible, setModalVisible] = useState(false);
  const [editingScene, setEditingScene] = useState<SceneConfig | null>(null);
  const [form] = Form.useForm();

  useEffect(() => {
    loadScenes();
  }, []);

  const loadScenes = async () => {
    try {
      setLoading(true);
      const response = await fetch('/api/admin/scenes');
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
      category: scene.category,
      tags: scene.tags,
      skills: scene.skills,
      system_prompt: scene.system_prompt,
      welcome_message: scene.welcome_message,
    });
    setModalVisible(true);
  };

  const handleDelete = async (sceneId: string, hardDelete: boolean = false) => {
    try {
      const response = await fetch(
        `/api/admin/scenes/${sceneId}?hard_delete=${hardDelete}`,
        {
          method: 'DELETE',
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
      const url = editingScene
        ? `/api/admin/scenes/${editingScene.id}`
        : '/api/admin/scenes';
      const method = editingScene ? 'PATCH' : 'POST';

      const response = await fetch(url, {
        method,
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(values),
      });

      if (!response.ok) {
        throw new Error('Failed to save scene');
      }

      message.success(editingScene ? '场景已更新' : '场景已创建');
      setModalVisible(false);
      loadScenes();
    } catch (error) {
      console.error('Failed to save scene:', error);
      message.error('保存场景失败');
    }
  };

  const columns: ColumnsType<SceneConfig> = [
    {
      title: '图标',
      dataIndex: 'icon',
      key: 'icon',
      width: 60,
      render: (icon: string) => <span style={{ fontSize: 24 }}>{icon}</span>,
    },
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 150,
    },
    {
      title: '场景ID',
      dataIndex: 'id',
      key: 'id',
      width: 150,
      render: (id: string) => <code>{id}</code>,
    },
    {
      title: '分类',
      dataIndex: 'category',
      key: 'category',
      width: 100,
      render: (category: string) => category ? <Tag color="blue">{category}</Tag> : '-',
    },
    {
      title: '标签',
      dataIndex: 'tags',
      key: 'tags',
      width: 200,
      render: (tags: string[]) => (
        <Space size={[0, 4]} wrap>
          {tags.slice(0, 3).map(tag => (
            <Tag key={tag}>{tag}</Tag>
          ))}
          {tags.length > 3 && <span>+{tags.length - 3}</span>}
        </Space>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
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
        return <Tag color={colorMap[status]}>{textMap[status] || status}</Tag>;
      },
    },
    {
      title: '操作',
      key: 'actions',
      width: 200,
      fixed: 'right',
      render: (_, record) => (
        <Space>
          <Tooltip title="编辑">
            <Button
              type="text"
              icon={<EditOutlined />}
              onClick={() => handleEdit(record)}
            />
          </Tooltip>
          <Popconfirm
            title="确定要删除此场景吗？"
            description="软删除后可以恢复"
            onConfirm={() => handleDelete(record.id)}
            okText="确定"
            cancelText="取消"
          >
            <Tooltip title="删除">
              <Button type="text" danger icon={<DeleteOutlined />} />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div className={styles.sceneManagement}>
      <div className={styles.header}>
        <h1>场景管理</h1>
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
        dataSource={scenes}
        rowKey="id"
        loading={loading}
        pagination={{
          pageSize: 10,
          showSizeChanger: true,
          showTotal: (total) => `共 ${total} 个场景`,
        }}
        scroll={{ x: 1200 }}
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
            name="category"
            label="场景分类"
          >
            <Input placeholder="办公" />
          </Form.Item>

          <Form.Item
            name="tags"
            label="场景标签"
          >
            <Select mode="tags" placeholder="输入标签后回车" />
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
