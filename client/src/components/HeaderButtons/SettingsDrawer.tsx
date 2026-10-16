import { useTranslation } from 'react-i18next';
import {
  Drawer,
  Divider,
  Radio,
  Switch,
  Button,
  Typography,
  Avatar,
  Space,
} from 'antd';
import {
  SunOutlined,
  MoonOutlined,
  MonitorOutlined,
  TeamOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useTheme } from '../../contexts/ThemeContext';
import { useUser } from '../../contexts/UserContext';
import { languageApi } from '../../api/modules/language';
import { useChatDisplayFromUser } from '../../hooks/useChatDisplayFromUser';

const { Text } = Typography;

/** 语言用原生名，不做翻译（通用做法） */
const LANG_OPTIONS: { value: string; label: string }[] = [
  { value: 'zh', label: '简体中文' },
  { value: 'en', label: 'English' },
  { value: 'ja', label: '日本語' },
  { value: 'ru', label: 'Русский' },
];

const THEME_OPTIONS: {
  value: 'light' | 'dark' | 'system';
  icon: React.ReactNode;
  labelKey: string;
  fallback: string;
}[] = [
  {
    value: 'light',
    icon: <SunOutlined />,
    labelKey: 'header.profile.themeLight',
    fallback: '浅色',
  },
  {
    value: 'dark',
    icon: <MoonOutlined />,
    labelKey: 'header.profile.themeDark',
    fallback: '深色',
  },
  {
    value: 'system',
    icon: <MonitorOutlined />,
    labelKey: 'header.profile.themeSystem',
    fallback: '跟随系统',
  },
];

/** 抽屉内分组标题 */
function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <Text
      type="secondary"
      style={{
        display: 'block',
        fontSize: 12,
        fontWeight: 600,
        letterSpacing: 0.4,
        marginBottom: 8,
      }}
    >
      {children}
    </Text>
  );
}

interface SettingsDrawerProps {
  open: boolean;
  onClose: () => void;
}

/**
 * 个人设置抽屉。
 *
 * 所有控件即时生效（与原顶栏菜单语义一致）：主题/语言为本地偏好，
 * 聊天显示走 UserContext（localStorage 主 + 后端备份）。
 */
export default function SettingsDrawer({ open, onClose }: SettingsDrawerProps) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const { user, isAdmin } = useUser();
  const { themeMode, setThemeMode } = useTheme();
  // 聊天显示走统一桥接钩子：读后端嵌套偏好，写 localStorage + 后端
  const { displayConfig, updateDisplayConfig } = useChatDisplayFromUser();

  const changeLang = (lang: string) => {
    i18n.changeLanguage(lang);
    localStorage.setItem('language', lang);
    languageApi.updateLanguage(lang).catch(() => {});
  };

  const toggleHideDetails = (checked: boolean) => {
    updateDisplayConfig('hideDetails', checked);
  };

  const displayName = user?.display_name || user?.username || 'User';
  const curLang = (i18n.resolvedLanguage || i18n.language || 'zh')
    .toLowerCase()
    .slice(0, 2);
  const currentLang = LANG_OPTIONS.some((o) => o.value === curLang)
    ? curLang
    : 'zh';

  return (
    <Drawer
      title={t('header.profile.settings')}
      placement="right"
      width={400}
      open={open}
      onClose={onClose}
      footer={
        <Button block onClick={onClose}>
          {t('common.close')}
        </Button>
      }
    >
      {user && (
        <div style={{ marginBottom: 20 }}>
          <Space size={12}>
            <Avatar
              size={40}
              src={user.avatar_url || undefined}
              icon={!user.avatar_url && <UserOutlined />}
            />
            <div>
              <div style={{ fontWeight: 600 }}>{displayName}</div>
              {user.display_name && user.username && (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {user.username}
                </Text>
              )}
            </div>
          </Space>
        </div>
      )}

      {/* ── 外观 ─────────────────────────────── */}
      <SectionTitle>
        {t('header.profile.sectionAppearance', { defaultValue: '外观' })}
      </SectionTitle>
      <Radio.Group
        value={themeMode}
        onChange={(e) => setThemeMode(e.target.value)}
        style={{ display: 'flex', width: '100%', marginBottom: 4 }}
      >
        {THEME_OPTIONS.map((opt) => (
          <Radio.Button
            key={opt.value}
            value={opt.value}
            style={{ flex: 1, textAlign: 'center', padding: '6px 0' }}
          >
            <Space size={6}>
              {opt.icon}
              <span>{t(opt.labelKey, { defaultValue: opt.fallback })}</span>
            </Space>
          </Radio.Button>
        ))}
      </Radio.Group>

      <Divider style={{ margin: '16px 0' }} />

      {/* ── 语言 ─────────────────────────────── */}
      <SectionTitle>
        {t('header.profile.sectionLanguage', { defaultValue: '语言' })}
      </SectionTitle>
      <Radio.Group
        value={currentLang}
        onChange={(e) => changeLang(e.target.value)}
        style={{ display: 'flex', width: '100%', marginBottom: 4 }}
      >
        {LANG_OPTIONS.map((opt) => (
          <Radio.Button
            key={opt.value}
            value={opt.value}
            style={{ flex: 1, textAlign: 'center', padding: '6px 0' }}
          >
            {opt.label}
          </Radio.Button>
        ))}
      </Radio.Group>

      <Divider style={{ margin: '16px 0' }} />

      {/* ── 聊天显示 ─────────────────────────── */}
      <SectionTitle>
        {t('header.profile.sectionChatDisplay', { defaultValue: '聊天显示' })}
      </SectionTitle>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <span>
          {t('header.profile.chatHideDetails', { defaultValue: '隐藏细节' })}
        </span>
        <Switch
          checked={displayConfig.hideDetails}
          onChange={toggleHideDetails}
        />
      </div>
      <Text
        type="secondary"
        style={{ fontSize: 12, display: 'block', marginTop: 6 }}
      >
        {t('header.profile.chatHideDetailsDesc', {
          defaultValue: '隐藏工具调用详情、文件列表和计划执行过程',
        })}
      </Text>

      {/* ── 管理（仅管理员）───────────────────── */}
      {isAdmin && (
        <>
          <Divider style={{ margin: '16px 0' }} />
          <SectionTitle>
            {t('header.profile.sectionAdmin', { defaultValue: '管理' })}
          </SectionTitle>
          <div
            role="button"
            tabIndex={0}
            onClick={() => {
              navigate('/admin/users');
              onClose();
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                navigate('/admin/users');
                onClose();
              }
            }}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '8px 12px',
              borderRadius: 6,
              border: '1px solid rgba(0,0,0,0.08)',
              cursor: 'pointer',
            }}
          >
            <TeamOutlined />
            <span>
              {t('header.profile.userManagement', { defaultValue: '用户管理' })}
            </span>
          </div>
        </>
      )}
    </Drawer>
  );
}
