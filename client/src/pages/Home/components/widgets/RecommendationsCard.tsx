/**
 * 推荐场景卡片组件
 */

import React, { useState, useEffect } from 'react';
import { message } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import styles from '../../styles.module.less';
import { WidgetProps, Scene } from '../../types';

interface RecommendationsCardProps extends WidgetProps {
  functionTags: string[];
}

const RecommendationsCard: React.FC<RecommendationsCardProps> = ({
  functionTags,
  onRefresh,
}) => {
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [loading, setLoading] = useState(false);

  /**
   * 加载推荐场景
   */
  useEffect(() => {
    loadRecommendations();
  }, [functionTags]);

  /**
   * 加载推荐场景
   */
  const loadRecommendations = async () => {
    setLoading(true);
    try {
      // 调用真实API获取推荐场景
      const response = await fetch(
        `/api/scenes/recommendations?limit=6&tags=${functionTags.join(',')}`
      );
      
      if (!response.ok) {
        throw new Error('Failed to load recommendations');
      }
      
      const data = await response.json();
      setScenes(data.scenes || []);
    } catch (error) {
      console.error('加载推荐场景失败:', error);
      message.error('加载推荐场景失败');
    } finally {
      setLoading(false);
    }
  };

  /**
   * 换一批
   */
  const handleRefresh = () => {
    loadRecommendations();
    if (onRefresh) {
      onRefresh();
    }
  };

  /**
   * 点击场景
   */
  const handleClickScene = (scene: Scene) => {
    // 跳转到场景页面
    window.location.href = `/scene/${scene.id}`;
  };

  return (
    <div className={styles.widget}>
      <div className={styles.widgetHeader}>
        <div className={styles.widgetTitle}>
          <span className={styles.widgetIcon}>🎯</span>
          <span>推荐场景</span>
        </div>
        <div className={styles.widgetActions}>
          <button
            className={styles.actionButton}
            onClick={handleRefresh}
            disabled={loading}
          >
            <ReloadOutlined spin={loading} /> 换一批
          </button>
        </div>
      </div>
      <div className={styles.widgetBody}>
        {loading ? (
          <div className={styles.loadingState}>
            <div className={styles.loadingSpinner} />
          </div>
        ) : scenes.length > 0 ? (
          <div className={styles.sceneGrid}>
            {scenes.map(scene => (
              <div
                key={scene.id}
                className={styles.sceneCard}
                onClick={() => handleClickScene(scene)}
              >
                <div className={styles.sceneIcon}>{scene.icon}</div>
                <div className={styles.sceneName}>{scene.name}</div>
                <div className={styles.sceneDescription}>
                  {scene.description}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className={styles.emptyState}>
            <div className={styles.emptyIcon}>📭</div>
            <div className={styles.emptyText}>
              暂无推荐场景，请设置您的职能标签
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default RecommendationsCard;
