import { Card, Descriptions, Tag } from "antd";
import ReactMarkdown from 'react-markdown';

export interface MessageDetail {
  id: string;
  title: string;
  content: string;
  channel: string;
  sender: string;
  priority: 'high' | 'medium' | 'low';
  created_at: string;
  updated_at?: string;
}

interface MessageDetailInfoProps {
  message: MessageDetail | null;
}

export default function MessageDetailInfo({ message }: MessageDetailInfoProps) {
  if (!message) return null;

  const priorityColorMap: Record<string, string> = {
    high: 'red',
    medium: 'orange',
    low: 'green'
  };

  return (
    <Card title="消息基本信息" style={{ marginBottom: 24 }}>
      <Descriptions column={1} bordered>
        <Descriptions.Item label="消息标题">{message.title}</Descriptions.Item>
        <Descriptions.Item label="来源渠道">
          <Tag color="blue">{message.channel}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="发送方/来源系统">{message.sender || '系统'}</Descriptions.Item>
        <Descriptions.Item label="优先级">
          <Tag color={priorityColorMap[message.priority] || 'default'}>
            {message.priority === 'high' ? '高优先' : message.priority === 'medium' ? '中优先' : '低优先'}
          </Tag>
        </Descriptions.Item>
        <Descriptions.Item label="接收时间">{new Date(message.created_at).toLocaleString()}</Descriptions.Item>
        {message.updated_at && (
          <Descriptions.Item label="更新时间">{new Date(message.updated_at).toLocaleString()}</Descriptions.Item>
        )}
      </Descriptions>

      <Card title="消息正文" style={{ marginTop: 16 }} size="small">
        <ReactMarkdown>{message.content}</ReactMarkdown>
      </Card>
    </Card>
  );
}
