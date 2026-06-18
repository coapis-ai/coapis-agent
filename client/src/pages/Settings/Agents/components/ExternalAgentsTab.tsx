/**
 * ExternalAgentsTab — read-only list of external agents (admin only).
 * Migrated from Admin/ToolsTab. Added username column and filter.
 */
import { useEffect, useMemo, useState } from "react";
import { Card, Table, Tag, Select, Space, message, Typography } from "antd";
import { useTranslation } from "react-i18next";
import { adminApi } from "@/api/modules/admin";

const { Text } = Typography;

export default function ExternalAgentsTab() {
  const { t } = useTranslation();
  const [agents, setAgents] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [filterUser, setFilterUser] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const res: any = await adminApi.listExternalAgents();
        setAgents(res.agents || res || []);
      } catch (e: any) {
        message.error(e?.message || t("admin.externalAgentsLoadFailed", "加载外部智能体失败"));
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const userOptions = useMemo(() => {
    const users = [...new Set(agents.map((a) => a.username).filter(Boolean))];
    return users.map((u) => ({ label: u, value: u }));
  }, [agents]);

  const filtered = useMemo(
    () => (filterUser ? agents.filter((a) => a.username === filterUser) : agents),
    [agents, filterUser],
  );

  const columns = [
    {
      title: t("admin.agentId", "智能体 ID"),
      dataIndex: "id",
      key: "id",
      width: 200,
    },
    {
      title: t("admin.agentName", "名称"),
      dataIndex: "name",
      key: "name",
    },
    {
      title: t("admin.username", "所属用户"),
      dataIndex: "username",
      key: "username",
      width: 120,
      render: (u: string) => u || <Tag>-</Tag>,
    },
    {
      title: t("admin.workspace", "工作目录"),
      dataIndex: "workspace_dir",
      key: "workspace_dir",
      ellipsis: true,
    },
    {
      title: t("admin.status", "状态"),
      dataIndex: "enabled",
      key: "enabled",
      width: 100,
      render: (enabled: boolean) =>
        enabled ? (
          <Tag color="green">{t("admin.enabled", "启用")}</Tag>
        ) : (
          <Tag color="red">{t("admin.disabled", "禁用")}</Tag>
        ),
    },
  ];

  return (
    <Card>
      <Text type="secondary" style={{ display: "block", marginBottom: 16 }}>
        {t("admin.externalAgentsHint", "外部智能体为系统自动发现的智能体，仅可查看。")}
      </Text>
      {userOptions.length > 0 && (
        <Space style={{ marginBottom: 16 }}>
          <Text>{t("admin.filterByUser", "按用户筛选")}</Text>
          <Select
            allowClear
            placeholder={t("admin.allUsers", "全部用户")}
            options={userOptions}
            value={filterUser}
            onChange={setFilterUser}
            style={{ width: 200 }}
          />
        </Space>
      )}
      <Table
        dataSource={filtered}
        columns={columns}
        rowKey="id"
        loading={loading}
        pagination={{ pageSize: 20 }}
      />
    </Card>
  );
}
