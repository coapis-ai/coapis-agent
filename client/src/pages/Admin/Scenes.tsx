import { Typography } from 'antd';
import { PageHeader } from '@/components/PageHeader';
import SceneManagement from './SceneManagement';
import styles from './index.module.css';

const { Text } = Typography;

export default function AdminScenes() {
  return (
    <div className={styles.pageContainer}>
      <PageHeader
        parent="设置"
        current="场景管理"
        subRow={
          <Text type="secondary">创建、编辑和管理系统场景</Text>
        }
      />
      <SceneManagement />
    </div>
  );
}
