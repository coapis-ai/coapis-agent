import React, { useState, useEffect, useMemo } from 'react';
import { Row, Col, Input, Select, Tag, Empty, Spin, message } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import { useParams, useSearchParams } from 'react-router-dom';
import SceneCard from './SceneCard';
import TagManagement from '../Admin/TagManagement';
import SceneManagement from '../Admin/SceneManagement';
import type { SceneConfig, SceneListResponse } from './types';
import styles from './index.module.less';
import { getApiToken } from '../../api/config';
import { useChatWindow } from '../../contexts/ChatWindowContext';

const { Search } = Input;
const { Option } = Select;

const Workbench: React.FC = () => {
  const { category: categoryParam } = useParams<{ category?: string }>();
  const [searchParams] = useSearchParams();
  const [scenes, setScenes] = useState<SceneConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchText, setSearchText] = useState('');
  const [selectedTag, setSelectedTag] = useState<string>();
  
  // Get management mode from URL
  const managementMode = searchParams.get('management'); // 'scenes' | 'tags'
  
  // 使用全局聊天窗口状态
  const { openChat } = useChatWindow();

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

  // Get unique tags
  const allTags = Array.from(new Set(scenes.flatMap(s => s.tags)));

  // Filter scenes
  const filteredScenes = useMemo(() => {
    return scenes.filter(scene => {
      if (scene.status !== 'active') return false;
      
      // Filter by category from URL (使用 primary_tag_id 和 tag_ids 匹配)
      if (categoryParam && categoryParam !== 'all') {
        const matchPrimaryTag = scene.primary_tag_id === categoryParam;
        const matchTagIds = scene.tag_ids && scene.tag_ids.includes(categoryParam);
        if (!matchPrimaryTag && !matchTagIds) {
          return false;
        }
      }
      
      if (searchText) {
        const searchLower = searchText.toLowerCase();
        const matchName = scene.name.toLowerCase().includes(searchLower);
        const matchDesc = scene.description.toLowerCase().includes(searchLower);
        if (!matchName && !matchDesc) return false;
      }
      
      if (selectedTag && !scene.tags.includes(selectedTag)) {
        return false;
      }
      
      return true;
    });
  }, [scenes, categoryParam, searchText, selectedTag]);

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

  // Render scene list
  return (
    <div className={styles.workbench}>
      <div className={styles.header}>
        <h1 className={styles.title}>工作台</h1>
        <p className={styles.subtitle}>选择场景，开始对话</p>
      </div>
      
      <div className={styles.filterBar}>
        <Search
          placeholder="搜索场景"
          allowClear
          onChange={e => setSearchText(e.target.value)}
          style={{ width: 300 }}
          prefix={<SearchOutlined />}
        />
        
        <Select
          placeholder="选择标签"
          allowClear
          style={{ width: 150 }}
          onChange={setSelectedTag}
          value={selectedTag}
        >
          {allTags.map(tag => (
            <Option key={tag} value={tag}>{tag}</Option>
          ))}
        </Select>
      </div>
      
      {filteredScenes.length === 0 ? (
        <Empty description="暂无场景" />
      ) : (
        <Row gutter={[16, 16]} className={styles.sceneGrid}>
          {filteredScenes.map(scene => (
            <Col key={scene.id} xs={24} sm={12} md={8} lg={6}>
              <SceneCard scene={scene} onEnter={handleEnterScene} />
            </Col>
          ))}
        </Row>
      )}
      
      {selectedTag && (
        <div className={styles.selectedTags}>
          <span>当前标签: </span>
          <Tag closable onClose={() => setSelectedTag(undefined)}>
            {selectedTag}
          </Tag>
        </div>
      )}
    </div>
  );
};

export default Workbench;
