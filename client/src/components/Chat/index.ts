// Chat 组件导出

// 资源选择器（原工具栏组件，设计 §2.4 迁至 resource/）
// 文件树/知识库选择器已由通用 CascadeMenu + cascadeAdapters 取代（批次2 删除）
// ReferenceHint 已摘除导出：设计第四区（计数+清空）已并入 ChatInputFooter，
// 本组件零调用方，文件与样式已移入 .trash/deadcode_20261012/（2026-10-12 放行）
export { ModelCapabilityHint } from './ModelCapabilityHint';
export { ModelCapabilityTag } from './ModelCapabilityTag';
export { ChatInputFooter } from './ChatInputFooter';
export { default as ModelChips } from './ModelChips';

export { useToolbarState } from './hooks/useToolbarState';

// M4 资源融合：+ 资源菜单与资源浮层
// HistorySessionsModal 已摘除导出：会话引用(refSessions)是空壳——无入口写入、
// 无出口发送、无后端消费者，已随 A5 收口删除状态。零调用方，文件已移入
// .trash/deadcode_20261012/（2026-10-12 放行）。
export { ResourcePlusMenu, CascadePickerModal, ScenePickerModal } from './resource';
export type { PickItem } from './types';
export type { SessionFile } from './resource';

export type {
  FileInfo,
  FileNode,
  KnowledgeInfo,
  ReferenceItem,
  ToolbarTool,
  ToolbarState,
  ToolbarConfig,
} from './types';
