# ChatToolbarDrawer 主组件

import { useState, useEffect, useCallback } from 'react';
import { Drawer, Tabs, Button, Tooltip } from 'antd';
import { MenuOutlined } from '@ant-design/icons';
import { PinButton } from './PinButton';
import { GlobalTools } from './GlobalTools';
import { FileTreeSelector } from './FileTreeSelector';
import { KnowledgeSelector } from './KnowledgeSelector';
import { SelectedReferences } from './SelectedReferences';
import useIsMobile from '@/hooks/useIsMobile';
import type { FileInfo, KnowledgeInfo } from '../types';
import './index.module.less';

const TOOLBAR_PINNED_KEY = 'chat-toolbar-pinned';

interface ChatToolbarDrawerProps {
  visible: boolean;
  onClose: () => void;
  onFileSelect: (files: FileInfo[]) => void;
  onKnowledgeSelect: (items: KnowledgeInfo[]) => void;
  selectedFiles?: FileInfo[];
  selectedKnowledge?: KnowledgeInfo[];
}

/**
 * 聊天工具栏抽屉组件
 * 
 * 功能：
 * - 左侧抽屉式工具栏
 * - 支持固定显示（PC端）
 * - 包含全局工具、文件选择器、知识库选择器
 */
export function ChatToolbarDrawer({
  visible,
  onClose,
  onFileSelect,
  onKnowledgeSelect,
  selectedFiles = [],
  selectedKnowledge = [],
}: ChatToolbarDrawerProps) {
  const isMobile = useIsMobile();
  
  // 固定状态（从 localStorage 读取）
  const [pinned, setPinned] = useState(() => {
    if (isMobile) return false; // 移动端不支持固定
    return localStorage.getItem(TOOLBAR_PINNED_KEY) === 'true';
  });

  // 当前标签页
  const [activeTab, setActiveTab] = useState<'tools' | 'files' | 'knowledge'>('tools');

  // 保存固定状态到 localStorage
  useEffect(() => {
    localStorage.setItem(TOOLBAR_PINNED_KEY, String(pinned));
  }, [pinned]);

  // 处理关闭
  const handleClose = useCallback(() => {
    if (!pinned) {
      onClose();
    }
  }, [pinned, onClose]);

  // 移动端不显示固定按钮
  const showPinButton = !isMobile;

  // 计算总引用数
  const totalReferences = selectedFiles.length + selectedKnowledge.length;

  return (
    <Drawer
      placement="left"
      open={visible}
      onClose={handleClose}
      mask={!pinned}  // 固定时不显示遮罩
      maskClosable={!pinned}  // 固定时点击遮罩不关闭
      width={isMobile ? '100%' : 320}
      title={
        <div className="chat-toolbar-header">
          <span>工具栏</span>
          {showPinButton && (
            <PinButton
              pinned={pinned}
              onToggle={() => setPinned(!pinned)}
            />
          )}
        </div>
      }
      className={`chat-toolbar-drawer ${pinned ? 'pinned' : ''}`}
      styles={{
        body: { padding: 0 },
      }}
    >
      {/* 标签页 */}
      <Tabs
        activeKey={activeTab}
        onChange={(key) => setActiveTab(key as any)}
        className="chat-toolbar-tabs"
        items={[
          {
            key: 'tools',
            label: '工具',
            children: <GlobalTools />,
          },
          {
            key: 'files',
            label: (
              <span>
                文件
                {selectedFiles.length > 0 && (
                  <span className="chat-toolbar-badge">{selectedFiles.length}</span>
                )}
              </span>
            ),
            children: (
              <FileTreeSelector
                selected={selectedFiles}
                onSelect={onFileSelect}
              />
            ),
          },
          {
            key: 'knowledge',
            label: (
              <span>
                知识库
                {selectedKnowledge.length > 0 && (
                  <span className="chat-toolbar-badge">{selectedKnowledge.length}</span>
                )}
              </span>
            ),
            children: (
              <KnowledgeSelector
                selected={selectedKnowledge}
                onSelect={onKnowledgeSelect}
              />
            ),
          },
        ]}
      />

      {/* 已选引用 */}
      {totalReferences > 0 && (
        <SelectedReferences
          files={selectedFiles}
          knowledge={selectedKnowledge}
          onRemoveFile={(id) => {
            onFileSelect(selectedFiles.filter(f => f.id !== id));
          }}
          onRemoveKnowledge={(id) => {
            onKnowledgeSelect(selectedKnowledge.filter(k => k.id !== id));
          }}
          onClear={() => {
            onFileSelect([]);
            onKnowledgeSelect([]);
          }}
        />
      )}
    </Drawer>
  );
}
