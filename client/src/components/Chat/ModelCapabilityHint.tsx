import { Space } from 'antd';
import { 
  CheckCircleOutlined, 
  WarningOutlined,
  InfoCircleOutlined,
  EyeOutlined,
  VideoCameraOutlined 
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import styles from './ModelCapabilityHint.module.less';

interface CapabilityHintProps {
  caps: {
    supportsMultimodal: boolean;
    supportsImage: boolean;
    supportsVideo: boolean;
  };
}

/**
 * 显示当前模型的能力提示
 * 在输入框下方显示一行文字，说明模型支持的文件类型
 */
export function ModelCapabilityHint({ caps }: CapabilityHintProps) {
  const { t } = useTranslation();
  
  // 支持图片+视频
  if (caps.supportsImage && caps.supportsVideo) {
    return (
      <div className={styles.hint}>
        <Space size={4}>
          <CheckCircleOutlined style={{ color: '#52c41a' }} />
          <span>{t('chat.capability.imageAndVideo')}</span>
        </Space>
      </div>
    );
  }
  
  // 仅支持图片
  if (caps.supportsImage) {
    return (
      <div className={styles.hint}>
        <Space size={4}>
          <CheckCircleOutlined style={{ color: '#52c41a' }} />
          <EyeOutlined style={{ color: '#52c41a' }} />
          <span>{t('chat.capability.imageOnly')}</span>
        </Space>
      </div>
    );
  }
  
  // 仅支持视频
  if (caps.supportsVideo) {
    return (
      <div className={styles.hint}>
        <Space size={4}>
          <CheckCircleOutlined style={{ color: '#52c41a' }} />
          <VideoCameraOutlined style={{ color: '#52c41a' }} />
          <span>{t('chat.capability.videoOnly')}</span>
        </Space>
      </div>
    );
  }
  
  // 纯文本模型（已探测但不支持）
  if (caps.supportsMultimodal === false) {
    return (
      <div className={`${styles.hint} ${styles.warning}`}>
        <Space size={4}>
          <WarningOutlined style={{ color: '#faad14' }} />
          <span>{t('chat.capability.textOnly')}</span>
        </Space>
      </div>
    );
  }
  
  // 未检测
  return (
    <div className={styles.hint}>
      <Space size={4}>
        <InfoCircleOutlined style={{ color: '#1890ff' }} />
        <span>{t('chat.capability.notProbed')}</span>
      </Space>
    </div>
  );
}
