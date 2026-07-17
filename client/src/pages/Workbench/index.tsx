import React, { useState, useEffect } from 'react';
import { Row, Col, Input, Select, Tag, Empty, Spin, message } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import SceneCard from './SceneCard';
import EmbeddedChat from './EmbeddedChat';
import type { SceneConfig, SceneListResponse } from './types';
import styles from './index.module.less';

const { Search } = Input;
const { Option } = Select;

const Workbench: React.FC = () => {
  const navigate = useNavigate();
  const [scenes, setScenes] = useState<SceneConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchText, setSearchText] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string>();
  const [selectedTag, setSelectedTag] = useState<string>();
  
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
      const response = await fetch('/api/scenes');
      if (!response.ok) {
        throw new Error('Failed to load scenes');
      }
      const data: SceneListResponse = await response.json();
      setScenes(data.scenes);
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
  
  const handleExpandChat = (chatId: string) => {
    // Navigate to full chat page
    navigate(`/chat/${chatId}`);
  };

  // Get unique categories and tags
  const categories = Array.from(new Set(scenes.map(s => s.category).filter(Boolean)));
  const allTags = Array.from(new Set(scenes.flatMap(s => s.tags)));

  // Filter scenes
  const filteredScenes = scenes.filter(scene => {
    if (scene.status !== 'active') return false;
    
    if (searchText) {
      const searchLower = searchText.toLowerCase();
      const matchName = scene.name.toLowerCase().includes(searchLower);
      const matchDesc = scene.description.toLowerCase().includes(searchLower);
      if (!matchName && !matchDesc) return false;
    }
    
    if (selectedCategory && scene.category !== selectedCategory) {
      return false;
    }
    
    if (selectedTag && !scene.tags.includes(selectedTag)) {
      return false;
    }
    
    return true;
  });

  if (loading) {
    return (
      <div className={styles.loadingContainer}>
        <Spin size="large" />
      </div>
    );
  }

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
          placeholder="选择分类"
          allowClear
          style={{ width: 150 }}
          onChange={setSelectedCategory}
          value={selectedCategory}
        >
          {categories.map(cat => (
            <Option key={cat} value={cat}>{cat}</Option>
          ))}
        </Select>
        
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
      
      {/* Embedded Chat Drawer */}
      <EmbeddedChat
        visible={drawerVisible}
        scene={selectedScene}
        onClose={handleCloseDrawer}
        onExpand={handleExpandChat}
      />
    </div>
  );
};

export default Workbench;
