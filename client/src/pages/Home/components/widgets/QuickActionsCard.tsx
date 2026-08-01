/**
 * 快捷操作卡片组件
 */

import React from 'react';
import styles from '../../styles.module.less';
import { WidgetProps } from '../../types';
import { QUICK_ACTIONS } from '../../constants';

const QuickActionsCard: React.FC<WidgetProps> = () => {
  /**
   * 点击快捷操作
   */
  const handleClickAction = (action: typeof QUICK_ACTIONS[0]) => {
    if (action.scene_id) {
      // 跳转到场景页面
      window.location.href = `/scene/${action.scene_id}`;
    } else {
      // 跳转到新对话页面
      window.location.href = '/chat';
    }
  };

  return (
    <div className={styles.widget}>
      <div className={styles.widgetHeader}>
        <div className={styles.widgetTitle}>
          <span className={styles.widgetIcon}>⚡</span>
          <span>快捷操作</span>
        </div>
      </div>
      <div className={styles.widgetBody}>
        <div className={styles.quickActionsGrid}>
          {QUICK_ACTIONS.map(action => (
            <div
              key={action.id}
              className={styles.quickActionButton}
              onClick={() => handleClickAction(action)}
            >
              <div className={styles.quickActionIcon}>{action.icon}</div>
              <div className={styles.quickActionName}>{action.name}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export default QuickActionsCard;
