/**
 * ChatDisplaySettings — 聊天显示设置面板
 *
 * 提供可视化界面让用户配置聊天消息的显示选项：
 * - 显示模式切换（简洁/详细）
 * - 隐藏工具调用卡片、思考过程、页脚、系统消息
 * - 消息细节：时间戳、Token 计数、模型名
 * - 交互：自动滚动
 * - 外观：字体大小、代码主题
 *
 * 配置自动保存到 localStorage 并同步到后端（通过 UserContext）。
 */
import React, { useCallback, useMemo } from 'react';
import { Modal, Switch, Radio, Divider, Space, Tooltip, Button, Collapse } from 'antd';
import {
  EyeOutlined,
  EyeInvisibleOutlined,
  ToolOutlined,
  BulbOutlined,
  UnorderedListOutlined,
  BgColorsOutlined,
  ReloadOutlined,
  ClockCircleOutlined,
  ThunderboltOutlined,
  CloudServerOutlined,
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
import styles from '../index.module.less';

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

  const displayModeOptions = useMemo(() => [
    { label: t('chat.settings.displayMode.simple', { defaultValue: '简洁模式' }), value: 'simple' },
    { label: t('chat.settings.displayMode.detailed', { defaultValue: '详细模式' }), value: 'detailed' },
  ], [t]);

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
      title={t('chat.settings.title', { defaultValue: '聊天显示设置' })}
      open={visible}
      onCancel={onClose}
      footer={[
        <Button key="reset" onClick={resetToDefaults} icon={<ReloadOutlined />}>
          {t('chat.settings.reset', { defaultValue: '恢复默认' })}
        </Button>,
        <Button key="close" type="primary" onClick={onClose}>
          {t('chat.settings.close', { defaultValue: '确定' })}
        </Button>,
      ]}
      width={460}
      className={styles.chatSettingsModal}
    >
      <div className={styles.chatSettingsContent}>
        {/* Display Mode */}
        <div className={styles.settingsSection}>
          <div className={styles.settingsSectionTitle}>
            <BgColorsOutlined />
            <span>{t('chat.settings.displayMode.title', { defaultValue: '显示模式' })}</span>
          </div>
          <Radio.Group
            value={config.displayMode}
            onChange={(e) => updateConfig('displayMode', e.target.value)}
          >
            <Space direction="vertical" style={{ width: '100%' }}>
              {displayModeOptions.map((opt) => (
                <Radio key={opt.value} value={opt.value}>
                  {opt.label}
                </Radio>
              ))}
            </Space>
          </Radio.Group>
          <div className={styles.settingsDescription}>
            {config.displayMode === 'simple'
              ? t('chat.settings.displayMode.simpleDesc', {
                  defaultValue: '仅显示对话内容，隐藏工具调用、思考过程等细节',
                })
              : t('chat.settings.displayMode.detailedDesc', {
                  defaultValue: '显示完整的 Agent 执行过程，包括工具调用和中间结果',
                })}
          </div>
        </div>

        <Divider style={{ margin: '16px 0' }} />

        {/* Toggle Options — only shown in simple mode */}
        {config.displayMode === 'simple' && (
          <>
            {/* Hide Tool Calls */}
            <div className={styles.settingsRow}>
              <div className={styles.settingsRowLeft}>
                <Tooltip title={t('chat.settings.hideToolCall.tooltip', { defaultValue: '隐藏工具调用详情卡片' })}>
                  <ToolOutlined style={{ color: '#1890ff', marginRight: 8 }} />
                </Tooltip>
                <span>{t('chat.settings.hideToolCall.label', { defaultValue: '隐藏工具调用' })}</span>
              </div>
              <Switch
                checked={config.hideToolCall}
                onChange={(v) => updateConfig('hideToolCall', v)}
                checkedChildren={<EyeInvisibleOutlined />}
                unCheckedChildren={<EyeOutlined />}
              />
            </div>

            {/* Hide Thinking */}
            <div className={styles.settingsRow}>
              <div className={styles.settingsRowLeft}>
                <Tooltip title={t('chat.settings.hideThinking.tooltip', { defaultValue: '隐藏思考过程/推理链' })}>
                  <BulbOutlined style={{ color: '#faad14', marginRight: 8 }} />
                </Tooltip>
                <span>{t('chat.settings.hideThinking.label', { defaultValue: '隐藏思考过程' })}</span>
              </div>
              <Switch
                checked={config.hideThinking}
                onChange={(v) => updateConfig('hideThinking', v)}
                checkedChildren={<EyeInvisibleOutlined />}
                unCheckedChildren={<EyeOutlined />}
              />
            </div>

            {/* Hide Footer */}
            <div className={styles.settingsRow}>
              <div className={styles.settingsRowLeft}>
                <Tooltip title={t('chat.settings.hideFooter.tooltip', { defaultValue: '隐藏 token 统计、时间戳、模型名' })}>
                  <UnorderedListOutlined style={{ color: '#52c41a', marginRight: 8 }} />
                </Tooltip>
                <span>{t('chat.settings.hideFooter.label', { defaultValue: '隐藏页脚信息' })}</span>
              </div>
              <Switch
                checked={config.hideFooter}
                onChange={(v) => updateConfig('hideFooter', v)}
                checkedChildren={<EyeInvisibleOutlined />}
                unCheckedChildren={<EyeOutlined />}
              />
            </div>

            {/* Hide System Messages */}
            <div className={styles.settingsRow}>
              <div className={styles.settingsRowLeft}>
                <Tooltip title={t('chat.settings.hideSystemMessages.tooltip', { defaultValue: '隐藏系统消息' })}>
                  <EyeInvisibleOutlined style={{ color: '#722ed1', marginRight: 8 }} />
                </Tooltip>
                <span>{t('chat.settings.hideSystemMessages.label', { defaultValue: '隐藏系统消息' })}</span>
              </div>
              <Switch
                checked={config.hideSystemMessages}
                onChange={(v) => updateConfig('hideSystemMessages', v)}
                checkedChildren={<EyeInvisibleOutlined />}
                unCheckedChildren={<EyeOutlined />}
              />
            </div>
          </>
        )}

        {/* Advanced Settings — always visible */}
        <Collapse
          items={[
            {
              key: 'message-details',
              label: (
                <Space>
                  <ClockCircleOutlined style={{ color: '#1890ff' }} />
                  {t('chat.settings.messageDetails.title', { defaultValue: '消息细节' })}
                </Space>
              ),
              children: (
                <Space direction="vertical" style={{ width: '100%', padding: '8px 0' }}>
                  {/* Show Timestamps */}
                  <div className={styles.settingsRow}>
                    <div className={styles.settingsRowLeft}>
                      <ClockCircleOutlined style={{ color: '#1890ff', marginRight: 8 }} />
                      <span>{t('chat.settings.showTimestamps.label', { defaultValue: '显示时间戳' })}</span>
                    </div>
                    <Switch
                      checked={config.showTimestamps}
                      onChange={(v) => updateConfig('showTimestamps', v)}
                    />
                  </div>

                  {/* Show Token Counts */}
                  <div className={styles.settingsRow}>
                    <div className={styles.settingsRowLeft}>
                      <ThunderboltOutlined style={{ color: '#faad14', marginRight: 8 }} />
                      <span>{t('chat.settings.showTokenCounts.label', { defaultValue: '显示 Token 计数' })}</span>
                    </div>
                    <Switch
                      checked={config.showTokenCounts}
                      onChange={(v) => updateConfig('showTokenCounts', v)}
                    />
                  </div>

                  {/* Show Model Name */}
                  <div className={styles.settingsRow}>
                    <div className={styles.settingsRowLeft}>
                      <CloudServerOutlined style={{ color: '#52c41a', marginRight: 8 }} />
                      <span>{t('chat.settings.showModelName.label', { defaultValue: '显示模型名称' })}</span>
                    </div>
                    <Switch
                      checked={config.showModelName}
                      onChange={(v) => updateConfig('showModelName', v)}
                    />
                  </div>
                </Space>
              ),
            },
            {
              key: 'interaction',
              label: (
                <Space>
                  <VerticalAlignBottomOutlined style={{ color: '#722ed1' }} />
                  {t('chat.settings.interaction.title', { defaultValue: '交互设置' })}
                </Space>
              ),
              children: (
                <Space direction="vertical" style={{ width: '100%', padding: '8px 0' }}>
                  {/* Auto Scroll */}
                  <div className={styles.settingsRow}>
                    <div className={styles.settingsRowLeft}>
                      <VerticalAlignBottomOutlined style={{ color: '#722ed1', marginRight: 8 }} />
                      <span>{t('chat.settings.autoScroll.label', { defaultValue: '自动滚动到底部' })}</span>
                    </div>
                    <Switch
                      checked={config.autoScroll}
                      onChange={(v) => updateConfig('autoScroll', v)}
                    />
                  </div>
                </Space>
              ),
            },
            {
              key: 'appearance',
              label: (
                <Space>
                  <FontSizeOutlined style={{ color: '#eb2f96' }} />
                  {t('chat.settings.appearance.title', { defaultValue: '外观设置' })}
                </Space>
              ),
              children: (
                <Space direction="vertical" style={{ width: '100%', padding: '8px 0' }}>
                  {/* Font Size */}
                  <div style={{ marginBottom: 12 }}>
                    <div className={styles.settingsRowLeft} style={{ marginBottom: 8 }}>
                      <FontSizeOutlined style={{ color: '#eb2f96', marginRight: 8 }} />
                      <span>{t('chat.settings.fontSize.title', { defaultValue: '字体大小' })}</span>
                    </div>
                    <Radio.Group
                      value={config.fontSize}
                      onChange={(e) => updateConfig('fontSize', e.target.value)}
                    >
                      <Space>
                        {fontSizeOptions.map((opt) => (
                          <Radio.Button key={opt.value} value={opt.value}>
                            {opt.label}
                          </Radio.Button>
                        ))}
                      </Space>
                    </Radio.Group>
                  </div>

                  {/* Code Theme */}
                  <div>
                    <div className={styles.settingsRowLeft} style={{ marginBottom: 8 }}>
                      <CodeOutlined style={{ color: '#13c2c2', marginRight: 8 }} />
                      <span>{t('chat.settings.codeTheme.title', { defaultValue: '代码块主题' })}</span>
                    </div>
                    <Radio.Group
                      value={config.codeTheme}
                      onChange={(e) => updateConfig('codeTheme', e.target.value)}
                    >
                      <Space>
                        {codeThemeOptions.map((opt) => (
                          <Radio.Button key={opt.value} value={opt.value}>
                            {opt.label}
                          </Radio.Button>
                        ))}
                      </Space>
                    </Radio.Group>
                  </div>
                </Space>
              ),
            },
          ]}
          bordered={false}
          defaultActiveKey={['message-details']}
          style={{ marginTop: 8 }}
        />

        {config.displayMode === 'detailed' && (
          <div className={styles.settingsDescription} style={{ textAlign: 'center', padding: '16px 0' }}>
            {t('chat.settings.detailedModeNote', {
              defaultValue: '详细模式下显示所有信息。切换到简洁模式可自定义隐藏选项。',
            })}
          </div>
        )}
      </div>
    </Modal>
  );
};

export default ChatDisplaySettings;
