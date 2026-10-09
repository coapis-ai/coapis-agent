import React, { useState, useEffect } from 'react';
import { Spin, message } from 'antd';
import { useParams, useSearchParams } from 'react-router-dom';
import ScenePicker from '../../components/ScenePicker';
import TagManagement from '../Admin/TagManagement';
import SceneManagement from '../Admin/SceneManagement';
import type { SceneConfig, SceneListResponse } from './types';
import styles from './index.module.less';
import { getApiToken } from '../../api/config';
import { useChatWindow } from '../../contexts/ChatWindowContext';

const Workbench: React.FC = () => {
  const { category: categoryParam } = useParams<{ category?: string }>();
  const [searchParams] = useSearchParams();
  const [scenes, setScenes] = useState<SceneConfig[]>([]);
  const [loading, setLoading] = useState(true);

  // Get management mode from URL
  const managementMode = searchParams.get('management'); // 'scenes' | 'tags'

  // 使用全局聊天窗口状态（scene = 当前聊天窗口所在场景，用于高亮）
  const { openChat, scene } = useChatWindow();

  // Load scenes
  useEffect(() => {
    loadScenes();
  }, []);

  const loadScenes = async () => {
    try {
      setLoading(true);
      const token = getApiToken();

      // Load scenes
      const scenesRes = await fetch('/api/scenes', {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      });
      if (!scenesRes.ok) {
        throw new Error('Failed to load scenes');
      }
      const scenesData: SceneListResponse = await scenesRes.json();
      setScenes(scenesData.scenes);
    } catch (error) {
      console.error('Failed to load scenes:', error);
      message.error('加载场景失败');
    } finally {
      setLoading(false);
    }
  };

  const handleEnterScene = (scene: SceneConfig) => {
    // 打开全局聊天窗口，传入场景
    openChat(scene);
  };

  if (loading) {
    return (
      <div className={styles.loadingContainer}>
        <Spin size="large" />
      </div>
    );
  }

  // Render management pages
  if (managementMode === 'scenes') {
    return (
      <div className={styles.workbench}>
        <div className={styles.header}>
          <h1 className={styles.title}>场景管理</h1>
          <p className={styles.subtitle}>创建、编辑、删除场景</p>
        </div>
        <div className={styles.managementContent}>
          <SceneManagement />
        </div>
      </div>
    );
  }

  if (managementMode === 'tags') {
    return <TagManagement />;
  }

  // Render scene list —— 复用共享 ScenePicker（搜索 + 标签筛选 + 卡片栅格）
  return (
    <div className={styles.workbench}>
      <div className={styles.header}>
        <h1 className={styles.title}>工作台</h1>
        <p className={styles.subtitle}>选择场景，开始对话</p>
      </div>

      <ScenePicker
        scenes={scenes}
        onSelect={handleEnterScene}
        categoryFilterId={categoryParam}
        currentSceneId={scene?.id}
      />
    </div>
  );
};

export default Workbench;
