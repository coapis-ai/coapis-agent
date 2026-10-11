// Chat 组件导出

// 资源选择器（原工具栏组件，设计 §2.4 迁至 resource/）
// 文件树/知识库选择器已由通用 CascadeMenu + cascadeAdapters 取代（批次2 删除）
export { ReferenceHint } from './ReferenceHint';
export { ModelCapabilityHint } from './ModelCapabilityHint';
export { ModelCapabilityTag } from './ModelCapabilityTag';
export { ChatInputFooter } from './ChatInputFooter';
export { default as ModelChips } from './ModelChips';

export { useToolbarState } from './hooks/useToolbarState';

// M4 资源融合：+ 资源菜单与资源浮层
export {
  ResourcePlusMenu,
  CascadePickerModal,
  HistorySessionsModal,
  ScenePickerModal,
} from './resource';
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
