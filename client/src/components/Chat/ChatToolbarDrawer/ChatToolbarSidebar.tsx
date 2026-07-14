// ChatToolbarSidebar 侧边栏组件（非Drawer版本）

import { useState, useEffect } from 'react';
import { Tabs } from 'antd';
import { PinButton } from './PinButton';
import { FileTreeSelector } from './FileTreeSelector';
import { KnowledgeSelector } from './KnowledgeSelector';
import { SelectedReferences } from './SelectedReferences';
import type { FileInfo, KnowledgeInfo } from '../types';
import styles from './Sidebar.module.less';

const TOOLBAR_PINNED_KEY = 'chat-toolbar-pinned';

interface ChatToolbarSidebarProps {
  onFileSelect: (files: FileInfo[]) => void;
  onKnowledgeSelect: (items: KnowledgeInfo[]) => void;
  selectedFiles?: FileInfo[];
  selectedKnowledge?: KnowledgeInfo[];
  showPinButton?: boolean;
  onPinToggle?: (pinned: boolean) => void;
  defaultPinned?: boolean;
}

/**
 * 聊天工具栏侧边栏组件
 * 
 * 功能：
 * - 侧边栏形式显示（不使用Drawer）
 * - 支持固定显示（PC端）
 * - 包含全局工具、文件选择器、知识库选择器、已选引用
 */
export function ChatToolbarSidebar({
  onFileSelect,
  onKnowledgeSelect,
  selectedFiles = [],
  selectedKnowledge = [],
  showPinButton = true,
  onPinToggle,
  defaultPinned = false,
}: ChatToolbarSidebarProps) {
  // 固定状态
  const [pinned, setPinned] = useState(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem(TOOLBAR_PINNED_KEY) === 'true';
    }
    return defaultPinned;
  });

  // 当前标签页
  const [activeTab, setActiveTab] = useState<'tools' | 'files' | 'knowledge' | 'references'>('files');

  // 保存固定状态
  useEffect(() => {
    if (typeof window !== 'undefined') {
      localStorage.setItem(TOOLBAR_PINNED_KEY, String(pinned));
      onPinToggle?.(pinned);
    }
  }, [pinned, onPinToggle]);

  // 计算总引用数
  const totalReferences = selectedFiles.length + selectedKnowledge.length;

  // 标签页配置
  const tabs = [
    {
      key: 'files',
      label: `文件 ${selectedFiles.length > 0 ? `(${selectedFiles.length})` : ''}`,
      children: (
        <FileTreeSelector
          selected={selectedFiles}
          onSelect={onFileSelect}
        />
      ),
    },
    {
      key: 'knowledge',
      label: `知识库 ${selectedKnowledge.length > 0 ? `(${selectedKnowledge.length})` : ''}`,
      children: (
        <KnowledgeSelector
          selected={selectedKnowledge}
          onSelect={onKnowledgeSelect}
        />
      ),
    },
    {
      key: 'references',
      label: `已选引用 (${totalReferences})`,
      children: (
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
      ),
    },
  ];

  return (
    <div className={styles.chatToolbarSidebar}>
      {/* 标题栏 */}
      <div className={styles.chatToolbarHeader}>
        <span>工具栏</span>
        {showPinButton && (
          <PinButton
            pinned={pinned}
            onToggle={() => setPinned(!pinned)}
          />
        )}
      </div>

      {/* 标签页内容 */}
      <Tabs
        activeKey={activeTab}
        onChange={(key) => setActiveTab(key as any)}
        className={styles.chatToolbarTabs}
        items={tabs}
      />
    </div>
  );
}
