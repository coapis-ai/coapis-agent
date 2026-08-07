import { Table, Tag, Button, Select, Input } from "antd";
import type { ColumnsType } from "antd/es/table";
import { SearchOutlined, FilterOutlined } from "@ant-design/icons";
import dayjs from "dayjs";

export interface MessageItem {
  id: string;
  title: string;
  content: string;
  channel: string;
  priority: 'high' | 'medium' | 'low';
  status: 'unread' | 'read' | 'processing' | 'processed';
  created_at: string;
}

interface MessageListTableProps {
  messages: MessageItem[];
  total: number;
  page: number;
  pageSize: number;
  loading?: boolean;
  onRowClick?: (messageId: string) => void;
  onPageChange?: (page: number, pageSize: number) => void;
}

export default function MessageListTable({
  messages,
  total,
  page,
  pageSize,
  loading = false,
  onRowClick,
  onPageChange,
}: MessageListTableProps) {
  
  const priorityColorMap: Record<string, string> = {
    high: 'red',
    medium: 'orange',
    low: 'green'
  };

  const statusLabelMap: Record<string, string> = {
    unread: '未读',
    read: '已读',
    processing: '处理中',
    processed: '已处理'
  };

  const statusColorMap: Record<string, string> = {
    unread: 'red',
    read: 'default',
    processing: 'blue',
    processed: 'green'
  };

  const columns: ColumnsType<MessageItem> = [
    {
      title: "标题/摘要",
      dataIndex: "title",
      key: "title",
      ellipsis: true,
      render: (text: string) => text || "无标题",
    },
    {
      title: "渠道",
      dataIndex: "channel",
      key: "channel",
      width: 100,
    },
    {
      title: "优先级",
      dataIndex: "priority",
      key: "priority",
      width: 80,
      render: (priority: string) => (
        <Tag color={priorityColorMap[priority] || 'default'}>
          {priority === 'high' ? '高' : priority === 'medium' ? '中' : '低'}
        </Tag>
      ),
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
      title: "接收时间",
      dataIndex: "created_at",
      key: "created_at",
      width: 160,
      render: (time: string) => dayjs(time).format('YYYY-MM-DD HH:mm'),
    }
  ];

  return (
    <div>
      {/* 筛选栏 */}
      <div style={{ marginBottom: 16, display: "flex", gap: 12, alignItems: "center" }}>
        <Select placeholder="状态筛选" style={{ width: 120 }} allowClear>
          <Select.Option value="unread">未读</Select.Option>
          <Select.Option value="read">已读</Select.Option>
          <Select.Option value="processing">处理中</Select.Option>
          <Select.Option value="processed">已处理</Select.Option>
        </Select>
        
        <Select placeholder="类型筛选" style={{ width: 120 }} allowClear>
          <Select.Option value="system_notification">系统通知</Select.Option>
          <Select.Option value="task_assignment">任务分配</Select.Option>
          <Select.Option value="approval_remind">审批提醒</Select.Option>
        </Select>

        <Input.Search
          placeholder="搜索标题/内容"
          prefix={<SearchOutlined />}
          style={{ width: 250 }}
        />
        
        <Button icon={<FilterOutlined />}>高级筛选</Button>
      </div>

      {/* 消息列表 */}
      <Table<MessageItem>
        columns={columns}
        dataSource={messages}
        loading={loading}
        rowKey="id"
        pagination={{
          current: page,
          pageSize: pageSize,
          total: total,
          showSizeChanger: true,
          showQuickJumper: true,
          onChange: onPageChange,
        }}
        onRow={(record) => ({
          onClick: () => onRowClick?.(record.id),
          style: { cursor: 'pointer' },
        })}
      />
    </div>
  );
}
