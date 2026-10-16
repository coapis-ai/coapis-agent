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
import { useModelPrefs } from '@/lib/modelChoice';
import { userModelPrefsApi } from '../../api/modules/user_model_prefs';

const roleColorMap: Record<string, string> = {
  visitor: 'default',
  user: 'blue',
  advanced: 'purple',
  admin: 'orange',
  superadmin: 'red',
};

interface ProfileButtonProps {
  /** 打开「个人设置」抽屉（由 Header 持有状态并渲染 SettingsDrawer） */
  onOpenSettings?: () => void;
}

const ProfileButton: React.FC<ProfileButtonProps> = ({ onOpenSettings }) => {
  const { user, logout } = useUser();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { chat: chatSlot, setChat } = useModelPrefs();
  const [models, setModels] = useState<
    { id: string; name: string; providerId: string; provider?: string }[]
  >([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsLoaded, setModelsLoaded] = useState(false);

  // 模型选择列表（懒加载一次）：只取聊天模型（model_type=llm）
  // 后端 /models/available 未过滤类型会把 qwen3-embedding 这类嵌入模型混进来
  useEffect(() => {
    if (!user || modelsLoaded) return;
    setModelsLoading(true);
    userModelPrefsApi
      .getAvailableModels("chat")
      .then((res: unknown) => {
        const r = res as {
          global_models?: {
            id: string;
            name: string;
            provider_id?: string;
            provider_name?: string;
            model_type?: string;
          }[];
        };
        const list = Array.isArray(r?.global_models) ? r.global_models : [];
        setModels(
          list
            .filter((m) => (m.model_type ?? "chat") === "chat")
            .map((m) => ({
              id: m.id,
              name: m.name,
              providerId: m.provider_id ?? '',
              provider: m.provider_name,
            })),
        );
      })
      .catch(() => setModels([]))
      .finally(() => {
        setModelsLoading(false);
        setModelsLoaded(true);
      });
  }, [user, modelsLoaded]);

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


  const isCurrent = (m: { providerId: string; id: string }) =>
    chatSlot.model === m.id && (chatSlot.providerId ?? '') === m.providerId;

  const modelChildren = [
    {
      key: 'auto',
      label: t('header.profile.auto'),
      icon: !chatSlot.model ? <CheckOutlined /> : undefined,
      onClick: () =>
        setChat({ providerId: null, model: null, name: null }).catch(() => {}),
    },
    { type: 'divider' as const },
    ...(modelsLoading
      ? [{ key: '__loading__', label: <Spin size="small" />, disabled: true }]
      : models.length === 0
        ? [{ key: '__none__', label: t('resourcePicker.noModels'), disabled: true }]
        : models.map((m) => ({
            key: `${m.providerId}::${m.id}`,
            icon: isCurrent(m) ? <CheckOutlined /> : undefined,
            label: (
              <span>
                {m.name}
                {m.provider && (
                  <span style={{ opacity: 0.55, marginLeft: 6, fontSize: 12 }}>{m.provider}</span>
                )}
              </span>
            ),
            onClick: () =>
              setChat({ providerId: m.providerId, model: m.id, name: m.name }).catch(
                () => {},
              ),
          }))),
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
    // 显示设置（主题/语言/聊天显示）已并入「个人设置」抽屉
    // 顶栏「语言」「设置」按钮迁入个人下拉（低频项收纳）
    {
      key: 'personal-settings',
      icon: <SettingOutlined />,
      label: t('header.profile.settings'),
      onClick: () => onOpenSettings?.(),
    },
    { type: 'divider' as const },
    // 「管理后台」入口移除：管理员入口保留在「个人设置 → 管理 → 用户管理」
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
  ];
  // 注：原 items.filter(item.key === 'admin-panel') 已随「管理后台」入口一并移除
  // （管理入口在「个人设置 → 管理」与侧栏「设置」，下拉不再有 admin-panel 项）

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
