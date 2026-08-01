/**
 * 首页常量配置
 */

import { WidgetConfig, WidgetSize } from './types';

/**
 * 默认卡片配置
 */
export const DEFAULT_WIDGET_CONFIGS: WidgetConfig[] = [
  {
    id: 'welcome',
    type: 'welcome',
    size: 'medium',
    visible: true,
    order: 0,
  },
  {
    id: 'recommendations',
    type: 'recommendations',
    size: 'large',
    visible: true,
    order: 1,
  },
  {
    id: 'recent',
    type: 'recent',
    size: 'medium',
    visible: true,
    order: 2,
  },
  {
    id: 'favorites',
    type: 'favorites',
    size: 'small',
    visible: true,
    order: 3,
  },
  {
    id: 'hot',
    type: 'hot',
    size: 'small',
    visible: true,
    order: 4,
  },
  {
    id: 'quickActions',
    type: 'quickActions',
    size: 'small',
    visible: true,
    order: 5,
  },
];

/**
 * 卡片尺寸对应的列数（12列网格）
 */
export const WIDGET_SIZE_COLUMNS: Record<WidgetSize, number> = {
  small: 3,   // 3列（1/4宽度）
  medium: 6,  // 6列（1/2宽度）
  large: 12,  // 12列（全宽）
};

/**
 * 卡片类型名称映射
 */
export const WIDGET_TYPE_NAMES: Record<string, string> = {
  welcome: '欢迎',
  recommendations: '推荐场景',
  recent: '最近使用',
  favorites: '我的收藏',
  hot: '热门场景',
  quickActions: '快捷操作',
};

/**
 * 卡片类型图标映射
 */
export const WIDGET_TYPE_ICONS: Record<string, string> = {
  welcome: '👋',
  recommendations: '🎯',
  recent: '📅',
  favorites: '⭐',
  hot: '🔥',
  quickActions: '⚡',
};

/**
 * 本地存储键名
 */
export const STORAGE_KEYS = {
  USER_PREFERENCES: 'coapis_user_preferences',
  DASHBOARD_CONFIG: 'coapis_dashboard_config',
  RECENT_SCENES: 'coapis_recent_scenes',
  FAVORITE_SCENES: 'coapis_favorite_scenes',
  FUNCTION_TAGS: 'coapis_function_tags',
};

/**
 * 默认职能标签
 */
export const DEFAULT_FUNCTION_TAGS = [
  '办公协作',
  '文档处理',
  '会议管理',
  '项目管理',
  '数据分析',
];

/**
 * 快捷操作配置
 */
export const QUICK_ACTIONS = [
  {
    id: 'new-chat',
    name: '新对话',
    icon: '💬',
    scene_id: null,
  },
  {
    id: 'meeting-minutes',
    name: '会议纪要',
    icon: '📝',
    scene_id: 'meeting-minutes',
  },
  {
    id: 'translation',
    name: '翻译助手',
    icon: '🌐',
    scene_id: 'translation',
  },
  {
    id: 'code-assistant',
    name: '代码助手',
    icon: '💻',
    scene_id: 'code-assistant',
  },
];

/**
 * API端点
 */
export const API_ENDPOINTS = {
  SCENES: '/api/scenes',
  RECOMMENDATIONS: '/api/scenes/recommendations',
  RECENT: '/api/scenes/recent',
  HOT: '/api/scenes/hot',
  FAVORITES: '/api/scenes/favorites',
  USER_PREFERENCES: '/api/user/preferences',
  DASHBOARD_CONFIG: '/api/user/dashboard-config',
};
