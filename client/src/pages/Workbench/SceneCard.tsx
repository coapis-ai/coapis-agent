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
  // Tags to display (max 3 visible)
  const visibleTags = scene.tags.slice(0, 3);
  const hiddenTags = scene.tags.slice(3);
  const hasHiddenTags = hiddenTags.length > 0;
  
  // All tags for tooltip
  const allTags = scene.category 
    ? [scene.category, ...scene.tags]
    : scene.tags;

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
      
      <p className={styles.sceneDescription}>{scene.description}</p>
      
      <Tooltip 
        title={allTags.join(' · ')}
        placement="top"
      >
        <div className={styles.sceneMeta}>
          {scene.category && (
            <Tag color="blue">{scene.category}</Tag>
          )}
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
