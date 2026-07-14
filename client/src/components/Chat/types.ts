// Chat 组件类型定义

import type { ReactNode } from 'react';

/**
 * 文件信息
 */
export interface FileInfo {
  id: string;
  name: string;
  path: string;
  type: 'file' | 'folder';
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
