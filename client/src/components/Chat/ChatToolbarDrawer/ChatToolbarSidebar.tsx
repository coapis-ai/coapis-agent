// ChatToolbarSidebar 侧边栏组件（非Drawer版本）

import { SelectedReferences } from './SelectedReferences';
import { GlobalTools } from './GlobalTools';
import type { FileInfo, KnowledgeInfo } from '../types';
import styles from './Sidebar.module.less';

interface ChatToolbarSidebarProps {
  onFileSelect: (files: FileInfo[]) => void;
  onKnowledgeSelect: (items: KnowledgeInfo[]) => void;
  selectedFiles?: FileInfo[];
  selectedKnowledge?: KnowledgeInfo[];
  showPinButton?: boolean;
  onPinToggle?: (pinned: boolean) => void;
  defaultPinned?: boolean;
  onSettingsClick?: () => void;
  showKnowledge?: boolean;
}

/**
 * 聊天工具栏侧边栏组件
 * 
 * 功能：
 * - 侧边栏形式显示（不使用Drawer）
 * - 包含工具、已选引用
 */
export function ChatToolbarSidebar({
  onFileSelect,
  onKnowledgeSelect,
  selectedFiles = [],
  selectedKnowledge = [],
  onSettingsClick,
  showKnowledge = true,
}: ChatToolbarSidebarProps) {
  // 计算总引用数
  const totalReferences = selectedFiles.length + selectedKnowledge.length;

  return (
    <div className={styles.chatToolbarSidebar}>
      {/* 工具列表 */}
      <div className={styles.chatToolbarContent}>
        <GlobalTools
          selectedFiles={selectedFiles}
          selectedKnowledge={selectedKnowledge}
          onFileSelect={onFileSelect}
          onKnowledgeSelect={onKnowledgeSelect}
          onSettingsClick={onSettingsClick}
          showKnowledge={showKnowledge}
        />
      </div>

      {/* 已选引用（如果有） */}
      {totalReferences > 0 && (
        <div className={styles.selectedReferencesSection}>
          <SelectedReferences
            files={selectedFiles}
            knowledge={selectedKnowledge}
            onRemoveFile={(id) => {
              const newFiles = selectedFiles.filter(f => f.id !== id);
              onFileSelect(newFiles);
            }}
            onRemoveKnowledge={(id) => {
              const newKnowledge = selectedKnowledge.filter(k => k.id !== id);
              onKnowledgeSelect(newKnowledge);
            }}
            onClear={() => {
              onFileSelect([]);
              onKnowledgeSelect([]);
            }}
          />
        </div>
      )}
    </div>
  );
}
