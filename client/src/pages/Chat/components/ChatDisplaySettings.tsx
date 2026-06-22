/**
 * ChatDisplaySettings — 聊天显示设置面板
 *
 * 提供可视化界面让用户配置聊天消息的显示选项：
 * - 隐藏细节（摘要模式）
 * - 自动滚动
 * - 字体大小
 * - 代码主题
 *
 * 配置自动保存到 localStorage 并同步到后端（通过 UserContext）。
 */
import React, { useCallback, useMemo } from 'react';
import { Modal, Switch, Radio, Divider, Space, Button } from 'antd';
import {
  EyeOutlined,
  ReloadOutlined,
  VerticalAlignBottomOutlined,
  FontSizeOutlined,
  CodeOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import {
  ChatDisplayConfig,
  DEFAULT_CHAT_DISPLAY_CONFIG,
  saveChatDisplayConfig,
} from '../types';
import { useChatDisplayFromUser } from '@/hooks/useChatDisplayFromUser';

interface ChatDisplaySettingsProps {
  visible: boolean;
  config: ChatDisplayConfig;
  onConfigChange: (config: ChatDisplayConfig) => void;
  onClose: () => void;
}

const ChatDisplaySettings: React.FC<ChatDisplaySettingsProps> = ({
  visible,
  config,
  onConfigChange,
  onClose,
}) => {
  const { t } = useTranslation();
  const { updateDisplayConfig: backendUpdate, resetToDefaults: backendReset } = useChatDisplayFromUser();

  const updateConfig = useCallback(
    (key: keyof ChatDisplayConfig, value: boolean | string) => {
      const newConfig = { ...config, [key]: value };
      saveChatDisplayConfig(newConfig);
      onConfigChange(newConfig);
      // Sync to backend via UserContext
      backendUpdate(key, value);
    },
    [config, onConfigChange, backendUpdate],
  );

  const resetToDefaults = useCallback(() => {
    saveChatDisplayConfig(DEFAULT_CHAT_DISPLAY_CONFIG);
    onConfigChange(DEFAULT_CHAT_DISPLAY_CONFIG);
    // Sync to backend via UserContext
    backendReset();
  }, [onConfigChange, backendReset]);

  const fontSizeOptions = useMemo(() => [
    { label: t('chat.settings.fontSize.small', { defaultValue: '小' }), value: 'small' },
    { label: t('chat.settings.fontSize.normal', { defaultValue: '正常' }), value: 'normal' },
    { label: t('chat.settings.fontSize.large', { defaultValue: '大' }), value: 'large' },
  ], [t]);

  const codeThemeOptions = useMemo(() => [
    { label: t('chat.settings.codeTheme.light', { defaultValue: '浅色' }), value: 'light' },
    { label: t('chat.settings.codeTheme.dark', { defaultValue: '深色' }), value: 'dark' },
  ], [t]);

  return (
    <Modal
      title={
        <Space>
          <EyeOutlined />
          {t('chat.settings.title', { defaultValue: '聊天显示设置' })}
        </Space>
      }
      open={visible}
      onCancel={onClose}
      footer={null}
      width={400}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        {/* 内容显示 */}
        <div>
          <div style={{ fontWeight: 500, marginBottom: 8, color: '#666' }}>
            {t('chat.settings.section.content', { defaultValue: '内容显示' })}
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Space>
              <EyeOutlined />
              <span>{t('chat.settings.hideDetails', { defaultValue: '隐藏细节' })}</span>
            </Space>
            <Switch
              checked={config.hideDetails}
              onChange={(checked) => updateConfig('hideDetails', checked)}
            />
          </div>
          <div style={{ fontSize: 12, color: '#999', marginTop: 4 }}>
            {t('chat.settings.hideDetailsDesc', { 
              defaultValue: '开启后，思考过程、工具调用、正文内容将显示摘要，点击可展开查看完整内容' 
            })}
          </div>
        </div>

        <Divider style={{ margin: '8px 0' }} />

        {/* 交互 */}
        <div>
          <div style={{ fontWeight: 500, marginBottom: 8, color: '#666' }}>
            {t('chat.settings.section.interaction', { defaultValue: '交互' })}
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Space>
              <VerticalAlignBottomOutlined />
              <span>{t('chat.settings.autoScroll', { defaultValue: '自动滚动' })}</span>
            </Space>
            <Switch
              checked={config.autoScroll}
              onChange={(checked) => updateConfig('autoScroll', checked)}
            />
          </div>
          <div style={{ fontSize: 12, color: '#999', marginTop: 4 }}>
            {t('chat.settings.autoScrollDesc', { 
              defaultValue: '新消息到达时自动滚动到底部' 
            })}
          </div>
        </div>

        <Divider style={{ margin: '8px 0' }} />

        {/* 外观 */}
        <div>
          <div style={{ fontWeight: 500, marginBottom: 8, color: '#666' }}>
            {t('chat.settings.section.appearance', { defaultValue: '外观' })}
          </div>
          
          {/* 字体大小 */}
          <div style={{ marginBottom: 12 }}>
            <Space style={{ marginBottom: 8 }}>
              <FontSizeOutlined />
              <span>{t('chat.settings.fontSize', { defaultValue: '字体大小' })}</span>
            </Space>
            <Radio.Group
              value={config.fontSize}
              onChange={(e) => updateConfig('fontSize', e.target.value)}
              optionType="button"
              buttonStyle="solid"
              size="small"
            >
              {fontSizeOptions.map((opt) => (
                <Radio.Button key={opt.value} value={opt.value}>
                  {opt.label}
                </Radio.Button>
              ))}
            </Radio.Group>
          </div>

          {/* 代码主题 */}
          <div>
            <Space style={{ marginBottom: 8 }}>
              <CodeOutlined />
              <span>{t('chat.settings.codeTheme', { defaultValue: '代码主题' })}</span>
            </Space>
            <Radio.Group
              value={config.codeTheme}
              onChange={(e) => updateConfig('codeTheme', e.target.value)}
              optionType="button"
              buttonStyle="solid"
              size="small"
            >
              {codeThemeOptions.map((opt) => (
                <Radio.Button key={opt.value} value={opt.value}>
                  {opt.label}
                </Radio.Button>
              ))}
            </Radio.Group>
          </div>
        </div>

        <Divider style={{ margin: '8px 0' }} />

        {/* 恢复默认 */}
        <Button
          icon={<ReloadOutlined />}
          onClick={resetToDefaults}
          block
        >
          {t('chat.settings.reset', { defaultValue: '恢复默认设置' })}
        </Button>
      </div>
    </Modal>
  );
};

export default ChatDisplaySettings;
