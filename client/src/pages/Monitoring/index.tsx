import { useState, useEffect } from "react";
import { Card, Row, Col, Statistic, Progress, Tag, Spin } from "antd";
import {
  ThunderboltOutlined,
  CloudServerOutlined,
  GoldOutlined,
  ClockCircleOutlined,
  LineChartOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import api from "@/api";
import styles from "./index.module.less";

interface SystemMetrics {
  cpu_percent: number;
  memory: { total: number; available: number; percent: number };
  disk: { total: number; free: number; percent: number };
  network: { recv_bytes: number; sent_bytes: number };
  uptime: number;
  api_stats: { total_requests: number; avg_response_time: number };
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
}

function formatUptime(seconds: number): string {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);

  if (days > 0) return `${days}d ${hours}h ${minutes}m`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

function MetricCard({
  title,
  icon,
  value,
  suffix,
  progress,
  color,
}: {
  title: string;
  icon: React.ReactNode;
  value: string | number;
  suffix?: string;
  progress?: number;
  color?: string;
}) {
  return (
    <Card className={styles.metricCard}>
      <Row align="middle" gutter={[16, 16]}>
        <Col>
          <div className={styles.metricIcon}>{icon}</div>
        </Col>
        <Col flex={1}>
          <div className={styles.metricTitle}>{title}</div>
          <Statistic
            value={value}
            suffix={suffix}
            className={styles.metricValue}
          />
          {progress !== undefined && (
            <Progress
              percent={progress}
              strokeColor={color}
              showInfo={false}
              className={styles.metricProgress}
            />
          )}
        </Col>
      </Row>
    </Card>
  );
}

function MonitoringPage() {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(true);
  const [metrics, setMetrics] = useState<SystemMetrics | null>(null);

  const fetchMetrics = async () => {
    try {
      // api.get() returns raw JSON directly (not wrapped in { data: ... })
      const [cpu, memory, disk, uptime, apiStats] = (await Promise.all([
        api.get("/monitor/cpu"),
        api.get("/monitor/memory"),
        api.get("/monitor/disk"),
        api.get("/monitor/uptime"),
        api.get("/monitor/api-stats"),
      ])) as any[];

      // Convert disk partitions array to flat { total, free, percent }
      // (take the root partition as primary metric)
      const diskPartitions = disk.partitions || [];
      const rootPartition = diskPartitions.find(
        (p: any) => p.mountpoint === "/" || p.mountpoint === "/app",
      ) || diskPartitions[0] || {};

      // uptime endpoint returns uptime_seconds, not uptime
      const uptimeSeconds = uptime.uptime_seconds ?? uptime.uptime ?? 0;
      setMetrics({
        cpu_percent: cpu.cpu_percent ?? cpu.percent ?? 0,
        memory: memory,
        disk: {
          total: rootPartition.total ?? 0,
          free: rootPartition.free ?? 0,
          percent: rootPartition.percent ?? 0,
        },
        network: { recv_bytes: 0, sent_bytes: 0 },
        uptime: uptimeSeconds,
        api_stats: apiStats,
      });
    } catch (error) {
      console.error("Failed to fetch metrics:", error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchMetrics();
    const interval = setInterval(fetchMetrics, 5000);
    return () => clearInterval(interval);
  }, []);

  if (loading || !metrics) {
    return (
      <div className={styles.container}>
        <Spin size="large" style={{ display: "block", margin: "100px auto" }} />
      </div>
    );
  }

  const getStatusColor = (percent: number) => {
    if (percent < 50) return "#52c41a";
    if (percent < 80) return "#faad14";
    return "#ff4d4f";
  };

  return (
    <div className={styles.container}>
      <PageHeader
        parent={t("nav.monitoring")}
        current={t("monitoring.title")}
        center={
          <Tag icon={<ClockCircleOutlined />} color="processing">
            {t("monitoring.autoRefresh")}
          </Tag>
        }
        subRow={t("monitoring.subtitle")}
      />

      <Row gutter={[24, 24]}>
        {/* CPU Usage */}
        <Col xs={24} sm={12} lg={6}>
          <MetricCard
            title={t("monitoring.cpu")}
            icon={<ThunderboltOutlined />}
            value={metrics.cpu_percent.toFixed(1)}
            suffix="%"
            progress={metrics.cpu_percent}
            color={getStatusColor(metrics.cpu_percent)}
          />
        </Col>

        {/* Memory Usage */}
        <Col xs={24} sm={12} lg={6}>
          <MetricCard
            title={t("monitoring.memory")}
            icon={<CloudServerOutlined />}
            value={formatBytes(metrics.memory.total - metrics.memory.available)}
            suffix={`/ ${formatBytes(metrics.memory.total)}`}
            progress={metrics.memory.percent}
            color={getStatusColor(metrics.memory.percent)}
          />
        </Col>

        {/* Disk Usage */}
        <Col xs={24} sm={12} lg={6}>
          <MetricCard
            title={t("monitoring.disk")}
            icon={<GoldOutlined />}
            value={formatBytes(metrics.disk.total - metrics.disk.free)}
            suffix={`/ ${formatBytes(metrics.disk.total)}`}
            progress={metrics.disk.percent}
            color={getStatusColor(metrics.disk.percent)}
          />
        </Col>

        {/* Uptime */}
        <Col xs={24} sm={12} lg={6}>
          <MetricCard
            title={t("monitoring.uptime")}
            icon={<ClockCircleOutlined />}
            value={formatUptime(metrics.uptime)}
          />
        </Col>

        {/* API Statistics */}
        <Col xs={24} sm={12}>
          <Card className={styles.apiCard}>
            <Row gutter={16}>
              <Col span={12}>
                <Statistic
                  title={t("monitoring.totalRequests")}
                  value={metrics.api_stats.total_requests}
                  prefix={<LineChartOutlined />}
                />
              </Col>
              <Col span={12}>
                <Statistic
                  title={t("monitoring.avgResponseTime")}
                  value={metrics.api_stats.avg_response_time}
                  suffix="ms"
                  precision={2}
                />
              </Col>
            </Row>
          </Card>
        </Col>

        {/* System Health */}
        <Col xs={24} sm={12}>
          <Card title={t("monitoring.systemHealth")} className={styles.healthCard}>
            <Row gutter={16}>
              <Col span={8}>
                <Tag color={getStatusColor(metrics.cpu_percent)}>
                  CPU: {metrics.cpu_percent.toFixed(1)}%
                </Tag>
              </Col>
              <Col span={8}>
                <Tag color={getStatusColor(metrics.memory.percent)}>
                  Memory: {metrics.memory.percent.toFixed(1)}%
                </Tag>
              </Col>
              <Col span={8}>
                <Tag color={getStatusColor(metrics.disk.percent)}>
                  Disk: {metrics.disk.percent.toFixed(1)}%
                </Tag>
              </Col>
            </Row>
          </Card>
        </Col>
      </Row>
    </div>
  );
}

export default MonitoringPage;
