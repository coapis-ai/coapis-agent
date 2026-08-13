/**
 * Data Table Card - Structured data display card.
 */

import { Card, Table, Typography, Space, Button } from 'antd';
import { TableOutlined } from '@ant-design/icons';
import styles from './DataTableCard.module.less';

const { Title, Text } = Typography;

export interface DataTableColumn {
  key: string;
  title: string;
  dataIndex?: string;
}

export interface DataTableRow {
  [key: string]: any;
}

export interface DataTableCardProps {
  cardId: string;
  cardType: 'data_table';
  title: string;
  description?: string;
  columns: DataTableColumn[];
  rows: DataTableRow[];
  actions?: Array<{ label: string; action: string; params?: Record<string, any>; type?: 'primary' | 'secondary' | 'danger' | 'success' }>;
  onAction?: (action: string, params?: Record<string, any>) => void;
}

export function DataTableCard({
  title,
  description,
  columns,
  rows,
  actions = [],
  onAction,
}: DataTableCardProps) {
  // Transform columns for Ant Design Table
  const tableColumns = columns.map(col => ({
    title: col.title,
    dataIndex: col.key,
    key: col.key,
  }));

  return (
    <Card className={styles.dataTableCard} bordered={false}>
      <div className={styles.header}>
        <TableOutlined size={18} className={styles.icon} />
        <Title level={5} className={styles.title}>{title}</Title>
      </div>

      {description && (
        <Text className={styles.description}>{description}</Text>
      )}

      <div className={styles.tableWrapper}>
        <Table
          dataSource={rows}
          columns={tableColumns}
          pagination={{ pageSize: 5, size: 'small' }}
          size="small"
          scroll={{ x: 'max-content' }}
          className={styles.table}
        />
      </div>

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

export default DataTableCard;
