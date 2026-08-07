import { Card, Button, Space, Modal, Input } from "antd";
import { ReadOutlined, PlayCircleOutlined, CheckSquareOutlined } from "@ant-design/icons";

export interface MessageActionPanelProps {
  messageId: string;
  status: 'unread' | 'read' | 'processing' | 'processed';
  onMarkRead?: () => void;
  onStartProcess?: () => void;
  onCompleteProcess?: (remark: string) => void;
}

export default function MessageActionPanel({
  status,
  onMarkRead,
  onStartProcess,
  onCompleteProcess,
}: MessageActionPanelProps) {
  const [modalVisible, setModalVisible] = useState(false);
  const [remark, setRemark] = useState("");

  const handleModalOk = () => {
    if (onCompleteProcess) {
      onCompleteProcess(remark);
    }
    setModalVisible(false);
    setRemark("");
  };

  return (
    <Card title="处理操作区" style={{ marginTop: 24 }}>
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        {status === 'unread' && (
          <Button 
            icon={<ReadOutlined />} 
            type="primary" 
            onClick={onMarkRead}
            block
          >
            标记为已读
          </Button>
        )}
        
        {(status === 'unread' || status === 'read') && (
          <Button 
            icon={<PlayCircleOutlined />} 
            type="default" 
            onClick={onStartProcess}
            block
          >
            开始处理
          </Button>
        )}

        {status === 'processing' && (
          <Button 
            icon={<CheckSquareOutlined />} 
            type="primary" 
            onClick={() => setModalVisible(true)}
            danger
            block
          >
            标记为已完成
          </Button>
        )}

        {/* Processing Status Display */}
        <div style={{ marginTop: 16, padding: 12, background: '#f5f5f5', borderRadius: 4 }}>
          <div style={{ fontWeight: 'bold', marginBottom: 8 }}>当前状态：</div>
          <span style={{ 
            color: status === 'unread' ? '#999' : 
                   status === 'read' ? '#1890ff' : 
                   status === 'processing' ? '#faad14' : '#52c41a',
            fontWeight: 500
          }}>
            {status === 'unread' ? '未读' : 
             status === 'read' ? '已读' : 
             status === 'processing' ? '处理中' : '已处理'}
          </span>
        </div>
      </Space>

      <Modal
        title="标记为已完成"
        open={modalVisible}
        onOk={handleModalOk}
        onCancel={() => {
          setModalVisible(false);
          setRemark("");
        }}
        okText="确认完成"
        cancelText="取消"
      >
        <p>请添加处理备注（可选）：</p>
        <Input.TextArea
          value={remark}
          onChange={(e) => setRemark(e.target.value)}
          placeholder="请输入处理结果或备注说明..."
          rows={4}
        />
      </Modal>
    </Card>
  );
}

// Add useState import
import { useState } from "react";
