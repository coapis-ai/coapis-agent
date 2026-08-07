import { Card, Statistic } from "antd";
import { InboxOutlined, ClockCircleOutlined, CheckCircleOutlined, ExclamationCircleOutlined } from "@ant-design/icons";

export interface MessageStats {
  total_messages: number;
  unread_messages: number;
  today_new_messages: number;
  processed_messages: number;
}

interface MessageStatisticsPanelProps {
  stats: MessageStats | null;
}

export default function MessageStatisticsPanel({ stats }: MessageStatisticsPanelProps) {
  return (
    <Card title="个人消息统计" style={{ marginBottom: 24 }}>
      <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
        <Statistic
          title="收到消息总数"
          value={stats?.total_messages || 0}
          prefix={<InboxOutlined />}
        />
        <Statistic
          title="待处理/未读消息数"
          value={stats?.unread_messages || 0}
          prefix={<ExclamationCircleOutlined style={{ color: "#ff4d4f" }} />}
          valueStyle={{ color: "#ff4d4f" }}
        />
        <Statistic
          title="今日新消息"
          value={stats?.today_new_messages || 0}
          prefix={<ClockCircleOutlined />}
        />
        <Statistic
          title="已处理消息数"
          value={stats?.processed_messages || 0}
          prefix={<CheckCircleOutlined style={{ color: "#52c41a" }} />}
          valueStyle={{ color: "#52c41a" }}
        />
      </div>
    </Card>
  );
}
