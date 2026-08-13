/**
 * File Preview Card - Document/image/video preview and download card.
 */

import { Card, Button, Space, Typography, Tag } from 'antd';
import { FileText, Image as ImageIcon, Video, Download } from 'lucide-react';
import styles from './FilePreviewCard.module.less';

const { Text, Title } = Typography;

export interface FilePreviewCardProps {
  cardId: string;
  cardType: 'file_preview';
  title: string;
  fileName?: string;
  fileSize?: number;
  previewUrl?: string;
  fileType?: 'image' | 'pdf' | 'doc' | 'video' | 'other';
  actions?: Array<{ label: string; action: string; params?: Record<string, any>; type?: 'primary' | 'secondary' | 'danger' | 'success' }>;
  onAction?: (action: string, params?: Record<string, any>) => void;
}

function getFileIcon(type?: string) {
  switch (type) {
    case 'image': return <ImageIcon size={24} className={styles.fileIcon} />;
    case 'video': return <Video size={24} className={styles.fileIcon} />;
    case 'pdf':
    case 'doc': return <FileText size={24} className={styles.fileIcon} />;
    default: return <FileText size={24} className={styles.fileIcon} />;
  }
}

function formatFileSize(bytes?: number): string {
  if (!bytes) return '';
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
}

export function FilePreviewCard({
  title,
  fileName,
  fileSize,
  previewUrl,
  fileType = 'other',
  actions = [],
  onAction,
}: FilePreviewCardProps) {
  const handleDownload = () => {
    if (actions.length > 0 && onAction) {
      const downloadAction = actions.find(a => a.action === 'download') || actions[0];
      if (downloadAction) {
        onAction(downloadAction.action, downloadAction.params);
        return;
      }
    }
    if (previewUrl) {
      window.open(previewUrl, '_blank');
    }
  };

  return (
    <Card className={styles.filePreviewCard} bordered={false}>
      <div className={styles.header}>
        {getFileIcon(fileType)}
        <Title level={5} className={styles.title}>{title || fileName}</Title>
      </div>

      <div className={`${styles.fileInfo}`}>
        {fileName && (
          <Text code className={styles.fileName}>{fileName}</Text>
        )}
        {fileSize && (
          <Tag color="default" className={styles.fileSize}>{formatFileSize(fileSize)}</Tag>
        )}
      </div>

      <div className={styles.actions}>
        {actions.length > 0 ? (
          <Space size="small">
            {actions.map((action, index) => {
              const isPrimary = action.type === 'primary';
              const isDanger = action.type === 'danger';
              const btnType = isPrimary ? 'primary' : 'default';
              return (
                <Button
                  key={index}
                  type={btnType as any}
                  danger={isDanger}
                  size="small"
                  icon={action.action === 'download' || action.action === 'view' ? <Download size={14} /> : null}
                  onClick={() => onAction?.(action.action, action.params)}
                >
                  {action.label}
                </Button>
              );
            })}
          </Space>
        ) : (
          <Button
            type="primary"
            icon={<Download size={14} />}
            onClick={handleDownload}
            className={styles.primaryButton}
          >
            {previewUrl ? '查看/下载' : '下载'}
          </Button>
        )}
      </div>
    </Card>
  );
}

export default FilePreviewCard;
