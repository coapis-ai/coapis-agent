import React from 'react';
import {
  // HomeOutlined,  // 首页功能暂时隐藏
  AppstoreOutlined,
  FolderOutlined,
  SettingOutlined,
  MessageOutlined,
} from '@ant-design/icons';

export interface MenuItem {
  key: string;
  label: string;
  labelKey: string;  // 国际化key
  icon: React.ReactNode;
  path: string;
  children?: MenuItem[];  // 支持二级菜单
}

export const MAIN_MENU_ITEMS: MenuItem[] = [
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
