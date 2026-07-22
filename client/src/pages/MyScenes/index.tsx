import { useState, useEffect } from 'react';
import { Card, Tag, Button, Spin, Empty, message, Tabs, Input, Modal, Form } from 'antd';
import { PlusOutlined, CloseOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { api } from '../../api';
import styles from './styles.module.css';

interface Scene {
  id: string;
  name: string;
  description: string;
  icon: string;
  primary_tag_id?: string;
  usage_count?: number;
}

interface UserScenesData {
  enabled_scenes: string[];
  custom_scenes: Scene[];
  preferences: {
    industries?: string[];
    roles?: string[];
  };
}

/**
 * 我的场景页面
 * 用户选择常用场景 + 创建自定义场景
 */
export default function MyScenes() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  
  // 场景数据
  const [allScenes, setAllScenes] = useState<Scene[]>([]);
  const [userScenes, setUserScenes] = useState<UserScenesData>({
    enabled_scenes: [],
    custom_scenes: [],
    preferences: {}
  });
  
  // UI状态
  const [createModalVisible, setCreateModalVisible] = useState(false);
  const [form] = Form.useForm();
  
  // 加载数据
  useEffect(() => {
    loadData();
  }, []);
  
  const loadData = async () => {
    try {
      setLoading(true);
      
      // 并行加载系统场景和用户场景
      const [scenesData, userScenesData] = await Promise.all([
        api.get('/api/scenes'),
        api.get('/api/user-scenes/my-scenes').catch(() => ({
          enabled_scenes: [],
          custom_scenes: [],
          preferences: {}
        }))
      ]);
      
      // 提取所有场景
      const scenes: Scene[] = (scenesData as any)?.scenes || [];
      
      setAllScenes(scenes);
      setUserScenes((userScenesData as UserScenesData) || {
        enabled_scenes: [],
        custom_scenes: [],
        preferences: {}
      });
    } catch (error) {
      console.error('Failed to load data:', error);
      message.error('加载数据失败');
    } finally {
      setLoading(false);
    }
  };
  
  // 切换场景启用状态
  const toggleScene = (sceneId: string) => {
    setUserScenes(prev => {
      const enabled = prev.enabled_scenes.includes(sceneId);
      return {
        ...prev,
        enabled_scenes: enabled
          ? prev.enabled_scenes.filter(id => id !== sceneId)
          : [...prev.enabled_scenes, sceneId]
      };
    });
  };
  
  // 保存用户场景配置
  const handleSave = async () => {
    try {
      setSaving(true);
      
      await api.post('/api/user-scenes/my-scenes', userScenes);
      
      message.success('保存成功');
    } catch (error) {
      console.error('Failed to save:', error);
      message.error('保存失败');
    } finally {
      setSaving(false);
    }
  };
  
  // 进入场景
  const enterScene = (sceneId: string) => {
    navigate(`/chat?scene=${sceneId}`);
  };
  
  // 创建自定义场景
  const handleCreateCustomScene = async (values: any) => {
    try {
      const newScene: Scene = {
        id: `custom-${Date.now()}`,
        name: values.name,
        description: values.description || '',
        icon: values.icon || '📋'
      };
      
      setUserScenes(prev => ({
        ...prev,
        custom_scenes: [...prev.custom_scenes, newScene],
        enabled_scenes: [...prev.enabled_scenes, newScene.id]
      }));
      
      setCreateModalVisible(false);
      form.resetFields();
      message.success('场景创建成功');
    } catch (error) {
      console.error('Failed to create scene:', error);
      message.error('创建失败');
    }
  };
  
  // 删除自定义场景
  const deleteCustomScene = (sceneId: string) => {
    setUserScenes(prev => ({
      ...prev,
      custom_scenes: prev.custom_scenes.filter(s => s.id !== sceneId),
      enabled_scenes: prev.enabled_scenes.filter(id => id !== sceneId)
    }));
  };
  
  // 推荐场景（未启用的热门场景）
  const recommendedScenes = allScenes
    .filter(scene => !userScenes.enabled_scenes.includes(scene.id))
    .sort((a, b) => (b.usage_count || 0) - (a.usage_count || 0))
    .slice(0, 6);
  
  // 已启用的场景
  const enabledSystemScenes = allScenes.filter(scene => 
    userScenes.enabled_scenes.includes(scene.id)
  );
  
  if (loading) {
    return (
      <div className={styles.loadingContainer}>
        <Spin size="large" tip="加载中..." />
      </div>
    );
  }
  
  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h1 className={styles.title}>我的场景</h1>
        <p className={styles.description}>
          选择您常用的场景，快速访问AI能力
        </p>
      </div>
      
      <Tabs
        defaultActiveKey="enabled"
        items={[
          {
            key: 'enabled',
            label: `已启用 (${enabledSystemScenes.length + userScenes.custom_scenes.length})`,
            children: (
              <div className={styles.sceneGrid}>
                {/* 系统场景 */}
                {enabledSystemScenes.map(scene => (
                  <Card
                    key={scene.id}
                    className={styles.sceneCard}
                    hoverable
                    onClick={() => enterScene(scene.id)}
                    actions={[
                      <Button
                        type="text"
                        size="small"
                        icon={<CloseOutlined />}
                        onClick={(e) => {
                          e.stopPropagation();
                          toggleScene(scene.id);
                        }}
                      >
                        移除
                      </Button>
                    ]}
                  >
                    <div className={styles.cardContent}>
                      <div className={styles.sceneIcon}>{scene.icon}</div>
                      <div className={styles.sceneName}>{scene.name}</div>
                      <div className={styles.sceneDesc}>{scene.description}</div>
                    </div>
                  </Card>
                ))}
                
                {/* 自定义场景 */}
                {userScenes.custom_scenes.map(scene => (
                  <Card
                    key={scene.id}
                    className={`${styles.sceneCard} ${styles.customSceneCard}`}
                    hoverable
                    onClick={() => enterScene(scene.id)}
                    actions={[
                      <Button
                        type="text"
                        size="small"
                        danger
                        icon={<CloseOutlined />}
                        onClick={(e) => {
                          e.stopPropagation();
                          deleteCustomScene(scene.id);
                        }}
                      >
                        删除
                      </Button>
                    ]}
                  >
                    <div className={styles.cardContent}>
                      <div className={styles.sceneIcon}>{scene.icon}</div>
                      <div className={styles.sceneName}>{scene.name}</div>
                      <div className={styles.sceneDesc}>{scene.description}</div>
                      <Tag color="blue" className={styles.customTag}>自定义</Tag>
                    </div>
                  </Card>
                ))}
                
                {/* 添加场景卡片 */}
                <Card
                  className={`${styles.sceneCard} ${styles.addCard}`}
                  hoverable
                  onClick={() => setCreateModalVisible(true)}
                >
                  <div className={styles.addContent}>
                    <PlusOutlined className={styles.addIcon} />
                    <div>创建自定义场景</div>
                  </div>
                </Card>
              </div>
            )
          },
          {
            key: 'recommended',
            label: `推荐 (${recommendedScenes.length})`,
            children: (
              <div className={styles.sceneGrid}>
                {recommendedScenes.length === 0 ? (
                  <Empty description="暂无推荐场景" />
                ) : (
                  recommendedScenes.map(scene => (
                    <Card
                      key={scene.id}
                      className={styles.sceneCard}
                      hoverable
                      onClick={() => toggleScene(scene.id)}
                    >
                      <div className={styles.cardContent}>
                        <div className={styles.sceneIcon}>{scene.icon}</div>
                        <div className={styles.sceneName}>{scene.name}</div>
                        <div className={styles.sceneDesc}>{scene.description}</div>
                        {scene.usage_count && (
                          <div className={styles.usageCount}>
                            🔥 {scene.usage_count} 次使用
                          </div>
                        )}
                      </div>
                      <Button
                        type="primary"
                        size="small"
                        icon={<PlusOutlined />}
                        style={{ marginTop: 12 }}
                        onClick={(e) => {
                          e.stopPropagation();
                          toggleScene(scene.id);
                        }}
                      >
                        添加
                      </Button>
                    </Card>
                  ))
                )}
              </div>
            )
          }
        ]}
      />
      
      {/* 创建自定义场景对话框 */}
      <Modal
        title="创建自定义场景"
        open={createModalVisible}
        onCancel={() => setCreateModalVisible(false)}
        onOk={() => form.submit()}
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={handleCreateCustomScene}
        >
          <Form.Item
            name="name"
            label="场景名称"
            rules={[{ required: true, message: '请输入场景名称' }]}
          >
            <Input placeholder="如：我的周报" />
          </Form.Item>
          
          <Form.Item
            name="description"
            label="场景描述"
          >
            <Input.TextArea 
              placeholder="描述这个场景的用途..."
              rows={3}
            />
          </Form.Item>
          
          <Form.Item
            name="icon"
            label="图标"
          >
            <Input placeholder="输入emoji，如：📋" maxLength={2} />
          </Form.Item>
        </Form>
      </Modal>
      
      {/* 保存按钮 */}
      <div className={styles.actions}>
        <Button
          type="primary"
          onClick={handleSave}
          loading={saving}
        >
          保存配置
        </Button>
      </div>
    </div>
  );
}
