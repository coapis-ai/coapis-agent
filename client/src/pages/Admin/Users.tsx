import { Typography } from 'antd';
import { PageHeader } from '@/components/PageHeader';
import { UsersTab } from './index';
import styles from './index.module.css';

const { Text } = Typography;

export default function AdminUsers() {
  return (
    <div className={styles.pageContainer}>
      <PageHeader
        parent="设置"
        current="用户管理"
        subRow={
          <Text type="secondary">管理系统用户、角色和权限分配</Text>
        }
      />
      <UsersTab />
    </div>
  );
}
