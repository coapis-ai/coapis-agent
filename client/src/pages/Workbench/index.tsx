import React, { useState, useEffect } from 'react';
import { Row, Col, Input, Select, Tag, Empty, Spin, message } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import SceneCard from './SceneCard';
import type { SceneConfig, SceneListResponse } from './types';
import styles from './index.module.less';

const { Search } = Input;
const { Option } = Select;

const Workbench: React.FC = () => {
  const [scenes, setScenes] = useState<SceneConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchText, setSearchText] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string>();
  const [selectedTag, setSelectedTag] = useState<string>();

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

  const handleEnterScene = async (scene: SceneConfig) => {
    try {
      const response = await fetch(`/api/scenes/${scene.id}/enter`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      });
      
      if (!response.ok) {
        throw new Error('Failed to enter scene');
      }
      
      const data = await response.json();
      message.success(`已进入场景: ${scene.name}`);
      
      // Navigate to chat with scene context
      // This would be implemented with router navigation
      console.log('Enter scene response:', data);
      
      // TODO: Navigate to chat page with scene context
      // history.push(`/chat/${data.chat_id}`, { scene: data });
      
    } catch (error) {
      console.error('Failed to enter scene:', error);
      message.error('进入场景失败');
    }
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
    </div>
  );
};

export default Workbench;
