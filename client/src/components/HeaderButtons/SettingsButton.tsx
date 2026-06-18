import { useState } from 'react';
import { Button, Drawer, Switch, Select, Divider, Typography } from 'antd';
import { SettingOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { useUser } from '../../contexts/UserContext';
import { useTheme, type ThemeMode } from '../../contexts/ThemeContext';

const { Text } = Typography;

export default function SettingsButton() {
  const { t, i18n } = useTranslation();
  const { preferences, updatePreferences } = useUser();
  const { themeMode, setThemeMode } = useTheme();
  const [open, setOpen] = useState(false);

  // Local form state
  const [localTheme, setLocalTheme] = useState<ThemeMode>(preferences.theme as ThemeMode || themeMode);
  const [language, setLanguage] = useState(preferences.language || i18n.language || 'en');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(!!preferences.sidebar_collapsed);
  const [chatDisplayMode, setChatDisplayMode] = useState(preferences.chat_display_mode || 'full');
  const [hideToolCall, setHideToolCall] = useState(!!preferences.chat_hide_tool_call);
  const [hideThinking, setHideThinking] = useState(!!preferences.chat_hide_thinking);
  const [hideFooter, setHideFooter] = useState(!!preferences.chat_hide_footer);
  const [hideSystemMessages, setHideSystemMessages] = useState(!!preferences.chat_hide_system_messages);
  const [emailNotif, setEmailNotif] = useState(!!preferences.email_notifications);
  const [pushNotif, setPushNotif] = useState(!!preferences.push_notifications);

  // Sync when drawer opens
  const handleOpen = () => {
    setLocalTheme(preferences.theme as ThemeMode || themeMode);
    setLanguage(preferences.language || i18n.language || 'en');
    setSidebarCollapsed(!!preferences.sidebar_collapsed);
    setChatDisplayMode(preferences.chat_display_mode || 'full');
    setHideToolCall(!!preferences.chat_hide_tool_call);
    setHideThinking(!!preferences.chat_hide_thinking);
    setHideFooter(!!preferences.chat_hide_footer);
    setHideSystemMessages(!!preferences.chat_hide_system_messages);
    setEmailNotif(!!preferences.email_notifications);
    setPushNotif(!!preferences.push_notifications);
    setOpen(true);
  };

  const handleSave = () => {
    updatePreferences({
      theme: localTheme,
      language,
      sidebar_collapsed: sidebarCollapsed ? 1 : 0,
      chat_display_mode: chatDisplayMode,
      chat_hide_tool_call: hideToolCall ? 1 : 0,
      chat_hide_thinking: hideThinking ? 1 : 0,
      chat_hide_footer: hideFooter ? 1 : 0,
      chat_hide_system_messages: hideSystemMessages ? 1 : 0,
      email_notifications: emailNotif ? 1 : 0,
      push_notifications: pushNotif ? 1 : 0,
    });

    // Apply language change immediately
    if (language !== i18n.language) {
      i18n.changeLanguage(language);
      localStorage.setItem('language', language);
    }

    // Apply theme change immediately
    setThemeMode(localTheme);

    setOpen(false);
  };

  const items = [
    {
      key: 'appearance',
      title: t('header.settings.appearance'),
      children: (
        <>
          <div style={{ marginBottom: 16 }}>
            <Text strong>{t('header.settings.theme')}</Text>
            <Select
              value={localTheme}
              onChange={setLocalTheme}
              style={{ width: '100%', marginTop: 8 }}
              options={[
                { label: t('header.settings.themeLight'), value: 'light' },
                { label: t('header.settings.themeDark'), value: 'dark' },
                { label: t('theme.system'), value: 'system' },
              ]}
            />
          </div>
          <div style={{ marginBottom: 16 }}>
            <Text strong>{t('header.settings.language')}</Text>
            <Select
              value={language}
              onChange={setLanguage}
              style={{ width: '100%', marginTop: 8 }}
              options={[
                { label: 'English', value: 'en' },
                { label: '简体中文', value: 'zh' },
                { label: '日本語', value: 'ja' },
                { label: 'Русский', value: 'ru' },
              ]}
            />
          </div>
          <div style={{ marginBottom: 16 }}>
            <Text strong>{t('header.settings.sidebarCollapsed')}</Text>
            <Switch
              checked={sidebarCollapsed}
              onChange={setSidebarCollapsed}
              style={{ marginLeft: 8 }}
            />
          </div>
        </>
      ),
    },
    {
      key: 'chat',
      title: t('header.settings.chat'),
      children: (
        <>
          <div style={{ marginBottom: 16 }}>
            <Text strong>{t('header.settings.chatDisplayMode')}</Text>
            <Select
              value={chatDisplayMode}
              onChange={setChatDisplayMode}
              style={{ width: '100%', marginTop: 8 }}
              options={[
                { label: t('header.settings.chatFull'), value: 'full' },
                { label: t('header.settings.chatSimplified'), value: 'simplified' },
                { label: t('header.settings.chatMinimal'), value: 'minimal' },
              ]}
            />
          </div>
          <div style={{ marginBottom: 12 }}>
            <Text>{t('header.settings.hideToolCall')}</Text>
            <Switch
              checked={hideToolCall}
              onChange={setHideToolCall}
              style={{ marginLeft: 8 }}
            />
          </div>
          <div style={{ marginBottom: 12 }}>
            <Text>{t('header.settings.hideThinking')}</Text>
            <Switch
              checked={hideThinking}
              onChange={setHideThinking}
              style={{ marginLeft: 8 }}
            />
          </div>
          <div style={{ marginBottom: 12 }}>
            <Text>{t('header.settings.hideFooter')}</Text>
            <Switch
              checked={hideFooter}
              onChange={setHideFooter}
              style={{ marginLeft: 8 }}
            />
          </div>
          <div style={{ marginBottom: 12 }}>
            <Text>{t('header.settings.hideSystemMessages')}</Text>
            <Switch
              checked={hideSystemMessages}
              onChange={setHideSystemMessages}
              style={{ marginLeft: 8 }}
            />
          </div>
        </>
      ),
    },
    {
      key: 'notifications',
      title: t('header.settings.notifications'),
      children: (
        <>
          <div style={{ marginBottom: 12 }}>
            <Text>{t('header.settings.emailNotifications')}</Text>
            <Switch
              checked={emailNotif}
              onChange={setEmailNotif}
              style={{ marginLeft: 8 }}
            />
          </div>
          <div style={{ marginBottom: 12 }}>
            <Text>{t('header.settings.pushNotifications')}</Text>
            <Switch
              checked={pushNotif}
              onChange={setPushNotif}
              style={{ marginLeft: 8 }}
            />
          </div>
        </>
      ),
    },
  ];

  return (
    <>
      <Button
        type="text"
        icon={<SettingOutlined />}
        title={t('header.settings.title')}
        onClick={handleOpen}
        style={{ fontSize: '16px' }}
      />
      <Drawer
        title={t('header.settings.title')}
        placement="right"
        width={380}
        open={open}
        onClose={() => setOpen(false)}
        extra={
          <Button type="primary" onClick={handleSave}>
            {t('header.settings.save')}
          </Button>
        }
      >
        <div>
          {items.map((section) => (
            <div key={section.key} style={{ marginBottom: 24 }}>
              <Text strong style={{ fontSize: 14 }}>
                {section.title}
              </Text>
              <Divider style={{ marginTop: 8, marginBottom: 12 }} />
              {section.children}
            </div>
          ))}
        </div>
      </Drawer>
    </>
  );
}
