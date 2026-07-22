import { Typography } from 'antd';
import { PageHeader } from '@/components/PageHeader';
import { OverviewTab } from './index';
import styles from './index.module.css';

const { Text } = Typography;

export default function AdminOverview() {
  return (
    <div className={styles.pageContainer}>
      <PageHeader
        parent="设置"
        current="系统概览"
        subRow={
          <Text type="secondary">查看系统统计数据和运行状态</Text>
        }
      />
      <OverviewTab />
    </div>
  );
}
