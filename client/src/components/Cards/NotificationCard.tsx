/**
 * Notification Card - System event reminder and scheduled notification card.
 */

import { Card, Typography, Tag, Space, Button } from 'antd';
import { Bell, Info, AlertTriangle, CheckCircle } from 'lucide-react';
import styles from './NotificationCard.module.less';

const { Text, Title } = Typography;

export interface NotificationCardProps {
  cardId: string;
  cardType: 'notification';
  title: string;
  message?: string;
  priority?: 'low' | 'medium' | 'high';
  createdAt?: number;
  actions?: Array<{ label: string; action: string; params?: Record<string, any>; type?: 'primary' | 'secondary' | 'danger' | 'success' }>;
  onAction?: (action: string, params?: Record<string, any>) => void;
}

function getPriorityIcon(priority?: string) {
  switch (priority) {
    case 'high': return <AlertTriangle size={18} className={`${styles.icon} ${styles.danger}`} />;
    case 'medium': return <Info size={18} className={`${styles.icon} ${styles.warning}`} />;
    case 'low': return <CheckCircle size={18} className={`${styles.icon} ${styles.success}`} />;
    default: return <Bell size={18} className={styles.icon} />;
  }
}

function getPriorityTag(priority?: string) {
  switch (priority) {
    case 'high': return <Tag color="error">高优先级</Tag>;
    case 'medium': return <Tag color="warning">中优先级</Tag>;
    case 'low': return <Tag color="success">低优先级</Tag>;
    default: return <Tag color="default">普通</Tag>;
  }
}

function formatTimestamp(timestamp?: number): string {
  if (!timestamp) return '';
  const date = new Date(timestamp * 1000);
  return date.toLocaleString('zh-CN', { 
    month: 'numeric', 
    day: 'numeric', 
    hour: '2-digit', 
    minute: '2-digit' 
  });
}

export function NotificationCard({
  title,
  message,
  priority = 'medium',
  createdAt,
  actions = [],
  onAction,
}: NotificationCardProps) {
  return (
    <Card className={styles.notificationCard} bordered={false}>
      <div className={styles.header}>
        {getPriorityIcon(priority)}
        <Title level={5} className={styles.title}>{title}</Title>
      </div>

      {priority && (
        <div className={styles.priorityRow}>
          {getPriorityTag(priority)}
          {createdAt && (
            <Text type="secondary" className={styles.timestamp}>
              {formatTimestamp(createdAt)}
            </Text>
          )}
        </div>
      )}

      {message && (
        <div className={styles.messageBox}>
          <Text className={styles.message}>{message}</Text>
        </div>
      )}

      {actions.length > 0 && (
        <div className={styles.actions}>
          <Space size="small">
            {actions.map((action, index) => {
              const isPrimary = action.type === 'primary';
              const isDanger = action.type === 'danger';
              const btnType = isPrimary ? 'primary' : 'default';
              return (
                <Button
                  key={index}
                  type={btnType as any}
                  danger={isDanger}
                  size="small"
                  onClick={() => onAction?.(action.action, action.params)}
                >
                  {action.label}
                </Button>
              );
            })}
          </Space>
        </div>
      )}
    </Card>
  );
}

export default NotificationCard;
