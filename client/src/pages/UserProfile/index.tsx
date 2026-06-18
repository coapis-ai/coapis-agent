import { useState, useEffect } from 'react';
import { Card, Row, Col, Avatar, Descriptions, Tag, Button, Input, Form, message, Spin, Divider, Switch, Space } from 'antd';
import { UserOutlined, ThunderboltOutlined, CloudServerOutlined, SaveOutlined, EditOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { useUser } from '@/contexts/UserContext';
import { getCurrentUser, getUserPreferences, updateUserPreferences } from '@/api/modules/user_me';
import { authApi } from '@/api/modules/auth';
import styles from './index.module.css';

export default function UserProfilePage() {
  const { t } = useTranslation();
  const { user, refreshUser } = useUser();
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [form] = Form.useForm();
  const [prefsForm] = Form.useForm();
  const [userDetails, setUserDetails] = useState<any>(null);
  const [passwordForm] = Form.useForm();

  // Load detailed user info and preferences
  useEffect(() => {
    Promise.all([
      getCurrentUser().catch(() => null),
      getUserPreferences().catch(() => ({})),
    ]).then(([userData, prefsData]) => {
      setUserDetails(userData);
      if (userData) {
        form.setFieldsValue({
          username: (userData as any).username,
          display_name: (userData as any).display_name || '',
        });
      }
      if (prefsData) {
        prefsForm.setFieldsValue({
          theme: (prefsData as any).theme || 'system',
          language: (prefsData as any).language || 'en',
          chat_display_mode: (prefsData as any).chat_display_mode || 'full',
          chat_hide_tool_call: !!(prefsData as any).chat_hide_tool_call,
          chat_hide_thinking: !!(prefsData as any).chat_hide_thinking,
        });
      }
      setLoading(false);
    });
  }, []);

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

  const handleSaveProfile = async () => {
    try {
      await form.validateFields();
      message.success(t('common.save'));
      setEditing(false);
    } catch {
      // Validation failed
    }
  };

  const handleSavePreferences = async () => {
    try {
      const values = await prefsForm.validateFields();
      await updateUserPreferences({
        theme: values.theme,
        language: values.language,
        chat_display_mode: values.chat_display_mode,
        chat_hide_tool_call: values.chat_hide_tool_call ? 1 : 0,
        chat_hide_thinking: values.chat_hide_thinking ? 1 : 0,
      });
      message.success(t('header.settings.save'));
      refreshUser();
    } catch {
      message.error(t('common.saveFailed') || 'Save failed');
    }
  };

  const handleChangePassword = async () => {
    try {
      const values = await passwordForm.validateFields();
      await authApi.updateProfile(values.currentPassword, undefined, values.newPassword);
      message.success(t('usersystem.passwordChanged'));
      passwordForm.resetFields();
    } catch (e: any) {
      message.error(e?.message || t('usersystem.passwordChangeFailed'));
    }
  };

  if (loading) {
    return (
      <div className={styles.profileContainer}>
        <Spin size="large" style={{ display: 'block', margin: '80px auto' }} />
      </div>
    );
  }

  const displayName = userDetails?.display_name || userDetails?.username || user?.username || '';
  const initials = displayName.charAt(0).toUpperCase();

  return (
    <div className={styles.profileContainer}>
      <Row gutter={24}>
        {/* Left: User Info Card */}
        <Col span={8}>
          <Card className={styles.infoCard} bordered={false}>
            <div className={styles.avatarSection}>
              <Avatar
                size={80}
                style={{ backgroundColor: '#722ed1', color: '#fff', fontSize: '32px' }}
              >
                {initials}
              </Avatar>
              <h2 className={styles.userName}>{displayName}</h2>
              <Tag color={roleColors[userDetails?.role || user?.role]} className={styles.roleTag}>
                {roleLabels[userDetails?.role || user?.role] || userDetails?.role}
              </Tag>
            </div>

            <Divider />

            <Descriptions column={1} size="small" className={styles.infoDescriptions}>
              <Descriptions.Item label={t('usersystem.username')}>
                {userDetails?.username || user?.username}
              </Descriptions.Item>
              <Descriptions.Item label={t('usersystem.level')}>
                L{userDetails?.level || user?.level || 0}
              </Descriptions.Item>
              <Descriptions.Item label={t('usersystem.points')}>
                <Space>
                  <ThunderboltOutlined style={{ color: '#faad14' }} />
                  {userDetails?.points ?? user?.points ?? 0}
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label={t('usersystem.tokenRemaining')}>
                <Space>
                  <CloudServerOutlined style={{ color: '#1890ff' }} />
                  {userDetails?.token_remaining ?? user?.token_remaining ?? 0}
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label={t('usersystem.status')}>
                <Tag color={(userDetails?.is_active ?? user?.is_active) ? 'success' : 'error'}>
                  {(userDetails?.is_active ?? user?.is_active) ? t('common.enabled') : t('common.disabled')}
                </Tag>
              </Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>

        {/* Right: Settings */}
        <Col span={16}>
          {/* Profile Settings */}
          <Card
            title={
              <Space>
                <UserOutlined />
                <span>{t('userprofile.settings')}</span>
                {editing && (
                  <Button type="link" size="small" onClick={handleSaveProfile}>
                    <SaveOutlined /> {t('common.save')}
                  </Button>
                )}
              </Space>
            }
            extra={!editing && <Button size="small" icon={<EditOutlined />} onClick={() => setEditing(true)} />}
            bordered={false}
            className={styles.settingsCard}
          >
            <Form form={form} layout="vertical">
              <Form.Item name="username" label={t('usersystem.username')}>
                <Input disabled={!editing} />
              </Form.Item>
              <Form.Item name="display_name" label={t('usersystem.display_name')}>
                <Input disabled={!editing} placeholder={t('userprofile.displayNamePlaceholder')} />
              </Form.Item>
            </Form>
          </Card>

          {/* Preferences */}
          <Card
            title={
              <Space>
                <ThunderboltOutlined />
                <span>{t('userprofile.preferences')}</span>
              </Space>
            }
            extra={<Button type="primary" size="small" onClick={handleSavePreferences}>
              {t('common.save')}
            </Button>}
            bordered={false}
            className={styles.settingsCard}
          >
            <Form form={prefsForm} layout="vertical">
              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item name="theme" label={t('header.settings.theme')}>
                    <select className={styles.selectInput}>
                      <option value="light">{t('header.settings.themeLight')}</option>
                      <option value="dark">{t('header.settings.themeDark')}</option>
                      <option value="system">{t('theme.system')}</option>
                    </select>
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="language" label={t('header.settings.language')}>
                    <select className={styles.selectInput}>
                      <option value="en">English</option>
                      <option value="zh">简体中文</option>
                      <option value="ja">日本語</option>
                      <option value="ru">Русский</option>
                    </select>
                  </Form.Item>
                </Col>
              </Row>
              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item name="chat_display_mode" label={t('header.settings.chatDisplayMode')}>
                    <select className={styles.selectInput}>
                      <option value="full">{t('header.settings.chatFull')}</option>
                      <option value="simplified">{t('header.settings.chatSimplified')}</option>
                      <option value="minimal">{t('header.settings.chatMinimal')}</option>
                    </select>
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="chat_hide_tool_call" valuePropName="checked" label={t('header.settings.hideToolCall')}>
                    <Switch />
                  </Form.Item>
                </Col>
              </Row>
            </Form>
          </Card>

          {/* Password Change */}
          <Card
            title={t('userprofile.changePassword')}
            bordered={false}
            className={styles.settingsCard}
          >
            <Form form={passwordForm} layout="vertical" onFinish={handleChangePassword}>
              <Form.Item
                name="currentPassword"
                label={t('account.currentPassword')}
                rules={[{ required: true, message: t('account.currentPasswordRequired') }]}
              >
                <Input.Password />
              </Form.Item>
              <Form.Item
                name="newPassword"
                label={t('account.newPassword')}
                rules={[{ required: true, min: 6, message: t('usersystem.passwordMinLength') }]}
              >
                <Input.Password placeholder={t('account.newPasswordPlaceholder')} />
              </Form.Item>
              <Form.Item
                name="confirmPassword"
                label={t('account.confirmPassword')}
                dependencies={['newPassword']}
                rules={[
                  ({ getFieldValue }) => ({
                    validator(_, value) {
                      if (!value && !getFieldValue('newPassword')) return Promise.resolve();
                      if (value === getFieldValue('newPassword')) return Promise.resolve();
                      return Promise.reject(new Error(t('account.passwordMismatch')));
                    },
                  }),
                ]}
              >
                <Input.Password placeholder={t('account.confirmPasswordPlaceholder')} />
              </Form.Item>
              <Button type="primary" htmlType="submit" block>
                {t('userprofile.updatePassword')}
              </Button>
            </Form>
          </Card>
        </Col>
      </Row>
    </div>
  );
}
