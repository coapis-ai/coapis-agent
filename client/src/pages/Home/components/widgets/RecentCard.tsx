/**
 * 最近使用卡片组件
 */

import React, { useState, useEffect } from 'react';
import { ClockCircleOutlined } from '@ant-design/icons';
import styles from '../../styles.module.less';
import { WidgetProps, Scene } from '../../types';

interface RecentCardProps extends WidgetProps {
  onRefresh?: () => void;
}

const RecentCard: React.FC<RecentCardProps> = () => {
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    loadRecentScenes();
  }, []);

  /**
   * 加载最近使用的场景
   */
  const loadRecentScenes = async () => {
    setLoading(true);
    try {
      // 获取token
      const token = localStorage.getItem('coapis_auth_token');
      
      if (!token) {
        // 未登录，显示空状态
        setScenes([]);
        return;
      }

      const response = await fetch('/api/user/scene-preferences/recent-scenes', {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });

      if (response.ok) {
        const data = await response.json();
        setScenes(data.scenes || []);
      } else {
        console.error('Failed to load recent scenes');
        setScenes([]);
      }
    } catch (error) {
      console.error('加载最近使用失败:', error);
      setScenes([]);
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
   * 格式化时间
   */
  const formatTime = (dateStr: string) => {
    const date = new Date(dateStr);
    const now = new Date();
    const diff = now.getTime() - date.getTime();
    const days = Math.floor(diff / (1000 * 60 * 60 * 24));

    if (days === 0) {
      const hours = Math.floor(diff / (1000 * 60 * 60));
      if (hours === 0) {
        const minutes = Math.floor(diff / (1000 * 60));
        return `${minutes}分钟前`;
      }
      return `${hours}小时前`;
    }
    if (days === 1) return '昨天';
    if (days < 7) return `${days}天前`;
    return date.toLocaleDateString();
  };

  return (
    <div className={styles.widget}>
      <div className={styles.widgetHeader}>
        <div className={styles.widgetTitle}>
          <span className={styles.widgetIcon}>📅</span>
          <span>最近使用</span>
        </div>
      </div>
      <div className={styles.widgetBody}>
        {loading ? (
          <div className={styles.loadingState}>
            <div className={styles.loadingSpinner} />
          </div>
        ) : scenes.length > 0 ? (
          <div className={styles.sceneGrid}>
            {scenes.slice(0, 6).map(scene => (
              <div
                key={scene.id}
                className={styles.sceneCard}
                onClick={() => handleClickScene(scene)}
              >
                <div className={styles.sceneIcon}>{scene.icon || '📄'}</div>
                <div className={styles.sceneName}>{scene.name}</div>
                {scene.last_used_at && (
                  <div className={styles.sceneMeta}>
                    <ClockCircleOutlined />
                    <span>{formatTime(scene.last_used_at)}</span>
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <div className={styles.emptyState}>
            <div className={styles.emptyIcon}>📭</div>
            <div className={styles.emptyText}>
              暂无使用记录
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default RecentCard;
