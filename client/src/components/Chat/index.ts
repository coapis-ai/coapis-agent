// Chat 组件导出

export { ChatToolbarDrawer } from './ChatToolbarDrawer';
export { ChatToolbarSidebar } from './ChatToolbarDrawer/ChatToolbarSidebar';
export { PinButton } from './ChatToolbarDrawer/PinButton';
export { GlobalTools } from './ChatToolbarDrawer/GlobalTools';
export { FileTreeSelector } from './ChatToolbarDrawer/FileTreeSelector';
export { KnowledgeSelector } from './ChatToolbarDrawer/KnowledgeSelector';
export { SelectedReferences } from './ChatToolbarDrawer/SelectedReferences';
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
