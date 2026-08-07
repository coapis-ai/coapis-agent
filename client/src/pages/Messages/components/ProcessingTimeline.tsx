import { Timeline, Tag, Space } from "antd";
import { CheckCircleOutlined, ClockCircleOutlined, ReadOutlined, LoadingOutlined } from "@ant-design/icons";

export interface ProcessingRecord {
  id: string;
  status: 'unread' | 'read' | 'processing' | 'processed';
  operator: string;
  operated_at: string;
  remark?: string;
}

interface ProcessingTimelineProps {
  records: ProcessingRecord[];
}

export default function ProcessingTimeline({ records }: ProcessingTimelineProps) {
  const statusIconMap: Record<string, React.ReactNode> = {
    unread: <ReadOutlined style={{ color: '#999' }} />,
    read: <CheckCircleOutlined style={{ color: '#1890ff' }} />,
    processing: <LoadingOutlined style={{ color: '#faad14' }} />,
    processed: <CheckCircleOutlined style={{ color: '#52c41a' }} />
  };

  const statusLabelMap: Record<string, string> = {
    unread: '未读',
    read: '已读',
    processing: '处理中',
    processed: '已处理'
  };

  return (
    <Timeline mode="left" style={{ marginTop: 16 }}>
      {records.length === 0 ? (
        <Timeline.Item dot={<ClockCircleOutlined />}>暂无处理记录</Timeline.Item>
      ) : (
        records.map((record) => (
          <Timeline.Item 
            key={record.id}
            dot={statusIconMap[record.status]}
            color={
              record.status === 'unread' ? '#999' :
              record.status === 'read' ? '#1890ff' :
              record.status === 'processing' ? '#faad14' : '#52c41a'
            }
          >
            <Space direction="vertical" size={4} style={{ width: '100%' }}>
              <div>
                <Tag color={
                  record.status === 'unread' ? 'default' :
                  record.status === 'read' ? 'blue' :
                  record.status === 'processing' ? 'orange' : 'green'
                }>
                  {statusLabelMap[record.status]}
                </Tag>
                <span style={{ marginLeft: 8, color: '#666' }}>
                  {new Date(record.operated_at).toLocaleString()}
                </span>
              </div>
              <div>操作人：{record.operator || '系统/AI代理'}</div>
              {record.remark && (
                <div style={{ color: '#888', fontSize: 13, marginTop: 4 }}>
                  备注：{record.remark}
                </div>
              )}
            </Space>
          </Timeline.Item>
        ))
      )}
    </Timeline>
  );
}
