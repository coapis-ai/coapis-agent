/**
 * 首页主组件
 */

import React, { useState, useEffect } from 'react';
import styles from './styles.module.less';
import { WidgetConfig } from './types';
import { DEFAULT_WIDGET_CONFIGS, STORAGE_KEYS } from './constants';
import WelcomeCard from './components/widgets/WelcomeCard';
import RecommendationsCard from './components/widgets/RecommendationsCard';
import RecentCard from './components/widgets/RecentCard';
import FavoritesCard from './components/widgets/FavoritesCard';
import HotCard from './components/widgets/HotCard';
import QuickActionsCard from './components/widgets/QuickActionsCard';

/**
 * 首页组件
 */
const Home: React.FC = () => {
  const [widgetConfigs, setWidgetConfigs] = useState<WidgetConfig[]>([]);
  const [loading, setLoading] = useState(true);

  /**
   * 加载卡片配置
   */
  useEffect(() => {
    loadWidgetConfigs();
  }, []);

  /**
   * 加载卡片配置
   */
  const loadWidgetConfigs = () => {
    try {
      const storedConfig = localStorage.getItem(STORAGE_KEYS.DASHBOARD_CONFIG);
      
      if (storedConfig) {
        setWidgetConfigs(JSON.parse(storedConfig));
      } else {
        setWidgetConfigs(DEFAULT_WIDGET_CONFIGS);
        localStorage.setItem(STORAGE_KEYS.DASHBOARD_CONFIG, JSON.stringify(DEFAULT_WIDGET_CONFIGS));
      }
      
      setLoading(false);
    } catch (error) {
      console.error('加载配置失败:', error);
      setWidgetConfigs(DEFAULT_WIDGET_CONFIGS);
      setLoading(false);
    }
  };

  /**
   * 渲染卡片
   */
  const renderWidget = (config: WidgetConfig) => {
    if (!config.visible) return null;

    switch (config.type) {
      case 'welcome':
        return <WelcomeCard key={config.id} />;
      case 'recommendations':
        return <RecommendationsCard key={config.id} functionTags={[]} />;
      case 'recent':
        return <RecentCard key={config.id} />;
      case 'favorites':
        return <FavoritesCard key={config.id} />;
      case 'hot':
        return <HotCard key={config.id} />;
      case 'quickActions':
        return <QuickActionsCard key={config.id} />;
      default:
        return null;
    }
  };

  /**
   * 获取卡片尺寸类名
   */
  const getSizeClassName = (size: string) => {
    switch (size) {
      case 'small':
        return styles.widgetSmall;
      case 'medium':
        return styles.widgetMedium;
      case 'large':
        return styles.widgetLarge;
      default:
        return styles.widgetMedium;
    }
  };

  if (loading) {
    return (
      <div className={styles.loadingState}>
        <div className={styles.loadingSpinner} />
      </div>
    );
  }

  return (
    <div className={styles.homeContainer}>
      {/* 头部 */}
      <div className={styles.homeHeader}>
        <h1 className={styles.homeTitle}>欢迎使用 CoApis</h1>
        <p className={styles.homeSubtitle}>您的智能办公助手，助力高效工作</p>
      </div>

      {/* 卡片网格 */}
      <div className={styles.dashboardGrid}>
        {widgetConfigs
          .sort((a, b) => a.order - b.order)
          .map(config => (
            <div
              key={config.id}
              className={`${styles.widget} ${getSizeClassName(config.size)}`}
            >
              {renderWidget(config)}
            </div>
          ))}
      </div>
    </div>
  );
};

export default Home;
