import { useEffect, useState } from 'react';
import { Card, Button, Space, Input, message, Spin, Alert, Tag, Modal, Radio } from 'antd';
import { SaveOutlined, ReloadOutlined, WarningOutlined, CloudSyncOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { adminApi } from '@/api/modules/admin';

const { TextArea } = Input;

const TEMPLATES = [
  { key: 'SOUL.md', label: 'SOUL.md', desc: '智能体性格与行为准则' },
  { key: 'MEMORY.md', label: 'MEMORY.md', desc: '智能体长期记忆模板' },
  { key: 'PROFILE.md', label: 'PROFILE.md', desc: '智能体身份与用户资料模板' },
];

export default function TemplatesTab() {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState<string | null>(null);
  const [templates, setTemplates] = useState<Record<string, string>>({});
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [syncModal, setSyncModal] = useState(false);
  const [syncStrategy, setSyncStrategy] = useState<'new_only' | 'overwrite'>('new_only');
  const [syncing, setSyncing] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const res: any = await adminApi.getTemplates();
      const data = res.templates || res;
      setTemplates(data);
      setEdits(data);
    } catch (e: any) {
      message.error(e?.message || t('admin.templatesLoadFailed'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const handleSave = async (key: string) => {
    setSaving(key);
    try {
      await adminApi.updateTemplate(key, edits[key]);
      message.success(t('admin.templateSaved', { name: key }));
      setTemplates((prev) => ({ ...prev, [key]: edits[key] }));
    } catch (e: any) {
      message.error(e?.message || t('admin.templateSaveFailed'));
    } finally {
      setSaving(null);
    }
  };

  const handleReset = async (key: string) => {
    try {
      await adminApi.resetTemplate(key);
      message.success(t('admin.templateReset', { name: key }));
      load();
    } catch (e: any) {
      message.error(e?.message || t('admin.templateResetFailed'));
    }
  };

  const handleChange = (key: string, value: string) => {
    setEdits((prev) => ({ ...prev, [key]: value }));
  };

  const handleSyncToUsers = async () => {
    setSyncing(true);
    try {
      const res: any = await adminApi.syncTemplatesToUsers(syncStrategy);
      message.success(`同步完成：${res.synced} 个文件已同步，${res.skipped} 个跳过，${res.backups} 个已备份`);
      setSyncModal(false);
    } catch (e: any) {
      message.error(e?.message || '同步失败');
    } finally {
      setSyncing(false);
    }
  };

  if (loading) {
    return (
      <Card>
        <Spin size="large" style={{ display: 'block', margin: '40px auto' }} />
      </Card>
    );
  }

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      <Alert
        message={t('admin.templatesWarning')}
        description={t('admin.templatesWarningDesc')}
        type="warning"
        showIcon
        icon={<WarningOutlined />}
      />

      <Card size="small">
        <Space>
          <Button type="primary" icon={<CloudSyncOutlined />} onClick={() => setSyncModal(true)}>
            同步到已有用户
          </Button>
          <span style={{ color: '#999', fontSize: 13 }}>将全局模板推送到所有已有用户的智能体 workspace</span>
        </Space>
      </Card>

      {TEMPLATES.map((tpl) => {
        const content = edits[tpl.key] || '';
        const original = templates[tpl.key] || '';
        const hasChanges = content !== original;

        return (
          <Card
            key={tpl.key}
            title={
              <Space>
                <Tag color="blue">{tpl.label}</Tag>
                <span style={{ color: '#999' }}>{tpl.desc}</span>
                {hasChanges && <Tag color="orange">{t('admin.unsavedChanges')}</Tag>}
              </Space>
            }
            extra={
              <Space>
                <Button
                  icon={<ReloadOutlined />}
                  onClick={() => handleReset(tpl.key)}
                  danger
                >
                  {t('admin.resetToDefault')}
                </Button>
                <Button
                  type="primary"
                  icon={<SaveOutlined />}
                  loading={saving === tpl.key}
                  disabled={!hasChanges}
                  onClick={() => handleSave(tpl.key)}
                >
                  {t('common.save')}
                </Button>
              </Space>
            }
          >
            <TextArea
              rows={16}
              value={content}
              onChange={(e) => handleChange(tpl.key, e.target.value)}
              style={{ fontFamily: 'monospace', fontSize: '13px' }}
            />
          </Card>
        );
      })}

      <Modal
        title="同步模板到已有用户"
        open={syncModal}
        onOk={handleSyncToUsers}
        onCancel={() => setSyncModal(false)}
        confirmLoading={syncing}
        okText="确认同步"
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Alert message="此操作会将全局模板文件推送到所有已有用户智能体的 workspace 目录。" type="info" showIcon />
          <div>
            <strong>同步策略：</strong>
            <Radio.Group
              value={syncStrategy}
              onChange={(e) => setSyncStrategy(e.target.value)}
              style={{ marginTop: 8 }}
            >
              <Space direction="vertical">
                <Radio value="new_only">仅同步新文件（不覆盖已存在的文件）</Radio>
                <Radio value="overwrite">强制覆盖（会先备份用户原文件）</Radio>
              </Space>
            </Radio.Group>
          </div>
        </Space>
      </Modal>
    </Space>
  );
}
