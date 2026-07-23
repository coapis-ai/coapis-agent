import React, { useState, useEffect } from 'react';
import styles from '../../styles.module.less';

interface Scene {
  id: string;
  name: string;
  description: string;
  icon?: string;
  short_description?: string;
  primary_tag_id?: string;
  tag_ids?: string[];
  usage_count?: number;
}

/**
 * 热门场景卡片
 */
const HotCard: React.FC = () => {
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    loadHotScenes();
  }, []);

  /**
   * 加载热门场景
   */
  const loadHotScenes = async () => {
    setLoading(true);
    try {
      // 调用真实API获取热门场景
      const response = await fetch('/api/scenes/hot?limit=10');
      
      if (!response.ok) {
        throw new Error('Failed to load hot scenes');
      }
      
      const data = await response.json();
      setScenes(data.scenes || []);
    } catch (error) {
      console.error('加载热门场景失败:', error);
    } finally {
      setLoading(false);
    }
  };

  /**
   * 点击场景
   */
  const handleClickScene = (scene: Scene) => {
    // 跳转到场景页面
    window.location.href = `/scene/${scene.id}`;
  };

  /**
   * 格式化使用次数
   */
  const formatUsageCount = (count: number) => {
    if (count >= 1000) {
      return `${(count / 1000).toFixed(1)}k`;
    }
    return count.toString();
  };

  return (
    <div className={styles.widget}>
      <div className={styles.widgetHeader}>
        <div className={styles.widgetTitle}>
          <span className={styles.widgetIcon}>🔥</span>
          <span>热门场景</span>
        </div>
      </div>
      <div className={styles.widgetBody}>
        {loading ? (
          <div className={styles.loadingState}>
            <div className={styles.loadingSpinner} />
          </div>
        ) : scenes.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {scenes.slice(0, 5).map((scene, index) => (
              <div
                key={scene.id}
                className={styles.sceneItem}
                onClick={() => handleClickScene(scene)}
                style={{ cursor: 'pointer' }}
              >
                <div className={styles.sceneRank}>
                  {index < 3 ? (
                    <span style={{ 
                      fontSize: 16, 
                      color: index === 0 ? '#ff6b6b' : index === 1 ? '#ffa94d' : '#ffd43b',
                      fontWeight: 'bold'
                    }}>
                      {index + 1}
                    </span>
                  ) : (
                    <span style={{ color: '#868e96' }}>{index + 1}</span>
                  )}
                </div>
                <div className={styles.sceneIcon}>
                  {scene.icon || '📊'}
                </div>
                <div className={styles.sceneContent}>
                  <div className={styles.sceneName}>{scene.name}</div>
                  <div className={styles.sceneDesc}>
                    {scene.short_description || scene.description}
                  </div>
                </div>
                <div className={styles.sceneMeta}>
                  <span style={{ fontSize: 12, color: '#868e96' }}>
                    {scene.usage_count ? formatUsageCount(scene.usage_count) : 0}次
                  </span>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className={styles.emptyState}>
            <span style={{ fontSize: 32, marginBottom: 8 }}>📭</span>
            <span style={{ color: '#868e96' }}>暂无热门场景</span>
          </div>
        )}
      </div>
    </div>
  );
};

export default HotCard;
