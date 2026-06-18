
import { Dropdown, Button, Avatar, Tag, Space } from 'antd';
import {
  UserOutlined,
  LogoutOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { useUser } from '../../contexts/UserContext';
import { useNavigate } from 'react-router-dom';

export default function ProfileButton() {
  const { t } = useTranslation();
  const { user, logout } = useUser();
  const navigate = useNavigate();

  if (!user) {
    return (
      <Button
        type="text"
        icon={<UserOutlined />}
        title={t('header.profile.login')}
        onClick={() => navigate('/login')}
        style={{ fontSize: '16px' }}
      />
    );
  }

  const roleLabels: Record<string, string> = {
    visitor: t('header.profile.roleVisitor'),
    user: t('header.profile.roleUser'),
    admin: t('header.profile.roleAdmin'),
    superadmin: t('header.profile.roleSuperadmin'),
  };

  const roleColors: Record<string, string> = {
    visitor: 'default',
    user: 'blue',
    admin: 'orange',
    superadmin: 'red',
  };

  const items = [
    {
      key: 'profile',
      icon: <UserOutlined />,
      label: t('header.profile.viewProfile'),
      onClick: () => navigate('/user/profile'),
    },
    { type: 'divider' as const },
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: t('header.profile.logout'),
      danger: true,
      onClick: logout,
    },
  ];

  const displayName = user.display_name || user.username;
  const initials = displayName.charAt(0).toUpperCase();

  return (
    <Dropdown menu={{ items }} placement="bottomRight">
      <div
        style={{
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '4px 8px',
          borderRadius: 6,
          transition: 'background 0.2s',
        }}
        onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(0,0,0,0.06)')}
        onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
      >
        <Avatar
          size="small"
          style={{
            backgroundColor: '#722ed1',
            color: '#fff',
            fontSize: '12px',
          }}
        >
          {initials}
        </Avatar>
        <Space direction="vertical" size={0} style={{ lineHeight: 1.2 }}>
          <span
            style={{
              fontSize: 13,
              fontWeight: 500,
              maxWidth: 120,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {displayName}
          </span>
          <Space size={4}>
            <Tag color={roleColors[user.role] || 'default'} style={{ padding: '0 4px', fontSize: 10 }}>
              {roleLabels[user.role] || user.role}
            </Tag>
            <span style={{ fontSize: 10, color: '#999' }}>
              <ThunderboltOutlined /> {user.points}
            </span>
          </Space>
        </Space>
      </div>
    </Dropdown>
  );
}
