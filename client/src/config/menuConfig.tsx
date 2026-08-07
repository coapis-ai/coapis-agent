import React, { useState, useEffect, useCallback } from 'react';
import {
  HomeOutlined,
  AppstoreOutlined,
  FolderOutlined,
  SettingOutlined,
  MessageOutlined,
  BookOutlined,
  CrownOutlined,
  ThunderboltOutlined,
  BarChartOutlined,
  SafetyOutlined,
  FileOutlined,
  CloudOutlined,
  RobotOutlined,
  ToolOutlined,
  LinkOutlined,
  TeamOutlined,
  MenuOutlined,
} from '@ant-design/icons';
import { menusApi } from '../api/modules/menus';

export interface MenuItem {
  key: string;
  label: string;
  icon: React.ReactNode;
  iconName?: string;  // 原始图标名称/emoji
  path: string;
  children?: MenuItem[];  // 支持二级菜单
  permission?: string;
  sortOrder?: number;
}

// Fallback menu items (hardcoded, used when API fails)
export const FALLBACK_MENU_ITEMS: MenuItem[] = [
  {
    key: 'chat',
    label: '聊天',
    icon: <MessageOutlined />,
    path: '/chat',
  },
  {
    key: 'workbench',
    label: '工作场景',
    icon: <AppstoreOutlined />,
    path: '/workbench',
    // 二级菜单从 API 动态加载，不在此硬编码
  },
  {
    key: 'myspace',
    label: '我的空间',
    icon: <FolderOutlined />,
    path: '/workspace/myspace',
  },
  {
    key: 'settings',
    label: '设置',
    icon: <SettingOutlined />,
    path: '/settings',
  },
];

// Icon map for converting string icon names to React components
const ICON_MAP: Record<string, React.ReactNode> = {
  'MessageOutlined': <MessageOutlined />,
  'AppstoreOutlined': <AppstoreOutlined />,
  'FolderOutlined': <FolderOutlined />,
  'SettingOutlined': <SettingOutlined />,
  'HomeOutlined': <HomeOutlined />,
  'BookOutlined': <BookOutlined />,
  'CrownOutlined': <CrownOutlined />,
  'ThunderboltOutlined': <ThunderboltOutlined />,
  'BarChartOutlined': <BarChartOutlined />,
  'SafetyOutlined': <SafetyOutlined />,
  'FileOutlined': <FileOutlined />,
  'CloudOutlined': <CloudOutlined />,
  'RobotOutlined': <RobotOutlined />,
  'ToolOutlined': <ToolOutlined />,
  'LinkOutlined': <LinkOutlined />,
  'TeamOutlined': <TeamOutlined />,
  'MenuOutlined': <MenuOutlined />,
};

/**
 * Render a menu icon from backend string.
 * - Known Ant Design icon names → mapped React component
 * - Emoji / other string → wrapped in <span>
 * - Empty / unknown → fallback icon
 */
function renderIcon(iconName: string | undefined, fallback: React.ReactNode = <AppstoreOutlined />): React.ReactNode {
  if (!iconName) return fallback;
  if (ICON_MAP[iconName]) return ICON_MAP[iconName];
  // Emoji detection: emoji are outside basic ASCII range
  if (/[^\x00-\x7F]/.test(iconName)) {
    return <span style={{ fontSize: 16 }}>{iconName}</span>;
  }
  return fallback;
}

// Hook to load menu items from API
export function useMenuItems() {
  const [menuItems, setMenuItems] = useState<MenuItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const loadMenuItems = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await menusApi.getMainMenu();
      const items = response.items.map((item) => ({
        ...item,
        iconName: item.icon,
        icon: renderIcon(item.icon),
        children: item.children?.map((child: any) => ({
          ...child,
          iconName: child.icon,
          icon: renderIcon(child.icon, <AppstoreOutlined /> as any),
        })),
      }));
      setMenuItems(items);
    } catch (err) {
      setError(err instanceof Error ? err : new Error('Failed to load menu'));
      // Fallback to hardcoded items on error
      setMenuItems(FALLBACK_MENU_ITEMS);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadMenuItems();
  }, [loadMenuItems]);

  return { menuItems, loading, error, refresh: loadMenuItems };
}

// Legacy export for backward compatibility
// This will be empty initially and populated by useMenuItems hook
export let MAIN_MENU_ITEMS: MenuItem[] = [];

// Sync MAIN_MENU_ITEMS with the hook (for components that don't use the hook)
// This is a simple approach - components should migrate to useMenuItems hook
export function setMainMenuItems(items: MenuItem[]) {
  MAIN_MENU_ITEMS = items;
}
