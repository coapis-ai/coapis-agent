/**
 * 我的收藏卡片组件
 */

import React, { useState, useEffect } from 'react';
import { StarFilled } from '@ant-design/icons';
import { message } from 'antd';
import styles from '../../styles.module.less';
import { WidgetProps, Scene } from '../../types';

interface FavoritesCardProps extends WidgetProps {}

const FavoritesCard: React.FC<FavoritesCardProps> = ({ onRefresh }) => {
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    loadFavoriteScenes();
  }, []);

  /**
   * 加载收藏的场景
   */
  const loadFavoriteScenes = async () => {
    setLoading(true);
    try {
      // 获取token
      const token = localStorage.getItem('coapis_auth_token');
      
      if (!token) {
        // 未登录，显示空状态
        setScenes([]);
        return;
      }

      const response = await fetch('/api/user/scene-preferences/favorite-scenes', {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });

      if (response.ok) {
        const data = await response.json();
        setScenes(data.scenes || []);
      } else {
        console.error('Failed to load favorite scenes');
        setScenes([]);
      }
    } catch (error) {
      console.error('加载收藏失败:', error);
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
   * 取消收藏
   */
  const handleRemoveFavorite = async (sceneId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    
    try {
      const token = localStorage.getItem('coapis_auth_token');
      if (!token) {
        message.warning('请先登录');
        return;
      }

      const response = await fetch(`/api/user/scene-preferences/favorite-scenes/${sceneId}`, {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });

      if (response.ok) {
        message.success('已取消收藏');
        loadFavoriteScenes(); // 重新加载
        if (onRefresh) onRefresh();
      } else {
        message.error('取消收藏失败');
      }
    } catch (error) {
      console.error('取消收藏失败:', error);
      message.error('取消收藏失败');
    }
  };

  return (
    <div className={styles.widget}>
      <div className={styles.widgetHeader}>
        <div className={styles.widgetTitle}>
          <span className={styles.widgetIcon}>⭐</span>
          <span>我的收藏</span>
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
                style={{ position: 'relative' }}
              >
                <div 
                  className={styles.favoriteIcon}
                  onClick={(e) => handleRemoveFavorite(scene.id, e)}
                  style={{
                    position: 'absolute',
                    top: 4,
                    right: 4,
                    cursor: 'pointer'
                  }}
                >
                  <StarFilled style={{ color: '#faad14' }} />
                </div>
                <div className={styles.sceneIcon}>{scene.icon || '📄'}</div>
                <div className={styles.sceneName}>{scene.name}</div>
              </div>
            ))}
          </div>
        ) : (
          <div className={styles.emptyState}>
            <div className={styles.emptyIcon}>⭐</div>
            <div className={styles.emptyText}>
              暂无收藏
            </div>
            <div className={styles.emptyHint}>
              点击场景右上角星星收藏
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default FavoritesCard;
