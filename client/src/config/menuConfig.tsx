import React, { useState, useEffect, useCallback } from 'react';
import {
  HomeOutlined,
  AppstoreOutlined,
  FolderOutlined,
  SettingOutlined,
  MessageOutlined,
} from '@ant-design/icons';
import { menusApi } from '../api/modules/menus';

export interface MenuItem {
  key: string;
  label: string;
  labelKey: string;  // 国际化key
  icon: React.ReactNode;
  path: string;
  children?: MenuItem[];  // 支持二级菜单
  permission?: string;
  sortOrder?: number;
  isActive?: boolean;
}

// Fallback menu items (hardcoded, used when API fails)
export const FALLBACK_MENU_ITEMS: MenuItem[] = [
  // 首页功能暂时隐藏，待完善后再开放
  // {
  //   key: 'home',
  //   label: '首页',
  //   labelKey: 'nav.home',
  //   icon: <HomeOutlined />,
  //   path: '/home',
  // },
  {
    key: 'chat',
    label: '聊天',
    labelKey: 'nav.chat',
    icon: <MessageOutlined />,
    path: '/chat',
  },
  {
    key: 'workbench',
    label: '工作场景',
    labelKey: 'nav.workbench',
    icon: <AppstoreOutlined />,
    path: '/workbench',
    // 二级菜单从 API 动态加载，不在此硬编码
  },
  {
    key: 'myspace',
    label: '我的空间',
    labelKey: 'nav.myspace',
    icon: <FolderOutlined />,
    path: '/workspace/myspace',
  },
  {
    key: 'settings',
    label: '设置',
    labelKey: 'nav.settings',
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
  'HomeOutlined': <HomeOutlined />,  // 如果将来启用首页
};

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
        icon: ICON_MAP[item.icon] || <AppstoreOutlined />,
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
