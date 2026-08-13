/**
 * Action Link Card - External system wake-up entrance card.
 */

import { Card, Button, Space, Typography } from 'antd';
import { ExternalLink, ArrowRight } from 'lucide-react';
import styles from './ActionLinkCard.module.less';

const { Text, Title } = Typography;

export interface ActionLinkCardProps {
  cardId: string;
  cardType: 'action_link';
  title: string;
  description?: string;
  linkUrl?: string;
  buttonText?: string;
  actions?: Array<{ label: string; action: string; params?: Record<string, any>; type?: 'primary' | 'secondary' | 'danger' | 'success' }>;
  onAction?: (action: string, params?: Record<string, any>) => void;
}

export function ActionLinkCard({
  title,
  description,
  linkUrl,
  buttonText = '查看详情',
  actions = [],
  onAction,
}: ActionLinkCardProps) {
  const handlePrimaryAction = () => {
    if (linkUrl) {
      window.open(linkUrl, '_blank');
      return;
    }
    if (actions.length > 0 && onAction) {
      const primaryAction = actions.find(a => a.type === 'primary') || actions[0];
      if (primaryAction) {
        onAction(primaryAction.action, primaryAction.params);
      }
    }
  };

  return (
    <Card className={styles.actionLinkCard} bordered={false}>
      <div className={styles.header}>
        <ExternalLink size={18} className={styles.icon} />
        <Title level={5} className={styles.title}>{title}</Title>
      </div>
      
      {description && (
        <Text className={styles.description}>{description}</Text>
      )}

      <div className={styles.actions}>
        {actions.length > 0 ? (
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
        ) : (
          <Button
            type="primary"
            icon={<ArrowRight size={14} />}
            onClick={handlePrimaryAction}
            className={styles.primaryButton}
          >
            {buttonText}
          </Button>
        )}
      </div>
    </Card>
  );
}

export default ActionLinkCard;
