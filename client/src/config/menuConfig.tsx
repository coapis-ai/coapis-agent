import React from 'react';
import {
  MessageOutlined,
  AppstoreOutlined,
  StarOutlined,
  FolderOutlined,
  SettingOutlined,
} from '@ant-design/icons';

export interface MenuItem {
  key: string;
  label: string;
  labelKey: string;  // 国际化key
  icon: React.ReactNode;
  path: string;
}

export const MAIN_MENU_ITEMS: MenuItem[] = [
  {
    key: 'chat',
    label: '聊天',
    labelKey: 'nav.chat',
    icon: <MessageOutlined />,
    path: '/chat',
  },
  {
    key: 'workbench',
    label: '办公',
    labelKey: 'nav.workbench',
    icon: <AppstoreOutlined />,
    path: '/workbench',
  },
  {
    key: 'my-scenes',
    label: '我的场景',
    labelKey: 'nav.myScenes',
    icon: <StarOutlined />,
    path: '/my-scenes',
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
