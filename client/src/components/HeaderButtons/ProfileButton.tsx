import React, { useEffect, useState } from 'react';
import { Dropdown, Button, Avatar, Tag, Spin } from 'antd';
import {
  UserOutlined,
  LogoutOutlined,
  UnorderedListOutlined,
  RobotOutlined,
  SettingOutlined,
  CheckOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { useUser } from '../../contexts/UserContext';
import { useNavigate } from 'react-router-dom';
import { useTheme } from '../../contexts/ThemeContext';
import { useModelChoice } from '@/lib/modelChoice';
import { languageApi } from '../../api/modules/language';
import api from '@/api';

const roleColorMap: Record<string, string> = {
  visitor: 'default',
  user: 'blue',
  advanced: 'purple',
  admin: 'orange',
  superadmin: 'red',
};

const ProfileButton: React.FC = () => {
  const { user, logout } = useUser();
  const navigate = useNavigate();
  const { t, i18n } = useTranslation();
  const { themeMode, setThemeMode } = useTheme();
  const { setChoice } = useModelChoice();
  const [models, setModels] = useState<{ id: string; name: string; provider?: string }[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsLoaded, setModelsLoaded] = useState(false);

  // 模型选择列表（懒加载一次，与 + 菜单的 ModelPickerModal 同源）
  useEffect(() => {
    if (!user || modelsLoaded) return;
    setModelsLoading(true);
    api
      .get('/models/available')
      .then((res: unknown) => {
        // /api/models/available → { global_models: [{id,name,provider_id,provider_name}] }
        const r = res as { global_models?: { id: string; name: string; provider_name?: string }[] };
        const list = Array.isArray(r?.global_models) ? r.global_models : [];
        setModels(list.map((m) => ({ id: m.id, name: m.name, provider: m.provider_name })));
      })
      .catch(() => setModels([]))
      .finally(() => {
        setModelsLoading(false);
        setModelsLoaded(true);
      });
  }, [user, modelsLoaded]);

  const changeLang = (lang: string) => {
    i18n.changeLanguage(lang);
    localStorage.setItem('language', lang);
    languageApi.updateLanguage(lang).catch(() => {});
  };

  if (!user) {
    return (
      <Button
        type="link"
        icon={<UserOutlined />}
        onClick={() => navigate('/login')}
      >
        {t('header.profile.login')}
      </Button>
    );
  }

  const curLang = i18n.resolvedLanguage || i18n.language || '';

  const modelChildren = [
    { key: 'auto', label: t('header.profile.auto'), disabled: true },
    ...(modelsLoading
      ? [{ key: '__loading__', label: <Spin size="small" />, disabled: true }]
      : models.length === 0
        ? [{ key: '__none__', label: t('resourcePicker.noModels'), disabled: true }]
        : models.map((m) => ({
            key: m.id,
            label: (
              <span>
                {m.name}
                {m.provider && (
                  <span style={{ opacity: 0.55, marginLeft: 6, fontSize: 12 }}>{m.provider}</span>
                )}
              </span>
            ),
            onClick: () => setChoice({ id: m.id, name: m.name }),
          }))),
  ];

  const displayChildren = [
    {
      key: 'theme-light',
      label: t('header.profile.themeLight'),
      icon: themeMode === 'light' ? <CheckOutlined /> : undefined,
      onClick: () => setThemeMode('light'),
    },
    {
      key: 'theme-dark',
      label: t('header.profile.themeDark'),
      icon: themeMode === 'dark' ? <CheckOutlined /> : undefined,
      onClick: () => setThemeMode('dark'),
    },
    {
      key: 'theme-system',
      label: t('header.profile.themeSystem'),
      icon: themeMode === 'system' ? <CheckOutlined /> : undefined,
      onClick: () => setThemeMode('system'),
    },
    { type: 'divider' as const },
    {
      key: 'lang-zh',
      label: '简体中文',
      icon: curLang.toLowerCase().startsWith('zh') ? <CheckOutlined /> : undefined,
      onClick: () => changeLang('zh'),
    },
    {
      key: 'lang-en',
      label: 'English',
      icon: curLang.toLowerCase().startsWith('en') ? <CheckOutlined /> : undefined,
      onClick: () => changeLang('en'),
    },
  ];

  const items = [
    {
      key: 'profile',
      icon: <UserOutlined />,
      label: `${user.username} (${t(`header.profile.role${user.role.charAt(0).toUpperCase()}${user.role.slice(1)}`)})`,
    },
    {
      key: 'sessions-center',
      icon: <UnorderedListOutlined />,
      label: t('header.sessionsCenter.title'),
      onClick: () => navigate('/sessions'),
    },
    // 设计 §2.4：模型选择迁入头像下拉（顶部灰色占位「自动」）
    {
      key: 'model-selection',
      icon: <RobotOutlined />,
      label: t('header.profile.modelSelection'),
      type: 'submenu' as const,
      children: modelChildren,
    },
    // 设计 §2.4：显示设置（主题 + 语言）
    {
      key: 'display-settings',
      icon: <SettingOutlined />,
      label: t('header.profile.displaySettings'),
      type: 'submenu' as const,
      children: displayChildren,
    },
    { type: 'divider' as const },
    {
      key: 'admin-panel',
      icon: <SettingOutlined />,
      label: t('header.profile.adminPanel'),
      onClick: () => navigate('/settings/users'),
    },
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: t('header.profile.logout'),
      danger: true,
      onClick: async () => {
        await logout();
        navigate('/');
      },
    },
  ].filter((item) => {
    // 管理员面板仅对管理员显示
    if (item.key === 'admin-panel') {
      return ['admin', 'superadmin'].includes(user!.role);
    }
    return true;
  });

  return (
    <Dropdown menu={{ items }} placement="bottomRight">
      <Button type="text" className="profile-button">
        <Avatar size="small" icon={<UserOutlined />} />
        <Tag color={roleColorMap[user.role]}>{user.username}</Tag>
      </Button>
    </Dropdown>
  );
};

export default ProfileButton;
