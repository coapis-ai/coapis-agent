import { Typography } from 'antd';
import { PageHeader } from '@/components/PageHeader';
import { AuditTab } from './index';
import styles from './index.module.css';

const { Text } = Typography;

export default function AdminAudit() {
  return (
    <div className={styles.pageContainer}>
      <PageHeader
        parent="设置"
        current="审计日志"
        subRow={
          <Text type="secondary">查看系统操作记录和安全审计</Text>
        }
      />
      <AuditTab />
    </div>
  );
}
