import { Typography } from 'antd';
import { PageHeader } from '@/components/PageHeader';
import TagManagement from './TagManagement';
import styles from './index.module.css';

const { Text } = Typography;

export default function AdminTags() {
  return (
    <div className={styles.pageContainer}>
      <PageHeader
        parent="设置"
        current="标签管理"
        subRow={
          <Text type="secondary">管理场景分类标签和维度</Text>
        }
      />
      <TagManagement />
    </div>
  );
}
