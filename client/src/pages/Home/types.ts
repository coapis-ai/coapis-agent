/**
 * 首页组件类型定义
 */

/**
 * 卡片尺寸
 */
export type WidgetSize = 'small' | 'medium' | 'large';

/**
 * 卡片配置
 */
export interface WidgetConfig {
  id: string;
  type: WidgetType;
  size: WidgetSize;
  visible: boolean;
  order: number;
}

/**
 * 卡片类型
 */
export type WidgetType =
  | 'welcome'        // 欢迎卡片
  | 'recommendations' // 推荐场景
  | 'recent'         // 最近使用
  | 'favorites'      // 我的收藏
  | 'hot'            // 热门场景
  | 'quickActions';  // 快捷操作

/**
 * 场景数据
 */
export interface Scene {
  id: string;
  name: string;
  description: string;
  icon?: string;
  primary_tag_id: string;
  tag_ids: string[];
  usage_count?: number;
  last_used_at?: string;
  is_favorite?: boolean;
}

/**
 * 用户配置
 */
export interface UserPreferences {
  function_tags: string[];
  recent_scenes: Scene[];
  favorite_scenes: string[];
  dashboard_config: WidgetConfig[];
}

/**
 * 天气数据（企业版功能）
 */
export interface WeatherData {
  city: string;
  temperature: number;
  condition: string;
  humidity: number;
  wind: string;
  forecast: WeatherForecast[];
}

export interface WeatherForecast {
  date: string;
  high: number;
  low: number;
  condition: string;
}

/**
 * 消息通知（企业版功能）
 */
export interface Message {
  id: string;
  type: 'info' | 'warning' | 'error' | 'success';
  title: string;
  content: string;
  created_at: string;
  is_read: boolean;
}

/**
 * 统计数据（企业版功能）
 */
export interface Statistics {
  total_sessions: number;
  total_messages: number;
  total_tokens: number;
  active_days: number;
  most_used_scenes: Scene[];
}

/**
 * 卡片Props
 */
export interface WidgetProps {
  config?: WidgetConfig;
  data?: any;
  onRefresh?: () => void;
  onAction?: (action: string, data?: any) => void;
}

/**
 * 首页Props
 */
export interface HomeProps {
  user?: {
    id: string;
    name: string;
    function_tags?: string[];
  };
}
