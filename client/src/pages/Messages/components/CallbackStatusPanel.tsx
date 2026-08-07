import { Card, Table, Tag, Button, Space } from "antd";
import type { ColumnsType } from "antd/es/table";

export interface CallbackRecord {
  id: string;
  target_url: string;
  event_type: string;
  status: 'pending' | 'success' | 'failed';
  retry_count: number;
  last_retry_at?: string;
  error_log?: string;
}

interface CallbackStatusPanelProps {
  callbacks: CallbackRecord[];
  onRetryCallback?: (callbackId: string) => void;
}

export default function CallbackStatusPanel({ 
  callbacks, 
  onRetryCallback 
}: CallbackStatusPanelProps) {
  
  const statusColorMap: Record<string, string> = {
    pending: 'orange',
    success: 'green',
    failed: 'red'
  };

  const statusLabelMap: Record<string, string> = {
    pending: '待回调',
    success: '已成功',
    failed: '已失败'
  };

  const columns: ColumnsType<CallbackRecord> = [
    {
      title: "事件类型",
      dataIndex: "event_type",
      key: "event_type",
      width: 120,
    },
    {
      title: "目标 URL",
      dataIndex: "target_url",
      key: "target_url",
      ellipsis: true,
      render: (url: string) => url || 'N/A',
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      width: 80,
      render: (status: string) => (
        <Tag color={statusColorMap[status] || 'default'}>
          {statusLabelMap[status] || status}
        </Tag>
      ),
    },
    {
      title: "重试次数",
      dataIndex: "retry_count",
      key: "retry_count",
      width: 80,
    },
    {
      title: "最后重试时间",
      dataIndex: "last_retry_at",
      key: "last_retry_at",
      width: 160,
      render: (time?: string) => time ? new Date(time).toLocaleString() : 'N/A',
    },
    {
      title: "操作",
      key: "action",
      width: 120,
      render: (_, record: CallbackRecord) => (
        <Space size="small">
          {record.status === 'failed' && onRetryCallback && (
            <Button 
              type="link" 
              size="small" 
              onClick={() => onRetryCallback?.(record.id)}
            >
              手动重试
            </Button>
          )}
        </Space>
      ),
    }
  ];

  return (
    <Card title="操作与同步面板 - 回调状态" style={{ marginTop: 24 }}>
      {callbacks.length === 0 ? (
        <div style={{ textAlign: 'center', color: '#999', padding: 24 }}>
          暂无回调记录
        </div>
      ) : (
        <Table<CallbackRecord>
          columns={columns}
          dataSource={callbacks}
          rowKey="id"
          pagination={{ pageSize: 5, showSizeChanger: false }}
        />
      )}
    </Card>
  );
}
