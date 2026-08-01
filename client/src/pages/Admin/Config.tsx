import { Typography } from 'antd';
import { PageHeader } from '@/components/PageHeader';
import { ConfigTab } from './index';
import styles from './index.module.css';

const { Text } = Typography;

export default function AdminConfig() {
  return (
    <div className={styles.pageContainer}>
      <PageHeader
        parent="设置"
        current="系统配置"
        subRow={
          <Text type="secondary">管理系统配额、环境变量和全局设置</Text>
        }
      />
      <ConfigTab />
    </div>
  );
}
