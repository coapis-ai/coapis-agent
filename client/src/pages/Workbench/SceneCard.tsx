import React from 'react';
import { Card, Tag, Tooltip } from 'antd';
import { FireOutlined } from '@ant-design/icons';
import type { SceneConfig } from './types';
import styles from './SceneCard.module.less';

interface SceneCardProps {
  scene: SceneConfig;
  onEnter: (scene: SceneConfig) => void;
  categoryMap?: Record<string, string>; // id -> name
  tagMap?: Record<string, string>; // id -> name
}

const SceneCard: React.FC<SceneCardProps> = ({ scene, onEnter, categoryMap = {}, tagMap = {} }) => {
  // Use short_description for display, fallback to description
  const displayDescription = scene.short_description || scene.description;
  
  // Use primary_tag_id for category display (if available)
  // Convert ID to name using categoryMap
  const categoryTag = scene.primary_tag_id ? (
    <Tag color="blue">{categoryMap[scene.primary_tag_id] || scene.primary_tag_id}</Tag>
  ) : scene.category ? (
    <Tag color="blue">{scene.category}</Tag>
  ) : null;
  
  // Use tag_ids for tags display (if available)
  // Convert IDs to names using tagMap
  // Filter out primary_tag_id to avoid duplication
  const allTags = scene.tag_ids?.length > 0 
    ? scene.tag_ids.map(id => tagMap[id] || id)
    : scene.tags;
  
  // Remove primary tag from allTags to avoid duplication with categoryTag
  const primaryTagName = scene.primary_tag_id ? tagMap[scene.primary_tag_id] || scene.primary_tag_id : null;
  const displayTags = primaryTagName 
    ? allTags.filter(tag => tag !== primaryTagName)
    : allTags;
  
  // Tags to display (max 2 visible for other tags, since category is shown separately)
  const visibleTags = displayTags.slice(0, 2);
  const hiddenTags = displayTags.slice(2);
  const hasHiddenTags = hiddenTags.length > 0;
  
  // Usage count indicator (🔥 for hot scenes)
  const usageIndicator = scene.usage_count > 0 ? (
    <Tooltip title={`使用 ${scene.usage_count} 次`}>
      <span className={styles.usageIndicator}>
        <FireOutlined /> {scene.usage_count}
      </span>
    </Tooltip>
  ) : null;

  return (
    <Card
      className={styles.sceneCard}
      hoverable
      onClick={() => onEnter(scene)}
    >
      <div className={styles.cardHeader}>
        <div className={styles.titleRow}>
          <span className={styles.sceneIcon}>{scene.icon}</span>
          <h3 className={styles.sceneName}>{scene.name}</h3>
          {usageIndicator}
        </div>
      </div>
      
      <p className={styles.sceneDescription}>{displayDescription}</p>
      
      <Tooltip 
        title={displayTags.join(' · ')}
        placement="top"
      >
        <div className={styles.sceneMeta}>
          {categoryTag}
          {visibleTags.map((tag, index) => (
            <Tag key={index}>{tag}</Tag>
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
