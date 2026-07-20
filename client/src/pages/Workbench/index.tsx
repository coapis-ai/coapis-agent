import React, { useState, useEffect, useMemo } from 'react';
import { Row, Col, Input, Select, Tag, Empty, Spin, message } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import { useSearchParams } from 'react-router-dom';
import SceneCard from './SceneCard';
import FloatingChatWindow from '../../components/FloatingChatWindow';
import type { SceneConfig, SceneListResponse } from './types';
import styles from './index.module.less';
import { getApiToken } from '../../api/config';

const { Search } = Input;
const { Option } = Select;

interface CategoryInfo {
  id: string;
  name: string;
  icon: string;
}

const Workbench: React.FC = () => {
  const [searchParams] = useSearchParams();
  const [scenes, setScenes] = useState<SceneConfig[]>([]);
  const [categoryMap, setCategoryMap] = useState<Record<string, string>>({}); // id -> name
  const [loading, setLoading] = useState(true);
  const [searchText, setSearchText] = useState('');
  const [selectedTag, setSelectedTag] = useState<string>();
  
  // Get category and management mode from URL
  const categoryParam = searchParams.get('category') || 'all';
  const managementMode = searchParams.get('management'); // 'scenes' | 'tags'
  
  // Embedded chat state
  const [drawerVisible, setDrawerVisible] = useState(false);
  const [selectedScene, setSelectedScene] = useState<SceneConfig | null>(null);

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
      
      // Load categories
      const categoriesRes = await fetch('/api/scenes/categories/grouped', {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      });
      if (categoriesRes.ok) {
        const categoriesData = await categoriesRes.json();
        
        // Build category map: id -> name
        const map: Record<string, string> = {};
        if (categoriesData?.dimensions) {
          // Add nature categories
          const natureCats = categoriesData.dimensions.nature?.categories || [];
          natureCats.forEach((cat: CategoryInfo) => {
            map[cat.id] = cat.name;
          });
          
          // Add domain categories
          const domainCats = categoriesData.dimensions.domain?.categories || [];
          domainCats.forEach((cat: CategoryInfo) => {
            map[cat.id] = cat.name;
          });
        }
        setCategoryMap(map);
      }
    } catch (error) {
      console.error('Failed to load scenes:', error);
      message.error('加载场景失败');
    } finally {
      setLoading(false);
    }
  };

  const handleEnterScene = (scene: SceneConfig) => {
    // Open embedded chat drawer
    setSelectedScene(scene);
    setDrawerVisible(true);
  };
  
  const handleCloseDrawer = () => {
    setDrawerVisible(false);
    setSelectedScene(null);
  };

  // Get unique tags
  const allTags = Array.from(new Set(scenes.flatMap(s => s.tags)));

  // Filter scenes
  const filteredScenes = useMemo(() => {
    return scenes.filter(scene => {
      if (scene.status !== 'active') return false;
      
      // Filter by category from URL
      if (categoryParam !== 'all') {
        // categoryParam是分类ID（如office-common），需要转换为分类名称进行匹配
        const categoryName = categoryMap[categoryParam];
        if (categoryName && scene.category !== categoryName) {
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
  }, [scenes, categoryParam, categoryMap, searchText, selectedTag]);

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
          {/* TODO: Implement SceneManagement component */}
          <p style={{ padding: '40px', textAlign: 'center', color: '#999' }}>
            场景管理功能开发中...
          </p>
        </div>
      </div>
    );
  }

  if (managementMode === 'tags') {
    return (
      <div className={styles.workbench}>
        <div className={styles.header}>
          <h1 className={styles.title}>标签管理</h1>
          <p className={styles.subtitle}>创建、编辑、删除标签</p>
        </div>
        <div className={styles.managementContent}>
          {/* TODO: Implement TagManagement component */}
          <p style={{ padding: '40px', textAlign: 'center', color: '#999' }}>
            标签管理功能开发中...
          </p>
        </div>
      </div>
    );
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
      
      {/* Floating Chat Window */}
      <FloatingChatWindow
        visible={drawerVisible}
        scene={selectedScene}
        onClose={handleCloseDrawer}
      />
    </div>
  );
};

export default Workbench;
