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
  const [hideDetails, setHideDetails] = useState(!!preferences.chat_hide_details);
  const [emailNotif, setEmailNotif] = useState(!!preferences.email_notifications);
  const [pushNotif, setPushNotif] = useState(!!preferences.push_notifications);

  // Sync when drawer opens
  const handleOpen = () => {
    setLocalTheme(preferences.theme as ThemeMode || themeMode);
    setLanguage(preferences.language || i18n.language || 'en');
    setSidebarCollapsed(!!preferences.sidebar_collapsed);
    setHideDetails(!!preferences.chat_hide_details);
    setEmailNotif(!!preferences.email_notifications);
    setPushNotif(!!preferences.push_notifications);
    setOpen(true);
  };

  const handleSave = () => {
    updatePreferences({
      theme: localTheme,
      language,
      sidebar_collapsed: sidebarCollapsed ? 1 : 0,
      chat_hide_details: hideDetails ? 1 : 0,
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
      title: t('header.settings.appearance', { defaultValue: '外观' }),
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
      title: t('header.settings.chat', { defaultValue: '聊天' }),
      children: (
        <>
          <div style={{ marginBottom: 12 }}>
            <Text>{t('header.settings.hideDetails', { defaultValue: '隐藏细节' })}</Text>
            <Switch
              checked={hideDetails}
              onChange={setHideDetails}
              style={{ marginLeft: 8 }}
            />
          </div>
          <div style={{ fontSize: 12, color: '#999' }}>
            {t('header.settings.hideDetailsDesc', { 
              defaultValue: '开启后，思考过程、工具调用、正文内容将显示摘要' 
            })}
          </div>
        </>
      ),
    },
    {
      key: 'notifications',
      title: t('header.settings.notifications', { defaultValue: '通知' }),
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
        onClick={handleOpen}
      />
      <Drawer
        title={t('header.settings.title', { defaultValue: '设置' })}
        placement="right"
        width={360}
        onClose={() => setOpen(false)}
        open={open}
        footer={
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
            <Button onClick={() => setOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button type="primary" onClick={handleSave}>
              {t('common.save')}
            </Button>
          </div>
        }
      >
        {items.map((item, index) => (
          <div key={item.key}>
            {index > 0 && <Divider />}
            <Text strong style={{ display: 'block', marginBottom: 12 }}>
              {item.title}
            </Text>
            {item.children}
          </div>
        ))}
      </Drawer>
    </>
  );
}
