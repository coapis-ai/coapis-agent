import React from 'react';
import { Card, Tag, Space } from 'antd';
import { PlayCircleOutlined } from '@ant-design/icons';
import type { SceneConfig } from './types';
import styles from './SceneCard.module.less';

interface SceneCardProps {
  scene: SceneConfig;
  onEnter: (scene: SceneConfig) => void;
}

const SceneCard: React.FC<SceneCardProps> = ({ scene, onEnter }) => {
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
      
      <div className={styles.sceneMeta}>
        {scene.category && (
          <Tag color="blue">{scene.category}</Tag>
        )}
        {scene.tags.slice(0, 3).map(tag => (
          <Tag key={tag}>{tag}</Tag>
        ))}
      </div>
    </Card>
  );
};

export default SceneCard;
