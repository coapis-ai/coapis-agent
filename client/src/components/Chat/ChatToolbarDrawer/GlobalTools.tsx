// 全局工具组件

import { List, Button } from 'antd';
import {
  ThunderboltOutlined,
  HistoryOutlined,
  SettingOutlined,
  SearchOutlined,
} from '@ant-design/icons';

interface GlobalToolsProps {
  onModelSelect?: () => void;
  onHistoryClick?: () => void;
  onSettingsClick?: () => void;
  onSearchClick?: () => void;
}

/**
 * 全局工具列表
 * 包含模型选择、聊天历史、显示设置、搜索消息等全局操作
 */
export function GlobalTools({ 
  onModelSelect,
  onHistoryClick,
  onSettingsClick,
  onSearchClick,
}: GlobalToolsProps) {
  const tools = [
    {
      key: 'model',
      icon: <ThunderboltOutlined />,
      label: '模型选择',
      onClick: onModelSelect,
    },
    {
      key: 'history',
      icon: <HistoryOutlined />,
      label: '聊天历史',
      onClick: onHistoryClick,
    },
    {
      key: 'settings',
      icon: <SettingOutlined />,
      label: '显示设置',
      onClick: onSettingsClick,
    },
    {
      key: 'search',
      icon: <SearchOutlined />,
      label: '搜索消息',
      onClick: onSearchClick,
    },
  ];

  return (
    <div className="chat-toolbar-global-tools">
      <List
        dataSource={tools}
        renderItem={(tool) => (
          <List.Item style={{ border: 'none', padding: '8px 0' }}>
            <Button
              type="text"
              icon={tool.icon}
              onClick={tool.onClick}
              block
              style={{ 
                textAlign: 'left',
                height: '40px',
                fontSize: '14px',
              }}
            >
              {tool.label}
            </Button>
          </List.Item>
        )}
      />
    </div>
  );
}
