// Chat 组件导出

// 资源选择器（原工具栏组件，设计 §2.4 迁至 resource/）
export { FileTreeSelector } from './resource/FileTreeSelector';
export { KnowledgeSelector } from './resource/KnowledgeSelector';
export { ReferenceHint } from './ReferenceHint';
export { ModelCapabilityHint } from './ModelCapabilityHint';
export { ModelCapabilityTag } from './ModelCapabilityTag';
export { ChatInputFooter } from './ChatInputFooter';

export { useToolbarState } from './hooks/useToolbarState';
export { useFileTree } from './hooks/useFileTree';
export { useKnowledgeList } from './hooks/useKnowledgeList';

// M4 资源融合：+ 资源菜单与选择面板
export {
  ResourcePlusMenu,
  MySpacePickerModal,
  KnowledgePickerModal,
  HistorySessionsModal,
  ModelPickerModal,
  MultiSelectPickerModal,
} from './resource';
export type { PickItem } from './resource';

export type {
  FileInfo,
  FileNode,
  KnowledgeInfo,
  ReferenceItem,
  ToolbarTool,
  ToolbarState,
  ToolbarConfig,
} from './types';
