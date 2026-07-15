import { Space } from 'antd';
import { 
  CheckCircleOutlined, 
  WarningOutlined,
  InfoCircleOutlined,
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
 * 简洁版本：✓图片 ✓视频
 */
export function ModelCapabilityHint({ caps }: CapabilityHintProps) {
  const { t } = useTranslation();
  
  // 支持图片+视频
  if (caps.supportsImage && caps.supportsVideo) {
    return (
      <div className={styles.hintCompact}>
        <Space size={8}>
          <span className={styles.capItem}>
            <CheckCircleOutlined style={{ color: '#52c41a', marginRight: 2 }} />
            {t('chat.capability.image', '图片')}
          </span>
          <span className={styles.capItem}>
            <CheckCircleOutlined style={{ color: '#52c41a', marginRight: 2 }} />
            {t('chat.capability.video', '视频')}
          </span>
        </Space>
      </div>
    );
  }
  
  // 仅支持图片
  if (caps.supportsImage) {
    return (
      <div className={styles.hintCompact}>
        <span className={styles.capItem}>
          <CheckCircleOutlined style={{ color: '#52c41a', marginRight: 2 }} />
          {t('chat.capability.image', '图片')}
        </span>
      </div>
    );
  }
  
  // 仅支持视频
  if (caps.supportsVideo) {
    return (
      <div className={styles.hintCompact}>
        <span className={styles.capItem}>
          <CheckCircleOutlined style={{ color: '#52c41a', marginRight: 2 }} />
          {t('chat.capability.video', '视频')}
        </span>
      </div>
    );
  }
  
  // 纯文本模型（已探测但不支持）
  if (caps.supportsMultimodal === false) {
    return (
      <div className={styles.hintCompact}>
        <span className={styles.capItem}>
          <WarningOutlined style={{ color: '#faad14', marginRight: 2 }} />
          {t('chat.capability.textOnlyShort', '仅文本')}
        </span>
      </div>
    );
  }
  
  // 未检测
  return (
    <div className={styles.hintCompact}>
      <span className={styles.capItem}>
        <InfoCircleOutlined style={{ color: '#1890ff', marginRight: 2 }} />
        {t('chat.capability.notProbedShort', '未检测')}
      </span>
    </div>
  );
}
