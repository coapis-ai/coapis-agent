import { useEffect, useState } from 'react';
import { Card, Tabs, Button, Space, Tag, Input, Switch, message, Modal, Alert, Spin } from 'antd';
import {
  ArrowLeftOutlined,
  SaveOutlined,
  CodeOutlined,
  CloudDownloadOutlined,
  DeleteOutlined,
  PlusOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { adminApi } from '@/api/modules/admin';
import styles from './GlobalAgentDetail.module.scss';

const { TextArea } = Input;

interface GlobalAgentDetailProps {
  agentId: string;
  onBack: () => void;
}

export default function GlobalAgentDetail({ agentId, onBack }: GlobalAgentDetailProps) {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(true);
  const [agent, setAgent] = useState<any>(null);
  const [skills, setSkills] = useState<any[]>([]);
  const [skillsLoading, setSkillsLoading] = useState(false);

  // Identity file editors
  const [soulContent, setSoulContent] = useState('');
  const [memoryContent, setMemoryContent] = useState('');
  const [profileContent, setProfileContent] = useState('');
  const [agentsContent, setAgentsContent] = useState('');
  const [bootstrapContent, setBootstrapContent] = useState('');
  const [heartbeatContent, setHeartbeatContent] = useState('');
  const [activeEditor, setActiveEditor] = useState<string | null>(null);

  // Skill pool for installation
  const [skillPoolOpen, setSkillPoolOpen] = useState(false);
  const [availableSkills, setAvailableSkills] = useState<string[]>([]);
  const [installingSkill, setInstallingSkill] = useState<string | null>(null);

  // Load agent details
  useEffect(() => {
    loadAgent();
  }, [agentId]);

  const loadAgent = async () => {
    setLoading(true);
    try {
      const res: any = await adminApi.getGlobalAgent(agentId);
      setAgent(res);
      setSoulContent(res.soul || '');
      setMemoryContent(res.memory || '');
      setProfileContent(res.profile || '');
      setAgentsContent(res.agents || '');
      setBootstrapContent(res.bootstrap || '');
      setHeartbeatContent(res.heartbeat || '');
    } catch (e: any) {
      message.error(e?.message || t('admin.agentLoadFailed'));
    } finally {
      setLoading(false);
    }
  };

  const loadSkills = async () => {
    setSkillsLoading(true);
    try {
      const res: any = await adminApi.listGlobalAgentSkills(agentId);
      setSkills(res.skills || []);
    } catch (e: any) {
      message.error(e?.message || t('admin.skillsLoadFailed'));
    } finally {
      setSkillsLoading(false);
    }
  };

  // Save identity file
  const saveIdentityFile = async (filename: string, content: string) => {
    const keyMap: Record<string, string> = {
      'SOUL.md': 'soul',
      'MEMORY.md': 'memory',
      'PROFILE.md': 'profile',
      'AGENTS.md': 'agents',
      'BOOTSTRAP.md': 'bootstrap',
      'HEARTBEAT.md': 'heartbeat',
    };
    try {
      await adminApi.updateGlobalAgent(agentId, { [keyMap[filename]]: content });
      message.success(t('admin.identityFileSaved', { filename }));
      setActiveEditor(null);
      loadAgent();
    } catch (e: any) {
      message.error(e?.message || t('admin.identityFileSaveFailed'));
    }
  };

  // Load available skills from global pool
  const loadSkillPool = async () => {
    try {
      // Get available skills from backend
      const poolRes: any = await fetch('/api/admin/skills/pool').then((r) => r.json());
      setAvailableSkills(poolRes.skills || []);
      setSkillPoolOpen(true);
    } catch (e: any) {
      message.error(e?.message || t('admin.skillPoolLoadFailed'));
    }
  };

  // Install skill
  const handleInstallSkill = async (skillName: string) => {
    setInstallingSkill(skillName);
    try {
      await adminApi.installSkillToGlobalAgent(agentId, skillName);
      message.success(t('admin.skillInstalled', { skillName }));
      setSkillPoolOpen(false);
      loadSkills();
    } catch (e: any) {
      message.error(e?.message || t('admin.skillInstallFailed'));
    } finally {
      setInstallingSkill(null);
    }
  };

  // Uninstall skill
  const handleUninstallSkill = (skillName: string) => {
    Modal.confirm({
      title: t('admin.uninstallSkillConfirm', { skillName }),
      content: t('admin.uninstallSkillDesc'),
      onOk: async () => {
        try {
          await adminApi.uninstallSkillFromGlobalAgent(agentId, skillName);
          message.success(t('admin.skillUninstalled', { skillName }));
          loadSkills();
        } catch (e: any) {
          message.error(e?.message || t('admin.skillUninstallFailed'));
        }
      },
    });
  };

  // Toggle skill
  const handleToggleSkill = async (skillName: string, enabled: boolean) => {
    try {
      await adminApi.toggleGlobalAgentSkill(agentId, skillName, enabled);
      message.success(
        enabled ? t('admin.skillEnabled') : t('admin.skillDisabled')
      );
      loadSkills();
    } catch (e: any) {
      message.error(e?.message || t('admin.skillToggleFailed'));
    }
  };

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: '80px 0' }}>
        <Spin size="large" />
      </div>
    );
  }

  const identityTabs = [
    {
      key: 'soul',
      label: 'SOUL.md',
      children: (
        <div className={styles.editorContainer}>
          {activeEditor === 'soul' ? (
            <Space direction="vertical" style={{ width: '100%' }} size="large">
              <TextArea
                value={soulContent}
                onChange={(e) => setSoulContent(e.target.value)}
                autoSize={{ minRows: 20, maxRows: 30 }}
                className={styles.codeEditor}
              />
              <Space>
                <Button
                  type="primary"
                  icon={<SaveOutlined />}
                  onClick={() => saveIdentityFile('SOUL.md', soulContent)}
                >
                  {t('common.save')}
                </Button>
                <Button onClick={() => setActiveEditor(null)}>
                  {t('common.cancel')}
                </Button>
              </Space>
            </Space>
          ) : (
            <div>
              <pre className={styles.fileContent}>{soulContent}</pre>
              <Button
                icon={<CodeOutlined />}
                onClick={() => setActiveEditor('soul')}
              >
                {t('common.edit')}
              </Button>
            </div>
          )}
        </div>
      ),
    },
    {
      key: 'memory',
      label: 'MEMORY.md',
      children: (
        <div className={styles.editorContainer}>
          {activeEditor === 'memory' ? (
            <Space direction="vertical" style={{ width: '100%' }} size="large">
              <TextArea
                value={memoryContent}
                onChange={(e) => setMemoryContent(e.target.value)}
                autoSize={{ minRows: 20, maxRows: 30 }}
                className={styles.codeEditor}
              />
              <Space>
                <Button
                  type="primary"
                  icon={<SaveOutlined />}
                  onClick={() => saveIdentityFile('MEMORY.md', memoryContent)}
                >
                  {t('common.save')}
                </Button>
                <Button onClick={() => setActiveEditor(null)}>
                  {t('common.cancel')}
                </Button>
              </Space>
            </Space>
          ) : (
            <div>
              <pre className={styles.fileContent}>{memoryContent}</pre>
              <Button
                icon={<CodeOutlined />}
                onClick={() => setActiveEditor('memory')}
              >
                {t('common.edit')}
              </Button>
            </div>
          )}
        </div>
      ),
    },
    {
      key: 'profile',
      label: 'PROFILE.md',
      children: (
        <div className={styles.editorContainer}>
          {activeEditor === 'profile' ? (
            <Space direction="vertical" style={{ width: '100%' }} size="large">
              <TextArea
                value={profileContent}
                onChange={(e) => setProfileContent(e.target.value)}
                autoSize={{ minRows: 20, maxRows: 30 }}
                className={styles.codeEditor}
              />
              <Space>
                <Button
                  type="primary"
                  icon={<SaveOutlined />}
                  onClick={() => saveIdentityFile('PROFILE.md', profileContent)}
                >
                  {t('common.save')}
                </Button>
                <Button onClick={() => setActiveEditor(null)}>
                  {t('common.cancel')}
                </Button>
              </Space>
            </Space>
          ) : (
            <div>
              <pre className={styles.fileContent}>{profileContent}</pre>
              <Button
                icon={<CodeOutlined />}
                onClick={() => setActiveEditor('profile')}
              >
                {t('common.edit')}
              </Button>
            </div>
          )}
        </div>
      ),
    },
    {
      key: 'agents',
      label: 'AGENTS.md',
      children: (
        <div className={styles.editorContainer}>
          {activeEditor === 'agents' ? (
            <Space direction="vertical" style={{ width: '100%' }} size="large">
              <TextArea
                value={agentsContent}
                onChange={(e) => setAgentsContent(e.target.value)}
                autoSize={{ minRows: 20, maxRows: 30 }}
                className={styles.codeEditor}
              />
              <Space>
                <Button
                  type="primary"
                  icon={<SaveOutlined />}
                  onClick={() => saveIdentityFile('AGENTS.md', agentsContent)}
                >
                  {t('common.save')}
                </Button>
                <Button onClick={() => setActiveEditor(null)}>
                  {t('common.cancel')}
                </Button>
              </Space>
            </Space>
          ) : (
            <div>
              <pre className={styles.fileContent}>{agentsContent}</pre>
              <Button
                icon={<CodeOutlined />}
                onClick={() => setActiveEditor('agents')}
              >
                {t('common.edit')}
              </Button>
            </div>
          )}
        </div>
      ),
    },
    {
      key: 'bootstrap',
      label: 'BOOTSTRAP.md',
      children: (
        <div className={styles.editorContainer}>
          {activeEditor === 'bootstrap' ? (
            <Space direction="vertical" style={{ width: '100%' }} size="large">
              <TextArea
                value={bootstrapContent}
                onChange={(e) => setBootstrapContent(e.target.value)}
                autoSize={{ minRows: 20, maxRows: 30 }}
                className={styles.codeEditor}
              />
              <Space>
                <Button
                  type="primary"
                  icon={<SaveOutlined />}
                  onClick={() => saveIdentityFile('BOOTSTRAP.md', bootstrapContent)}
                >
                  {t('common.save')}
                </Button>
                <Button onClick={() => setActiveEditor(null)}>
                  {t('common.cancel')}
                </Button>
              </Space>
            </Space>
          ) : (
            <div>
              <pre className={styles.fileContent}>{bootstrapContent}</pre>
              <Button
                icon={<CodeOutlined />}
                onClick={() => setActiveEditor('bootstrap')}
              >
                {t('common.edit')}
              </Button>
            </div>
          )}
        </div>
      ),
    },
    {
      key: 'heartbeat',
      label: 'HEARTBEAT.md',
      children: (
        <div className={styles.editorContainer}>
          {activeEditor === 'heartbeat' ? (
            <Space direction="vertical" style={{ width: '100%' }} size="large">
              <TextArea
                value={heartbeatContent}
                onChange={(e) => setHeartbeatContent(e.target.value)}
                autoSize={{ minRows: 20, maxRows: 30 }}
                className={styles.codeEditor}
              />
              <Space>
                <Button
                  type="primary"
                  icon={<SaveOutlined />}
                  onClick={() => saveIdentityFile('HEARTBEAT.md', heartbeatContent)}
                >
                  {t('common.save')}
                </Button>
                <Button onClick={() => setActiveEditor(null)}>
                  {t('common.cancel')}
                </Button>
              </Space>
            </Space>
          ) : (
            <div>
              <pre className={styles.fileContent}>{heartbeatContent}</pre>
              <Button
                icon={<CodeOutlined />}
                onClick={() => setActiveEditor('heartbeat')}
              >
                {t('common.edit')}
              </Button>
            </div>
          )}
        </div>
      ),
    },
  ];

  return (
    <div>
      <Button
        type="link"
        icon={<ArrowLeftOutlined />}
        onClick={onBack}
        style={{ marginBottom: 16, paddingLeft: 0 }}
      >
        {t('admin.backToList')}
      </Button>

      <Card
        title={
          <Space>
            <span style={{ fontSize: 18, fontWeight: 'bold' }}>
              {agent?.name || agentId}
            </span>
            <Tag color={agent?.enabled ? 'green' : 'red'}>
              {agent?.enabled ? t('common.enabled') : t('common.disabled')}
            </Tag>
          </Space>
        }
        extra={
          <Space>
            <Button onClick={loadAgent}>{t('common.refresh')}</Button>
          </Space>
        }
      >
        <Tabs
          defaultActiveKey="identity"
          items={[
            {
              key: 'identity',
              label: `${t('admin.identityFiles')} (AGENTS/SOUL/PROFILE/MEMORY/BOOTSTRAP/HEARTBEAT)`,
              children: <Tabs type="card" items={identityTabs} />,
            },
            {
              key: 'skills',
              label: `${t('admin.skills')} (${skills.length})`,
              children: (
                <div>
                  <Alert
                    type="info"
                    message={t('admin.skillsDescription')}
                    style={{ marginBottom: 16 }}
                  />

                  <Space style={{ marginBottom: 16 }}>
                    <Button
                      type="primary"
                      icon={<PlusOutlined />}
                      onClick={loadSkillPool}
                    >
                      {t('admin.installSkill')}
                    </Button>
                    <Button onClick={loadSkills}>{t('common.refresh')}</Button>
                  </Space>

                  {skillsLoading ? (
                    <Spin />
                  ) : skills.length === 0 ? (
                    <Alert
                      type="warning"
                      message={t('admin.noSkillsInstalled')}
                      showIcon
                    />
                  ) : (
                    <div className={styles.skillsList}>
                      {skills.map((skill) => (
                        <Card
                          key={skill.name}
                          size="small"
                          className={styles.skillCard}
                          extra={
                            <Space>
                              <Switch
                                size="small"
                                checked={skill.enabled}
                                onChange={(checked) =>
                                  handleToggleSkill(skill.name, checked)
                                }
                              />
                              <Tag color={skill.source}>
                                {skill.source}
                              </Tag>
                            </Space>
                          }
                        >
                          <div className={styles.skillInfo}>
                            <div className={styles.skillName}>
                              {skill.name}
                              {skill.version && (
                                <Tag style={{ marginLeft: 8 }}>
                                  v{skill.version}
                                </Tag>
                              )}
                            </div>
                            <div className={styles.skillDesc}>
                              {skill.description || t('admin.noDescription')}
                            </div>
                          </div>
                          <div className={styles.skillActions}>
                            <Button
                              size="small"
                              danger
                              icon={<DeleteOutlined />}
                              onClick={() => handleUninstallSkill(skill.name)}
                            >
                              {t('admin.uninstall')}
                            </Button>
                          </div>
                        </Card>
                      ))}
                    </div>
                  )}
                </div>
              ),
            },
            {
              key: 'config',
              label: t('admin.config'),
              children: (
                <div>
                  <Alert
                    type="info"
                    message={t('admin.configDescription')}
                    style={{ marginBottom: 16 }}
                  />
                  <pre className={styles.fileContent}>
                    {JSON.stringify(agent?.agent_json || {}, null, 2)}
                  </pre>
                </div>
              ),
            },
          ]}
        />
      </Card>

      {/* Skill Pool Modal */}
      <Modal
        title={t('admin.installSkillFromPool')}
        open={skillPoolOpen}
        onCancel={() => setSkillPoolOpen(false)}
        footer={null}
      >
        <p style={{ marginBottom: 16 }}>
          {t('admin.skillPoolDescription')}
        </p>
        <div className={styles.skillPoolList}>
          {availableSkills.length === 0 ? (
            <Alert type="warning" message={t('admin.noAvailableSkills')} />
          ) : (
            availableSkills.map((skillName) => {
              const isInstalled = skills.some((s) => s.name === skillName);
              return (
                <Card
                  key={skillName}
                  size="small"
                  className={styles.poolSkillCard}
                  style={{
                    opacity: isInstalled ? 0.5 : 1,
                    marginBottom: 8,
                  }}
                >
                  <div style={{ width: '100%', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                      <strong>{skillName}</strong>
                      {isInstalled && (
                        <Tag color="default" style={{ marginLeft: 8 }}>
                          {t('admin.alreadyInstalled')}
                        </Tag>
                      )}
                    </div>
                    <Button
                      size="small"
                      type="primary"
                      icon={<CloudDownloadOutlined />}
                      disabled={isInstalled || installingSkill === skillName}
                      loading={installingSkill === skillName}
                      onClick={() => handleInstallSkill(skillName)}
                    >
                      {t('admin.install')}
                    </Button>
                  </div>
                </Card>
              );
            })
          )}
        </div>
      </Modal>
    </div>
  );
}
