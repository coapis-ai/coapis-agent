import React from 'react';
import { Card, Tag, Space, Tooltip } from 'antd';
import { PlayCircleOutlined } from '@ant-design/icons';
import type { SceneConfig } from './types';
import styles from './SceneCard.module.less';

interface SceneCardProps {
  scene: SceneConfig;
  onEnter: (scene: SceneConfig) => void;
}

const SceneCard: React.FC<SceneCardProps> = ({ scene, onEnter }) => {
  // Use short_description for display, fallback to description
  const displayDescription = scene.short_description || scene.description;
  
  // Use primary_tag_id for category display (if available)
  // Otherwise fall back to category for backward compatibility
  const categoryTag = scene.primary_tag_id ? null : (scene.category ? (
    <Tag color="blue">{scene.category}</Tag>
  ) : null);
  
  // Use tag_ids for tags display (if available)
  // Otherwise fall back to tags for backward compatibility
  const displayTags = scene.tag_ids?.length > 0 ? scene.tag_ids : scene.tags;
  
  // Tags to display (max 3 visible)
  const visibleTags = displayTags.slice(0, 3);
  const hiddenTags = displayTags.slice(3);
  const hasHiddenTags = hiddenTags.length > 0;

  return (
    <Card
      className={styles.sceneCard}
      hoverable
      onClick={() => onEnter(scene)}
      actions={[
        <Space key="enter" className={styles.enterButton}>
          <PlayCircleOutlined />
          <span>进入场景</span>
        </Space>,
      ]}
    >
      <div className={styles.cardHeader}>
        <span className={styles.sceneIcon}>{scene.icon}</span>
        <h3 className={styles.sceneName}>{scene.name}</h3>
      </div>
      
      <p className={styles.sceneDescription}>{displayDescription}</p>
      
      {scene.usage_count > 0 && (
        <div className={styles.usageCount}>
          使用次数: {scene.usage_count}
        </div>
      )}
      
      <Tooltip 
        title={displayTags.join(' · ')}
        placement="top"
      >
        <div className={styles.sceneMeta}>
          {categoryTag}
          {visibleTags.map(tag => (
            <Tag key={tag}>{tag}</Tag>
          ))}
          {hasHiddenTags && (
            <Tag>+{hiddenTags.length}</Tag>
          )}
        </div>
      </Tooltip>
    </Card>
  );
};

export default SceneCard;
