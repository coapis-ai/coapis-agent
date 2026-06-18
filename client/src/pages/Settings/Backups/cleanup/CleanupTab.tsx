/**
 * CleanupTab — storage overview + one-click cleanup + rules config + history.
 */
import { useCallback, useEffect, useState } from "react";
import {
  Button,
  Card,
  Col,
  InputNumber,
  Modal,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from "antd";
import {
  DeleteOutlined,
  DatabaseOutlined,
  CloudServerOutlined,
  HddOutlined,
  ReloadOutlined,
  SettingOutlined,
  ThunderboltOutlined,
  WarningOutlined,
} from "@ant-design/icons";

import api from "@/api";
import type {
  StorageOverview,
  CleanupRules,
  CleanupRunResponse,
  CleanupLogEntry,
} from "@/api/types/cleanup";

const { Text, Title } = Typography;

/** Friendly label for data type keys */
const TYPE_LABELS: Record<string, string> = {
  chat_messages: "聊天消息",
  sessions: "会话状态",
  dialog_logs: "对话日志",
  tool_results: "工具结果",
  browser_cache: "浏览器缓存",
  evolution: "进化数据",
};

/** Format bytes to human-readable */
function humanSize(bytes: number): string {
  if (bytes === 0) return "0B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return (bytes / Math.pow(1024, i)).toFixed(1) + units[i];
}

export default function CleanupTab() {
  const [loading, setLoading] = useState(false);
  const [overview, setOverview] = useState<StorageOverview | null>(null);
  const [rules, setRules] = useState<CleanupRules>({});
  const [history, setHistory] = useState<CleanupLogEntry[]>([]);
  const [runResult, setRunResult] = useState<CleanupRunResponse | null>(null);
  const [rulesOpen, setRulesOpen] = useState(false);
  const [running, setRunning] = useState(false);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [ov, rh, hist] = await Promise.all([
        api.getOverview(),
        api.getRules(),
        api.getHistory(20),
      ]);
      setOverview(ov);
      setRules(rh.rules);
      setHistory(hist.history);
    } catch {
      message.error("加载清理数据失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  const handleRunCleanup = async () => {
    Modal.confirm({
      title: "确认清理",
      icon: <WarningOutlined />,
      content: "将执行全量数据清理：归档旧消息、过期会话、压缩日志、清除缓存。操作可逆（数据归档到数据库）。",
      okText: "执行清理",
      cancelText: "取消",
      onOk: async () => {
        setRunning(true);
        try {
          const res = await api.runCleanup();
          setRunResult(res);
          message.success(`清理完成，处理 ${res.total_items_processed} 项，释放 ${humanSize(res.total_bytes_freed)}`);
          await fetchAll();
        } catch {
          message.error("清理执行失败");
        } finally {
          setRunning(false);
        }
      },
    });
  };

  const handleRunSingle = async (dataType: string) => {
    const label = TYPE_LABELS[dataType] || dataType;
    Modal.confirm({
      title: `确认清理「${label}」`,
      icon: <WarningOutlined />,
      content: `将清理${label}数据。此操作可逆（数据归档到数据库），但请确认确实需要清理。`,
      okText: "执行清理",
      cancelText: "取消",
      onOk: async () => {
        setRunning(true);
        try {
          await api.runSingle(dataType);
          message.success(`${label} 清理完成`);
          await fetchAll();
        } catch {
          message.error("清理失败");
        } finally {
          setRunning(false);
        }
      },
    });
  };

  const handleSaveRules = async () => {
    try {
      await api.updateRules(rules);
      message.success("清理规则已保存");
      setRulesOpen(false);
    } catch {
      message.error("保存失败");
    }
  };

  if (loading && !overview) {
    return <div style={{ padding: 40, textAlign: "center" }}>加载中...</div>;
  }

  // Storage breakdown percentages
  const total = overview?.total_bytes || 1;
  const hotPct = ((overview?.hot.bytes || 0) / total) * 100;
  const warmPct = ((overview?.warm.bytes || 0) / total) * 100;
  const coldPct = ((overview?.cold.bytes || 0) / total) * 100;
  const otherBytes = Object.values(overview?.other || {}).reduce(
    (sum, v) => (typeof v === "number" ? sum + v : sum), 0
  );
  const otherPct = (otherBytes / total) * 100;

  // History table columns
  const historyCols = [
    {
      title: "时间",
      dataIndex: "executed_at",
      key: "time",
      width: 180,
      render: (v: string) => new Date(v).toLocaleString("zh-CN"),
    },
    {
      title: "类型",
      dataIndex: "data_type",
      key: "type",
      width: 120,
      render: (v: string) => <Tag>{TYPE_LABELS[v] || v}</Tag>,
    },
    {
      title: "操作",
      dataIndex: "action",
      key: "action",
      width: 100,
    },
    {
      title: "处理数",
      dataIndex: "items_count",
      key: "count",
      width: 80,
    },
    {
      title: "释放空间",
      dataIndex: "bytes_freed",
      key: "freed",
      width: 100,
      render: (v: number) => humanSize(v),
    },
  ];

  return (
    <div style={{ padding: "0 4px" }}>
      {/* Storage Overview */}
      <Card
        title={
          <Space>
            <DatabaseOutlined />
            <span>存储概览</span>
            <Tooltip title="刷新">
              <Button
                type="text"
                icon={<ReloadOutlined />}
                size="small"
                onClick={fetchAll}
                loading={loading}
              />
            </Tooltip>
          </Space>
        }
        extra={
          <Space>
            <Button
              icon={<SettingOutlined />}
              onClick={() => setRulesOpen(true)}
            >
              清理规则
            </Button>
            <Button
              type="primary"
              danger
              icon={<DeleteOutlined />}
              loading={running}
              onClick={handleRunCleanup}
            >
              一键清理
            </Button>
          </Space>
        }
        style={{ marginBottom: 16 }}
      >
        <Row gutter={[16, 16]}>
          <Col span={6}>
            <Card size="small" style={{ background: "#fff7e6", borderColor: "#ffd591" }}>
              <Statistic
                title={<><ThunderboltOutlined /> 热数据 (JSON)</>}
                value={overview?.hot.human || "0"}
                valueStyle={{ color: "#d46b08" }}
              />
              <Text type="secondary" style={{ fontSize: 12 }}>
                聊天记录、活跃会话、MEMORY.md
              </Text>
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small" style={{ background: "#e6f7ff", borderColor: "#91d5ff" }}>
              <Statistic
                title={<><HddOutlined /> 温数据 (DB)</>}
                value={overview?.warm.human || "0"}
                valueStyle={{ color: "#1890ff" }}
              />
              <Text type="secondary" style={{ fontSize: 12 }}>
                归档消息、历史会话、压缩日志
              </Text>
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small" style={{ background: "#f6ffed", borderColor: "#b7eb8f" }}>
              <Statistic
                title={<><CloudServerOutlined /> 冷数据 (gzip)</>}
                value={overview?.cold.human || "0"}
                valueStyle={{ color: "#52c41a" }}
              />
              <Text type="secondary" style={{ fontSize: 12 }}>
                备份文件 (backups/*.tar.gz)
              </Text>
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small">
              <Statistic
                title="总占用"
                value={overview?.total_human || "0"}
                valueStyle={{ color: "#333" }}
              />
              <Text type="secondary" style={{ fontSize: 12 }}>
                工作空间: {overview?.workspace?.split("/").pop()}
              </Text>
            </Card>
          </Col>
        </Row>

        {/* Progress bar breakdown */}
        <div style={{ marginTop: 16 }}>
          <div style={{ display: "flex", gap: 2, height: 24, borderRadius: 4, overflow: "hidden" }}>
            <Tooltip title={`热数据 ${overview?.hot.human}`}>
              <div style={{ width: `${hotPct}%`, background: "#fa8c16", minWidth: hotPct > 0 ? 4 : 0 }} />
            </Tooltip>
            <Tooltip title={`温数据 ${overview?.warm.human}`}>
              <div style={{ width: `${warmPct}%`, background: "#1890ff", minWidth: warmPct > 0 ? 4 : 0 }} />
            </Tooltip>
            <Tooltip title={`冷数据 ${overview?.cold.human}`}>
              <div style={{ width: `${coldPct}%`, background: "#52c41a", minWidth: coldPct > 0 ? 4 : 0 }} />
            </Tooltip>
            <Tooltip title={`其他 ${humanSize(otherBytes)}`}>
              <div style={{ width: `${otherPct}%`, background: "#d9d9d9", minWidth: otherPct > 0 ? 4 : 0 }} />
            </Tooltip>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", marginTop: 4, fontSize: 12, color: "#999" }}>
            <span>🟠 热 {hotPct.toFixed(1)}%</span>
            <span>🔵 温 {warmPct.toFixed(1)}%</span>
            <span>🟢 冷 {coldPct.toFixed(1)}%</span>
            <span>⚪ 其他 {otherPct.toFixed(1)}%</span>
          </div>
        </div>

        {/* Quick cleanup buttons */}
        <div style={{ marginTop: 16 }}>
          <Title level={5}>单项清理</Title>
          <Space wrap>
            {Object.entries(TYPE_LABELS).map(([key, label]) => (
              <Button
                key={key}
                size="small"
                loading={running}
                onClick={() => handleRunSingle(key)}
              >
                {label}
              </Button>
            ))}
          </Space>
        </div>
      </Card>

      {/* Last run result */}
      {runResult && (
        <Card
          title="最近一次清理结果"
          size="small"
          style={{ marginBottom: 16 }}
          extra={
            <Button type="text" size="small" onClick={() => setRunResult(null)}>
              关闭
            </Button>
          }
        >
          <Row gutter={16}>
            {runResult.results.map((r) => (
              <Col span={4} key={r.data_type}>
                <Card size="small">
                  <Statistic
                    title={TYPE_LABELS[r.data_type] || r.data_type}
                    value={r.items_archived + r.items_deleted}
                    suffix="项"
                    valueStyle={{ fontSize: 20 }}
                  />
                  <Text type="secondary">{humanSize(r.bytes_freed)}</Text>
                </Card>
              </Col>
            ))}
          </Row>
        </Card>
      )}

      {/* Cleanup History */}
      <Card
        title={<><DatabaseOutlined /> 清理历史</>}
        size="small"
      >
        <Table
          dataSource={history}
          columns={historyCols}
          rowKey="id"
          size="small"
          pagination={{ pageSize: 10 }}
          locale={{ emptyText: "暂无清理记录" }}
        />
      </Card>

      {/* Rules Modal */}
      <Modal
        title="清理规则配置"
        open={rulesOpen}
        onCancel={() => setRulesOpen(false)}
        onOk={handleSaveRules}
        okText="保存"
        cancelText="取消"
        width={600}
      >
        <div style={{ maxHeight: 400, overflow: "auto" }}>
          {Object.entries(rules).map(([key, rule]) => (
            <Card key={key} size="small" title={TYPE_LABELS[key] || key} style={{ marginBottom: 8 }}>
              <Space>
                {rule.hot_limit !== undefined && (
                  <>
                    <Text>保留最近</Text>
                    <InputNumber
                      min={1}
                      max={1000}
                      value={rule.hot_limit}
                      onChange={(v) =>
                        setRules((prev) => ({
                          ...prev,
                          [key]: { ...prev[key], hot_limit: v ?? undefined },
                        }))
                      }
                    />
                    <Text>条消息</Text>
                  </>
                )}
                {rule.hot_days !== undefined && (
                  <>
                    <Text>热数据保留</Text>
                    <InputNumber
                      min={1}
                      max={365}
                      value={rule.hot_days}
                      onChange={(v) =>
                        setRules((prev) => ({
                          ...prev,
                          [key]: { ...prev[key], hot_days: v ?? undefined },
                        }))
                      }
                    />
                    <Text>天</Text>
                  </>
                )}
                <Text>归档保留</Text>
                <InputNumber
                  min={1}
                  max={365}
                  value={rule.warm_days}
                  onChange={(v) =>
                    setRules((prev) => ({
                      ...prev,
                      [key]: { ...prev[key], warm_days: v ?? prev[key].warm_days },
                    }))
                  }
                />
                <Text>天</Text>
              </Space>
            </Card>
          ))}
        </div>
      </Modal>
    </div>
  );
}
