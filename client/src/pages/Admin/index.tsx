import { useState, useEffect, useMemo } from 'react';
import { Card, Row, Col, Statistic, Table, Tag, Button, Space, Input, Modal, Form, message, Tabs, Select, Descriptions, Alert, Spin, Switch, Checkbox } from 'antd';
import {
  UserOutlined, TrophyOutlined, ThunderboltOutlined, CloudServerOutlined,
  PlusOutlined, DeleteOutlined, EditOutlined, SearchOutlined, ReloadOutlined,
  BarChartOutlined, FileTextOutlined, SettingOutlined, CrownOutlined,
  SafetyOutlined, StopOutlined, PlayCircleOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { useModuleAccess } from '@/hooks/useModuleAccess';
import PermissionMatrix from './components/PermissionMatrix';
import { CRUD_OPS } from './components/PermissionMatrix';
import {
  getTokenSummary, getUsersConfig,
} from '@/api/modules/user_system';
import {
  getSystemOverview, listUsers, createUser, deleteUser, disableUser, updateUser, getAuditLogs,
} from '@/api/modules/admin';
import { permissionsApi } from '@/api/modules/permissions';

import styles from './index.module.css';

const { Search } = Input;

export default function AdminPage() {
  const { t } = useTranslation();
  const { isAllowed } = useModuleAccess();

  if (!isAllowed('admin')) {
    return (
      <div className={styles.adminContainer}>
        <Alert
          type="error"
          showIcon
          message={t('admin.accessDenied')}
          description={t('admin.accessDeniedDesc')}
          style={{ maxWidth: 600, margin: '80px auto' }}
        />
      </div>
    );
  }

  return (
    <div className={styles.adminContainer}>
      <h1 className={styles.adminTitle}>
        <CrownOutlined /> {t('admin.title')}
      </h1>
      <AdminDashboard />
    </div>
  );
}

function AdminDashboard() {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState('overview');

  const tabItems = [
    {
      key: 'overview',
      label: <><BarChartOutlined /> {t('admin.overview')}</>,
      children: <OverviewTab />,
    },
    {
      key: 'users',
      label: <><UserOutlined /> {t('admin.users')}</>,
      children: <UsersTab />,
    },
    {
      key: 'permissions',
      label: <><SafetyOutlined /> {t('admin.roles')}</>,
      children: <PermissionsTab />,
    },
    {
      key: 'audit',
      label: <><FileTextOutlined /> {t('admin.audit')}</>,
      children: <AuditTab />,
    },
    {
      key: 'config',
      label: <><SettingOutlined /> {t('admin.quota')}</>,
      children: <ConfigTab />,
    },
  ];

  return (
    <Tabs
      activeKey={activeTab}
      onChange={setActiveTab}
      type="card"
      size="large"
      className={styles.adminTabs}
      items={tabItems}
    />
  );
}

// ── Overview Tab ──────────────────────────────────────────────────────────

function OverviewTab() {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(true);
  const [overview, setOverview] = useState<any>(null);
  const [summary, setSummary] = useState<any>(null);

  useEffect(() => {
    Promise.all([
      getSystemOverview().catch(() => ({ users: { total: 0 }, agents: { total: 0, running: 0 }, system: {} })),
      getTokenSummary().catch(() => ({})),
    ]).then(([ov, sm]) => {
      setOverview(ov);
      setSummary(sm);
      setLoading(false);
    });
  }, []);

  if (loading) {
    return <Spin size="large" style={{ display: 'block', margin: '40px auto' }} />;
  }

  return (
    <Row gutter={16}>
      <Col span={6}>
        <Card className={styles.statCard}>
          <Statistic
            title={t('admin.totalUsers')}
            value={overview?.users?.total ?? 0}
            prefix={<UserOutlined />}
          />
        </Card>
      </Col>
      <Col span={6}>
        <Card className={styles.statCard}>
          <Statistic
            title={t('admin.totalTokens')}
            value={summary?.total_tokens ?? 0}
            prefix={<CloudServerOutlined />}
            precision={0}
          />
        </Card>
      </Col>
      <Col span={6}>
        <Card className={styles.statCard}>
          <Statistic
            title={t('admin.usedTokens')}
            value={summary?.used_tokens ?? 0}
            prefix={<ThunderboltOutlined />}
            precision={0}
          />
        </Card>
      </Col>
      <Col span={6}>
        <Card className={styles.statCard}>
          <Statistic
            title={t('admin.remainingTokens')}
            value={(summary?.total_tokens ?? 0) - (summary?.used_tokens ?? 0)}
            prefix={<TrophyOutlined />}
            precision={0}
          />
        </Card>
      </Col>
      <Col span={12} style={{ marginTop: 16 }}>
        <Card className={styles.statCard}>
          <Statistic
            title={t('nav.agents')}
            value={overview?.agents?.total ?? 0}
            suffix={`/ ${overview?.agents?.running ?? 0} running`}
            prefix={<UserOutlined />}
          />
        </Card>
      </Col>
    </Row>
  );
}

// ── Users Tab ─────────────────────────────────────────────────────────────

function UsersTab() {
  const { t } = useTranslation();
  const [users, setUsers] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [loading, setLoading] = useState(false);
  const [searchText, setSearchText] = useState('');
  const [registerModal, setRegisterModal] = useState(false);
  const [registerForm] = Form.useForm();
  const [editModal, setEditModal] = useState(false);
  const [editUser, setEditUser] = useState<any>(null);
  const [editForm] = Form.useForm();

  // Permission overrides state
  const [roleConfigs, setRoleConfigs] = useState<Record<string, any>>({});
  const [configModules, setConfigModules] = useState<Record<string, any>>({});
  const [registerOverrides, setRegisterOverrides] = useState<Record<string, Record<string, boolean>>>({});
  const [editOverrides, setEditOverrides] = useState<Record<string, Record<string, boolean>>>({});
  const [registerRole, setRegisterRole] = useState('user');
  const [editRoleVal, setEditRoleVal] = useState('user');

  const loadUsers = async () => {
    setLoading(true);
    try {
      const res: any = await listUsers(page, pageSize, searchText);
      setUsers(res.users || []);
      setTotal(res.total || 0);
    } catch {
      message.error(t('admin.loadUsersFailed'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadUsers(); loadRoleConfigs(); }, [page, pageSize]);

  const loadRoleConfigs = async () => {
    try {
      const cfg = await permissionsApi.getPermissionsConfig();
      setRoleConfigs(cfg.config?.roles || {});
      setConfigModules(cfg.config?.modules || {});
    } catch {}
  };

  // Get default matrix for a role
  const getRoleMatrix = (role: string): Record<string, Record<string, boolean>> => {
    return roleConfigs[role]?.modules || {};
  };

  // Compute diff: only keep overrides that differ from role defaults
  const computeOverrides = (role: string, overrides: Record<string, Record<string, boolean>>): Record<string, Record<string, boolean>> | null => {
    const base = getRoleMatrix(role);
    const diff: Record<string, Record<string, boolean>> = {};
    let hasDiff = false;
    for (const [mod, ops] of Object.entries(overrides)) {
      const modDiff: Record<string, boolean> = {};
      for (const [op, val] of Object.entries(ops)) {
        const baseVal = base[mod]?.[op];
        if (val !== baseVal) {
          modDiff[op] = val;
          hasDiff = true;
        }
      }
      if (Object.keys(modDiff).length > 0) diff[mod] = modDiff;
    }
    return hasDiff ? diff : null;
  };

  const handleSearch = (val: string) => {
    setSearchText(val);
    setPage(1);
  };

  useEffect(() => {
    if (searchText) loadUsers();
  }, [searchText]);

  const handleOpenRegister = () => {
    const defaultRole = 'user';
    setRegisterRole(defaultRole);
    setRegisterOverrides(getRoleMatrix(defaultRole));
    registerForm.resetFields();
    registerForm.setFieldsValue({ role: defaultRole });
    setRegisterModal(true);
  };

  const handleRegister = async () => {
    try {
      const values = await registerForm.validateFields();
      const overrides = computeOverrides(values.role, registerOverrides);
      if (overrides) values.permission_overrides = overrides;
      await createUser(values);
      message.success(t('admin.userRegistered'));
      setRegisterModal(false);
      registerForm.resetFields();
      setRegisterOverrides({});
      loadUsers();
    } catch (e: any) {
      message.error(e?.message || t('admin.registerFailed'));
    }
  };

  const handleEdit = async (u: any) => {
    setEditUser(u);
    editForm.setFieldsValue({
      display_name: u.display_name || '',
      role: u.role || 'user',
      is_active: u.is_active ?? true,
    });
    setEditRoleVal(u.role || 'user');
    // Load existing overrides from API, merge with role defaults for full display
    const roleDefaults = getRoleMatrix(u.role || 'user');
    try {
      const res: any = await permissionsApi.getUserOverrides(u.username);
      const stored = res.overrides || {};
      // Merge: start from role defaults, then apply user-specific overrides
      const merged: Record<string, Record<string, boolean>> = {};
      for (const mod of Object.keys(roleDefaults)) {
        merged[mod] = { ...roleDefaults[mod], ...(stored[mod] || {}) };
      }
      setEditOverrides(merged);
    } catch {
      setEditOverrides(roleDefaults);
    }
    setEditModal(true);
  };

  const handleSaveEdit = async () => {
    try {
      const values = await editForm.validateFields();
      const overrides = computeOverrides(editRoleVal, editOverrides);
      // Send null when no changes — backend skips update if None
      // Send {} to explicitly clear all overrides
      // Send non-empty dict to set specific overrides
      values.permission_overrides = overrides;
      await updateUser(editUser.id, values);
      message.success(t('admin.userUpdated'));
      setEditModal(false);
      loadUsers();
    } catch {
      message.error(t('admin.updateFailed'));
    }
  };

  const handleDisable = (u: any) => {
    Modal.confirm({
      title: t('admin.confirmDisable'),
      content: t('admin.confirmDisableDesc', { username: u.username }),
      onOk: async () => {
        try {
          await disableUser(u.id);
          message.success(t('admin.userDisabled'));
          loadUsers();
        } catch (e: any) {
          message.error(e?.message || t('admin.disableFailed'));
        }
      },
    });
  };

  const handleEnable = (u: any) => {
    Modal.confirm({
      title: t('admin.confirmEnable'),
      content: t('admin.confirmEnableDesc', { username: u.username }),
      onOk: async () => {
        try {
          await updateUser(u.id, { is_active: true });
          message.success(t('admin.userEnabled'));
          loadUsers();
        } catch (e: any) {
          message.error(e?.message || t('admin.enableFailed'));
        }
      },
    });
  };

  const handleDelete = (u: any) => {
    Modal.confirm({
      title: t('admin.confirmDelete'),
      content: (
        <div>
          <p>{t('admin.confirmDeleteDesc', { username: u.username })}</p>
          <Alert
            type="warning"
            message={t('admin.deleteWarning')}
            description={t('admin.deleteWarningDesc')}
            style={{ marginTop: 8 }}
          />
          <div style={{ marginTop: 8 }}>
            <Checkbox>{t('admin.backupBeforeDelete')}</Checkbox>
          </div>
        </div>
      ),
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await deleteUser(u.id, { backup: true });
          message.success(t('admin.userDeleted'));
          loadUsers();
        } catch (e: any) {
          message.error(e?.message || t('admin.deleteFailed'));
        }
      },
    });
  };

  const roleColors: Record<string, string> = {
    admin: 'orange',
    superadmin: 'red',
  };

  const columns = [
    {
      title: t('usersystem.username'),
      dataIndex: 'username',
      key: 'username',
      render: (text: string) => <strong>{text}</strong>,
    },
    {
      title: t('usersystem.display_name'),
      dataIndex: 'display_name',
      key: 'display_name',
    },
    {
      title: t('usersystem.role'),
      dataIndex: 'role',
      key: 'role',
      render: (role: string) => (
        <Tag color={roleColors[role] || 'default'}>{role}</Tag>
      ),
    },
    {
      title: t('usersystem.level'),
      dataIndex: 'level',
      key: 'level',
      render: (level: number) => <span>L{level}</span>,
    },
    {
      title: t('usersystem.points'),
      dataIndex: 'points',
      key: 'points',
      render: (pts: number) => <><ThunderboltOutlined /> {pts}</>,
    },
    {
      title: t('usersystem.status'),
      dataIndex: 'is_active',
      key: 'is_active',
      render: (active: boolean) => (
        <Tag color={active ? 'success' : 'error'}>
          {active ? t('common.enabled') : t('common.disabled')}
        </Tag>
      ),
    },
    {
      title: t('common.actions'),
      key: 'actions',
      render: (_: any, record: any) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => handleEdit(record)}>
            {t('common.edit')}
          </Button>
          {record.is_active ? (
            <Button
              size="small"
              icon={<StopOutlined />}
              onClick={() => handleDisable(record)}
            >
              {t('common.disable')}
            </Button>
          ) : (
            <Button
              size="small"
              icon={<PlayCircleOutlined />}
              onClick={() => handleEnable(record)}
            >
              {t('common.enable')}
            </Button>
          )}
          <Button
            size="small"
            danger
            icon={<DeleteOutlined />}
            onClick={() => handleDelete(record)}
          >
            {t('common.delete')}
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col flex="auto">
          <Search
            placeholder={t('admin.searchUsers')}
            allowClear
            enterButton={<SearchOutlined />}
            onSearch={handleSearch}
            style={{ maxWidth: 400 }}
          />
        </Col>
        <Col>
          <Space>
            <Button icon={<ReloadOutlined />} onClick={loadUsers} />
            <Button type="primary" icon={<PlusOutlined />} onClick={handleOpenRegister}>
              {t('admin.addUser')}
            </Button>
          </Space>
        </Col>
      </Row>

      <Table
        columns={columns}
        dataSource={users}
        rowKey="username"
        loading={loading}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (totalCount) => `${t('common.total', { count: totalCount })}`,
          onChange: (p, ps) => { setPage(p); setPageSize(ps); },
        }}
      />

      {/* Register Modal */}
      <Modal
        title={t('admin.registerUser')}
        open={registerModal}
        width={900}
        onCancel={() => { setRegisterModal(false); registerForm.resetFields(); setRegisterOverrides({}); setRegisterRole('user'); }}
        onOk={handleRegister}
        styles={{ body: { display: 'flex', gap: 24, maxHeight: 'calc(100vh - 200px)', overflow: 'auto' } }}
      >
        {/* 左栏：基本信息 */}
        <div style={{ flex: '0 0 280px' }}>
          <Form form={registerForm} layout="vertical" size="small">
            <Form.Item name="username" label={t('usersystem.username')} rules={[{ required: true }]}>
              <Input />
            </Form.Item>
            <Form.Item name="password" label={t('usersystem.password')} rules={[{ required: true, min: 6 }]}>
              <Input.Password />
            </Form.Item>
            <Form.Item name="display_name" label={t('usersystem.display_name')}>
              <Input />
            </Form.Item>
            <Form.Item name="role" label={t('usersystem.role')} rules={[{ required: true }]} initialValue="user">
              <Select
                options={[
                  { label: t('header.profile.roleUser'), value: 'user' },
                  { label: t('header.profile.roleAdmin'), value: 'admin' },
                ]}
                onChange={(v: string) => { setRegisterRole(v); setRegisterOverrides(getRoleMatrix(v)); }}
              />
            </Form.Item>
          </Form>
        </div>
        {/* 右栏：权限覆盖矩阵 */}
        <div style={{ flex: 1, minWidth: 0, borderLeft: '1px solid #f0f0f0', paddingLeft: 24, maxHeight: "calc(100vh - 200px)", overflowY: "auto" }}>
          <div style={{ marginBottom: 8, fontWeight: 500, fontSize: 13, color: '#666' }}>
            {t('admin.permissionOverride', '权限覆盖')}
          </div>
          {registerRole && roleConfigs[registerRole] && (
            <PermissionOverrideMatrix
              baseMatrix={getRoleMatrix(registerRole)}
              overrides={registerOverrides}
              onChange={setRegisterOverrides}
              configModules={configModules}
            />
          )}
        </div>
      </Modal>

      {/* Edit Modal */}
      <Modal
        title={t('admin.editUser')}
        open={editModal}
        width={900}
        onCancel={() => setEditModal(false)}
        onOk={handleSaveEdit}
        styles={{ body: { display: 'flex', gap: 24, maxHeight: 'calc(100vh - 200px)', overflow: 'auto' } }}
      >
        {/* 左栏：基本信息 */}
        <div style={{ flex: '0 0 280px' }}>
          <Form form={editForm} layout="vertical" size="small">
            <Form.Item name="display_name" label={t('usersystem.display_name')}>
              <Input />
            </Form.Item>
            <Form.Item name="role" label={t('usersystem.role')}>
              <Select
                options={[
                  { label: t('header.profile.roleUser'), value: 'user' },
                  { label: t('header.profile.roleAdmin'), value: 'admin' },
                ]}
                onChange={(v: string) => {
                  setEditRoleVal(v);
                  setEditOverrides(getRoleMatrix(v));
                }}
              />
            </Form.Item>
            <Form.Item name="is_active" valuePropName="checked" label={t('usersystem.status')}>
              <Switch />
            </Form.Item>
          </Form>
        </div>
        {/* 右栏：权限覆盖矩阵 */}
        <div style={{ flex: 1, minWidth: 0, borderLeft: '1px solid #f0f0f0', paddingLeft: 24, maxHeight: "calc(100vh - 200px)", overflowY: "auto" }}>
          <div style={{ marginBottom: 8, fontWeight: 500, fontSize: 13, color: '#666' }}>
            {t('admin.permissionOverride', '权限覆盖')}
          </div>
          {editRoleVal && roleConfigs[editRoleVal] && (
            <PermissionOverrideMatrix
              baseMatrix={getRoleMatrix(editRoleVal)}
              overrides={editOverrides}
              onChange={setEditOverrides}
              configModules={configModules}
            />
          )}
        </div>
      </Modal>
    </div>
  );
}

// ── Audit Tab ─────────────────────────────────────────────────────────────

function AuditTab() {
  const { t } = useTranslation();
  const [logs, setLogs] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);

  const loadLogs = async () => {
    setLoading(true);
    try {
      const res: any = await getAuditLogs(page, 50);
      setLogs(res.logs || []);
      setTotal(res.total || 0);
    } catch {
      // Audit may not have data yet
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadLogs(); }, [page]);

  return (
    <Card loading={loading} extra={<Button icon={<ReloadOutlined />} onClick={loadLogs} />}>
      <Table
        columns={[
          { title: t('admin.time'), dataIndex: 'created_at', key: 'created_at',
            render: (ts: number) => ts ? new Date(ts * 1000).toLocaleString() : '-' },
          { title: t('usersystem.username'), dataIndex: 'username', key: 'username' },
          { title: t('admin.action'), dataIndex: 'action', key: 'action' },
          { title: t('admin.details'), dataIndex: 'details', key: 'details',
            render: (d: any) => typeof d === 'string' ? d : JSON.stringify(d || {}) },
        ]}
        dataSource={logs}
        rowKey="id"
        pagination={{ current: page, total, onChange: setPage }}
      />
    </Card>
  );
}

// ── Config Tab ────────────────────────────────────────────────────────────

function ConfigTab() {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(true);
  const [config, setConfig] = useState<any>(null);

  useEffect(() => {
    Promise.all([
      getUsersConfig().catch(() => ({})),
    ]).then(([cfg]) => {
      setConfig(cfg);
      setLoading(false);
    });
  }, []);

  return (
    <Spin spinning={loading}>
      <Row gutter={24}>
        <Col span={12}>
          <Card title={t('admin.systemConfig')} bordered={false}>
            <Descriptions column={1} bordered size="small">
              <Descriptions.Item label={t('admin.authEnabled')}>
                <Tag color={config?.enabled ? 'success' : 'default'}>
                  {config?.enabled ? t('common.enabled') : t('common.disabled')}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label={t('admin.userSystemEnabled')}>
                <Tag color={config?.enabled ? 'success' : 'default'}>
                  {config?.enabled ? t('common.enabled') : t('common.disabled')}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label={t('admin.totalUsers')}>
                {config?.total_users ?? '-'}
              </Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>
      </Row>
    </Spin>
  );
}

// ── Permissions Tab ───────────────────────────────────────────────────────

function PermissionsTab() {
  const { t } = useTranslation();
  const [activeSubTab, setActiveSubTab] = useState('roles');
  const [loading, setLoading] = useState(false);
  const [config, setConfig] = useState<any>(null);
  const [selectedRole, setSelectedRole] = useState('user');

  // Edit state
  const [editRole, setEditRole] = useState<string | null>(null);
  const [editModules, setEditModules] = useState<any>({});
  const [editWhitelist, setEditWhitelist] = useState<string>('');
  const [editBlacklist, setEditBlacklist] = useState<string>('');
  const [editDangerous, setEditDangerous] = useState<string>('');

  useEffect(() => {
    loadConfig();
  }, []);

  const loadConfig = async () => {
    setLoading(true);
    try {
      const res: any = await permissionsApi.getPermissionsConfig();
      setConfig(res.config);
    } catch (e: any) {
      message.error(t('admin.permissionsLoadFailed', { error: e.message }));
    } finally {
      setLoading(false);
    }
  };

  const handleSaveRole = async () => {
    if (!editRole) return;
    setLoading(true);
    try {
      // editModules is now a CRUD matrix object for matrix mode
      await permissionsApi.updateRoleConfig(editRole, editModules);
      message.success(t('admin.roleUpdated'));
      setEditRole(null);
      loadConfig();
    } catch (e: any) {
      message.error(e.message);
    } finally {
      setLoading(false);
    }
  };

  const handleSaveShell = async () => {
    if (!selectedRole) return;
    setLoading(true);
    try {
      const whitelist = editWhitelist.split('\n').filter(l => l.trim());
      const blacklist = editBlacklist.split('\n').filter(l => l.trim());
      const dangerous = editDangerous.split('\n').filter(l => l.trim());
      await permissionsApi.updateShellPermissions(
        selectedRole, whitelist, blacklist, dangerous
      );
      message.success(t('admin.shellPermissionsUpdated'));
      loadConfig();
    } catch (e: any) {
      message.error(e.message);
    } finally {
      setLoading(false);
    }
  };

  const handleReload = async () => {
    setLoading(true);
    try {
      await permissionsApi.reloadPermissions();
      message.success(t('admin.permissionsReloaded'));
      loadConfig();
    } catch (e: any) {
      message.error(e.message);
    } finally {
      setLoading(false);
    }
  };

  const roles = config?.roles || {};
  const shellPerms = config?.shell_permissions?.roles || {};
  const moduleDefs = config?.modules || {};

  const subTabItems = [
    {
      key: 'roles',
      label: t('admin.roleManagement'),
      children: <RolesSubTab
        roles={roles}
        moduleDefs={moduleDefs}
        onEdit={(role: string) => {
          const r = roles[role];
          setEditRole(role);
          const mods = r?.modules;
          // v2.0: modules is CRUD matrix object; v1 fallback: string array
          if (mods && typeof mods === 'object' && !Array.isArray(mods) && mods !== '*') {
            setEditModules(mods);
          } else {
            setEditModules({});
          }
        }}
        editRole={editRole}
        editModules={editModules}
        setEditModules={setEditModules}
        onSave={handleSaveRole}
        onCancel={() => setEditRole(null)}
        loading={loading}
      />,
    },
    {
      key: 'shell',
      label: t('admin.shellPermissions'),
      children: <ShellSubTab
        roles={Object.keys(shellPerms)}
        selectedRole={selectedRole}
        setSelectedRole={setSelectedRole}
        whitelist={editWhitelist}
        blacklist={editBlacklist}
        dangerous={editDangerous}
        setWhitelist={setEditWhitelist}
        setBlacklist={setEditBlacklist}
        setDangerous={setEditDangerous}
        onSave={handleSaveShell}
        shellPerms={shellPerms}
        loading={loading}
      />,
    },
    {
      key: 'audit',
      label: t('admin.auditLogs'),
      children: <AuditSubTab loading={loading} />,
    },
  ];

  return (
    <div>
      <Row justify="end" style={{ marginBottom: 16 }}>
        <Button icon={<ReloadOutlined />} onClick={handleReload} loading={loading}>
          {t('admin.reloadPermissions')}
        </Button>
      </Row>
      <Tabs activeKey={activeSubTab} onChange={setActiveSubTab} type="card" items={subTabItems} />
    </div>
  );
}

// ── Permission Override Matrix (inline in user create/edit) ────────────────

function PermissionOverrideMatrix({
  baseMatrix,
  overrides,
  onChange,
  configModules,
}: {
  baseMatrix: Record<string, Record<string, boolean>>;
  overrides: Record<string, Record<string, boolean>>;
  onChange: (o: Record<string, Record<string, boolean>>) => void;
  configModules?: Record<string, any>;
}) {
  const moduleDefs = useMemo(() => {
    // 优先使用 config.modules（有 name、icon、operations）
    if (configModules && Object.keys(configModules).length > 0) {
      return configModules;
    }
    // fallback: 从 baseMatrix 推断
    const defs: Record<string, any> = {};
    for (const k of Object.keys(baseMatrix)) {
      defs[k] = { name: k };
    }
    return defs;
  }, [baseMatrix, configModules]);

  const diffCount = useMemo(() => {
    let count = 0;
    for (const mod of Object.keys(baseMatrix)) {
      for (const op of CRUD_OPS) {
        if (overrides[mod]?.[op] !== baseMatrix[mod]?.[op]) count++;
      }
    }
    return count;
  }, [baseMatrix, overrides]);

  return (
    <div style={{ marginTop: 16, border: '1px solid #f0f0f0', borderRadius: 8, padding: '8px 12px' }}>
      <PermissionMatrix
        moduleDefs={moduleDefs}
        value={overrides}
        onChange={onChange}
        baseMatrix={baseMatrix}
        showReset
        onReset={() => onChange(baseMatrix)}
        diffCount={diffCount}
      />
    </div>
  );
}

// ── Roles Sub-Tab ─────────────────────────────────────────────────────────

function RolesSubTab({
  roles, moduleDefs, onEdit,
  editRole, editModules,
  setEditModules, onSave, onCancel, loading,
}: any) {
  const { t } = useTranslation();

  // editModules is now the CRUD matrix object
  const matrix = editModules && typeof editModules === 'object' && !Array.isArray(editModules)
    ? editModules
    : {};

  return (
    <div>
      <Table
        columns={[
          {
            title: t('usersystem.role'),
            dataIndex: 'role',
            key: 'role',
            render: (role: string) => (
              <Tag color={role === 'admin' ? 'red' : 'default'}>
                {roles[role]?.name || role}
              </Tag>
            ),
          },
          {
            title: t('admin.modules'),
            key: 'modules',
            render: (_: any, record: any) => {
              const mods = record.modules;
              if (mods === '*') return <Tag color="red">{t('admin.allModules', '全部模块')}</Tag>;
              if (typeof mods === 'object' && !Array.isArray(mods)) {
                const enabled = Object.entries(mods).filter(([_, v]: [string, any]) => v && typeof v === 'object' && v.read);
                return (
                  <Space wrap size={4}>
                    {enabled.map(([k]: [string, any]) => (
                      <Tag key={k} color="cyan">{moduleDefs[k]?.icon} {moduleDefs[k]?.name || k}</Tag>
                    ))}
                    {enabled.length === 0 && <span style={{ color: '#999' }}>-</span>}
                  </Space>
                );
              }
              if (Array.isArray(mods)) {
                return (
                  <Space wrap size={4}>
                    {mods.map((m: string) => (
                      <Tag key={m} color="cyan">{moduleDefs[m]?.icon} {moduleDefs[m]?.name || m}</Tag>
                    ))}
                  </Space>
                );
              }
              return '-';
            },
          },
          {
            title: t('common.actions'),
            key: 'actions',
            render: (_: any, record: any) => {
              if (record.role === 'admin') {
                return <Tag color="red">{t('admin.locked', '系统内置')}</Tag>;
              }
              return (
                <Button size="small" icon={<EditOutlined />} onClick={() => onEdit(record.role)}>
                  {t('admin.editPermissions', '编辑权限')}
                </Button>
              );
            },
          },
        ]}
        dataSource={Object.entries(roles).map(([key, val]: [string, any]) => ({
          role: key,
          ...val,
        }))}
        rowKey="role"
        pagination={false}
      />

      {/* CRUD Matrix Edit Modal */}
      <Modal
        title={t('admin.editRolePermissions', { role: editRole, defaultValue: '' }).replace(/[\s:：]$/, '') || `${t('admin.editPermissions', '编辑权限')} — ${editRole}`}
        open={!!editRole}
        onOk={onSave}
        onCancel={onCancel}
        confirmLoading={loading}
        width={700}
        okText={t('common.save', '保存')}
        cancelText={t('common.cancel', '取消')}
      >
        {editRole === 'admin' ? (
          <div style={{ padding: 24, textAlign: 'center', color: '#999' }}>
            {t('admin.adminLocked', '管理员角色拥有所有权限，不可修改')}
          </div>
        ) : (
          <>
            <p style={{ marginBottom: 12, color: '#666', fontSize: 13 }}>
              {t('admin.matrixHint', '勾选每个模块允许的操作。模块名称前的复选框可全选/取消。')}
            </p>
            <PermissionMatrix
              moduleDefs={moduleDefs}
              value={matrix}
              onChange={setEditModules}
              size="small"
              bordered
            />
          </>
        )}
      </Modal>
    </div>
  );
}

// ── Shell Sub-Tab ─────────────────────────────────────────────────────────

function ShellSubTab({
  roles, selectedRole, setSelectedRole,
  whitelist, blacklist, dangerous,
  setWhitelist, setBlacklist, setDangerous,
  onSave, shellPerms, loading,
}: any) {
  const { t } = useTranslation();

  useEffect(() => {
    const perm = shellPerms[selectedRole];
    if (perm) {
      setWhitelist((perm.whitelist || []).join('\n'));
      setBlacklist((perm.blacklist || []).join('\n'));
      setDangerous((perm.dangerous_patterns || []).join('\n'));
    } else {
      setWhitelist('');
      setBlacklist('');
      setDangerous('');
    }
  }, [selectedRole, shellPerms]);

  return (
    <div>
      <Row gutter={24}>
        <Col span={8}>
          <Card title={t('admin.selectRole')} size="small" style={{ marginBottom: 16 }}>
            <Select
              value={selectedRole}
              onChange={setSelectedRole}
              style={{ width: '100%' }}
              options={roles.map((r: string) => ({ label: r, value: r }))}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Button type="primary" onClick={onSave} loading={loading} block>
            {t('common.save')}
          </Button>
        </Col>
      </Row>

      <Row gutter={16}>
        <Col span={8}>
          <Card title={t('admin.whitelist')} size="small">
            <Input.TextArea
              rows={12}
              value={whitelist}
              onChange={(e) => setWhitelist(e.target.value)}
              placeholder={t('admin.whitelistPlaceholder')}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card title={t('admin.blacklist')} size="small">
            <Input.TextArea
              rows={12}
              value={blacklist}
              onChange={(e) => setBlacklist(e.target.value)}
              placeholder={t('admin.blacklistPlaceholder')}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card title={t('admin.dangerousPatterns')} size="small">
            <Input.TextArea
              rows={12}
              value={dangerous}
              onChange={(e) => setDangerous(e.target.value)}
              placeholder={t('admin.dangerousPatternsPlaceholder')}
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
}

// ── Audit Sub-Tab ─────────────────────────────────────────────────────────

function AuditSubTab({ loading: _ }: { loading: boolean }) {
  const { t } = useTranslation();
  const [logs, setLogs] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState({ username: '', role: '', result: '' });

  const loadLogs = async () => {
    setLoading(true);
    try {
      const res: any = await permissionsApi.getAuditLogs({
        username: filters.username || undefined,
        role: filters.role || undefined,
        result: filters.result || undefined,
        limit: 50,
        offset: (page - 1) * 50,
      });
      setLogs(res.logs || []);
      setTotal(res.total || 0);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadLogs(); }, [page, filters]);

  const handleExport = () => {
    const blob = new Blob([JSON.stringify(logs, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `audit-logs-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Card
      loading={loading}
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={loadLogs} />
          <Button onClick={handleExport}>{t('admin.export')}</Button>
        </Space>
      }
    >
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Input
            placeholder={t('usersystem.username')}
            value={filters.username}
            onChange={(e) => { setFilters({ ...filters, username: e.target.value }); setPage(1); }}
            allowClear
          />
        </Col>
        <Col span={6}>
          <Select
            placeholder={t('usersystem.role')}
            value={filters.role || undefined}
            onChange={(v) => { setFilters({ ...filters, role: v || '' }); setPage(1); }}
            allowClear
            style={{ width: '100%' }}
            options={[
              { label: 'visitor', value: 'visitor' },
              { label: 'user', value: 'user' },
              { label: 'admin', value: 'admin' },
            ]}
          />
        </Col>
        <Col span={6}>
          <Select
            placeholder={t('admin.result')}
            value={filters.result || undefined}
            onChange={(v) => { setFilters({ ...filters, result: v || '' }); setPage(1); }}
            allowClear
            style={{ width: '100%' }}
            options={[
              { label: t('admin.allowed'), value: 'allowed' },
              { label: t('admin.denied'), value: 'denied' },
            ]}
          />
        </Col>
      </Row>

      <Table
        columns={[
          {
            title: t('admin.time'),
            dataIndex: 'timestamp',
            key: 'timestamp',
            render: (ts: number) => ts ? new Date(ts * 1000).toLocaleString() : '-',
          },
          { title: t('usersystem.username'), dataIndex: 'username', key: 'username' },
          { title: t('usersystem.role'), dataIndex: 'user_role', key: 'user_role' },
          { title: t('admin.eventType'), dataIndex: 'event_type', key: 'event_type' },
          { title: t('admin.tool'), dataIndex: 'tool_name', key: 'tool_name' },
          {
            title: t('admin.target'),
            dataIndex: 'target_path',
            key: 'target_path',
            render: (v: string) => v || '-',
          },
          {
            title: t('admin.result'),
            dataIndex: 'result',
            key: 'result',
            render: (v: string) => (
              <Tag color={v === 'allowed' ? 'success' : 'error'}>
                {v === 'allowed' ? t('admin.allowed') : t('admin.denied')}
              </Tag>
            ),
          },
          {
            title: t('admin.reason'),
            dataIndex: 'reason',
            key: 'reason',
            render: (v: string) => v || '-',
          },
        ]}
        dataSource={logs}
        rowKey="event_id"
        pagination={{
          current: page,
          total,
          pageSize: 50,
          onChange: setPage,
          showTotal: (totalCount: number) => t('common.total', { count: totalCount }),
        }}
      />
    </Card>
  );
}
