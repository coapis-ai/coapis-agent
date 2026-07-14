// 全局工具组件

import { List, Button } from 'antd';
import {
  HistoryOutlined,
  ThunderboltOutlined,
  SettingOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import type { ToolbarTool } from '../types';
import './index.module.less';

interface GlobalToolsProps {
  onToolClick?: (key: string) => void;
}

/**
 * 全局工具列表
 * 包含历史、模型、设置、搜索等全局操作
 */
export function GlobalTools({ onToolClick }: GlobalToolsProps) {
  const tools: ToolbarTool[] = [
    {
      key: 'history',
      icon: <HistoryOutlined />,
      label: '历史会话',
      order: 1,
    },
    {
      key: 'model',
      icon: <ThunderboltOutlined />,
      label: '模型选择',
      order: 2,
    },
    {
      key: 'settings',
      icon: <SettingOutlined />,
      label: '显示设置',
      order: 3,
    },
    {
      key: 'search',
      icon: <SearchOutlined />,
      label: '搜索消息',
      order: 4,
    },
  ];

  return (
    <div className="chat-toolbar-global-tools">
      <List
        dataSource={tools.sort((a, b) => (a.order || 0) - (b.order || 0))}
        renderItem={(tool) => (
          <List.Item>
            <Button
              type="text"
              className="tool-item"
              icon={tool.icon}
              onClick={() => onToolClick?.(tool.key)}
              disabled={tool.disabled}
              block
            >
              {tool.label}
            </Button>
          </List.Item>
        )}
      />
    </div>
  );
}
