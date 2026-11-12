import { useState } from 'react';
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
import {
  isNoticeEnabled,
  setNoticeEnabled,
  getSilenceUntil,
  silenceFor,
  clearSilence,
} from '../../lib/updateNotice';

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
  // 通知与弹窗：浏览器本地状态（单一实现在 lib/updateNotice）
  const [noticeEnabled, setNoticeEnabledState] = useState(() => isNoticeEnabled());
  const [silenceUntil, setSilenceUntil] = useState(() => getSilenceUntil());

  const changeLang = (lang: string) => {
    i18n.changeLanguage(lang);
    localStorage.setItem('language', lang);
    languageApi.updateLanguage(lang).catch(() => {});
  };

  const toggleHideDetails = (checked: boolean) => {
    updateDisplayConfig('hideDetails', checked);
  };

  const toggleShowThinking = (checked: boolean) => {
    // UI 是「显示思考内容」，存储字段是 hideThinking（后端 chat_hide_thinking）
    updateDisplayConfig('hideThinking', !checked);
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

      {/* 显示思考内容 — Switch = hideThinking 取反；后端字段 chat_hide_thinking */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
        <Switch
          size='small'
          checked={!displayConfig.hideThinking}
          onChange={(checked) => toggleShowThinking(checked)}
        />
        <span>
          {t('chat.settings.showThinking.label', {
            defaultValue: '显示思考内容',
          })}
        </span>
      </div>
      <Text type='secondary' style={{ fontSize: 12 }}>
        {t('chat.settings.showThinking.desc', {
          defaultValue: '关闭后，思考过程只保留一条折叠条，点击可展开',
        })}
      </Text>


      <Divider style={{ margin: '16px 0' }} />

      {/* ── 通知与弹窗 ───────────────────────────
          版本更新弹窗的开关与免打扰收纳在这里（唯一设置入口）；
          状态存浏览器本地（lib/updateNotice）——更新作用于本机安装包，
          属浏览器级状态，不占后端用户偏好字段。 */}
      <SectionTitle>
        {t('header.profile.sectionNotifications', { defaultValue: '通知与弹窗' })}
      </SectionTitle>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <Switch size='small' checked={noticeEnabled} onChange={(checked) => {
          setNoticeEnabled(checked);
          setNoticeEnabledState(checked);
        }} />
        <span>
          {t('header.updateNotice.autoPopupLabel', { defaultValue: '版本更新自动弹窗' })}
        </span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
        {silenceUntil > Date.now() ? (
          <>
            <Button size='small' onClick={() => {
              clearSilence();
              setSilenceUntil(0);
            }}>
              {t('header.updateNotice.restoreNow', { defaultValue: '恢复提醒' })}
            </Button>
            <Text type='secondary' style={{ fontSize: 12 }}>
              {t('header.updateNotice.silencedUntil', {
                defaultValue: '已免打扰至 {{until}}',
                until: new Date(silenceUntil).toLocaleString(),
              })}
            </Text>
          </>
        ) : (
          <Button size='small' onClick={() => setSilenceUntil(silenceFor(72 * 3600 * 1000))}>
            {t('header.updateNotice.silence72', { defaultValue: '72 小时内不提醒' })}
          </Button>
        )}
      </div>
      <Text type='secondary' style={{ fontSize: 12 }}>
        {t('header.updateNotice.noticeDesc', {
          defaultValue: '发现新版本时自动提示一次；关闭后仅在顶栏出现更新图标时提醒',
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
