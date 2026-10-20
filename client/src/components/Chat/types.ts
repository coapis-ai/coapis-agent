// Chat 组件类型定义

import type { ReactNode } from 'react';

/** 通用可选项（会话引用等选择器共用） */
export interface PickItem {
  id: string;
  name: string;
  desc?: string;
}

/**
 * 文件信息
 *
 * type 里的 image/video/audio 不是装饰：发送时它决定内容块类型，
 * 而只有 image/video/audio 块才会被后端转成真正的媒体数据送给模型；
 * 图片被写成 "file" 时 formatter 只给一句文本占位符，模型看不到像素。
 * 判定入口：pages/Chat/utils.ts → mediaTypeFromFilename()
 */
export interface FileInfo {
  id: string;
  name: string;
  path: string;
  type: 'file' | 'folder' | 'image' | 'video' | 'audio';
  size?: number;
  mimeType?: string;
  createdAt?: string;
  updatedAt?: string;
}

/**
 * 文件树节点
 */
export interface FileNode {
  id: string;
  name: string;
  path: string;
  type: 'file' | 'folder';
  size?: number;
  mimeType?: string;
  children?: FileNode[];
}

/**
 * 知识库信息
 */
export interface KnowledgeInfo {
  id: string;
  name: string;
  description?: string;
  documentCount?: number;
  createdAt?: string;
}

/**
 * 引用项
 */
export interface ReferenceItem {
  id: string;
  type: 'file' | 'knowledge';
  name: string;
  icon?: ReactNode;
}

/**
 * 工具栏工具定义
 */
export interface ToolbarTool {
  key: string;
  icon: ReactNode;
  label: string;
  component?: React.ComponentType<any>;
  onClick?: () => void;
  disabled?: boolean;
  visible?: boolean;
  order?: number;
}

/**
 * 工具栏状态
 */
export interface ToolbarState {
  visible: boolean;
  pinned: boolean;
  activeTab: 'tools' | 'files' | 'knowledge';
}

/**
 * 工具栏配置
 */
export interface ToolbarConfig {
  showPinButton?: boolean;
  defaultPinned?: boolean;
  defaultVisible?: boolean;
  width?: number;
}
