// 全局工具组件

import { useState } from 'react';
import { Collapse, Button, Modal } from 'antd';
import {
  ThunderboltOutlined,
  HistoryOutlined,
  SettingOutlined,
  FolderOutlined,
  BookOutlined,
} from '@ant-design/icons';
import ModelSelector from '../../../pages/Chat/ModelSelector';
import ChatSessionDropdown from '../../../pages/Chat/components/ChatSessionDropdown';
import { FileTreeSelector } from './FileTreeSelector';
import { KnowledgeSelector } from './KnowledgeSelector';
import type { FileInfo, KnowledgeInfo } from '../types';

interface GlobalToolsProps {
  onSettingsClick?: () => void;
  selectedFiles?: FileInfo[];
  selectedKnowledge?: KnowledgeInfo[];
  onFileSelect?: (files: FileInfo[]) => void;
  onKnowledgeSelect?: (items: KnowledgeInfo[]) => void;
  showKnowledge?: boolean;
}

export function GlobalTools({ 
  onSettingsClick,
  selectedFiles = [],
  selectedKnowledge = [],
  onFileSelect,
  onKnowledgeSelect,
  showKnowledge = true,
}: GlobalToolsProps) {
  // 聊天历史弹窗
  const [historyModalOpen, setHistoryModalOpen] = useState(false);
  const [historySearchKeyword, setHistorySearchKeyword] = useState('');
  
  return (
    <div style={{ padding: '0 4px' }}>
      {/* 模型选择 */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ 
          fontSize: 14, 
          fontWeight: 500, 
          marginBottom: 8,
          display: 'flex',
          alignItems: 'center',
          gap: 8,
        }}>
          <ThunderboltOutlined /> 模型选择
        </div>
        <ModelSelector />
      </div>

      {/* 聊天历史按钮 */}
      <Button 
        icon={<HistoryOutlined />}
        onClick={() => setHistoryModalOpen(true)}
        block
        style={{ marginBottom: 16 }}
      >
        聊天历史
      </Button>

      {/* 我的空间（可展开） */}
      <Collapse
        style={{ marginBottom: 8 }}
        items={[
          {
            key: 'files',
            label: (
              <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <FolderOutlined /> 我的空间
                {selectedFiles.length > 0 && (
                  <span style={{ color: '#1890ff', fontSize: 12 }}>
                    ({selectedFiles.length})
                  </span>
                )}
              </span>
            ),
            children: onFileSelect ? (
              <FileTreeSelector
                selected={selectedFiles}
                onSelect={onFileSelect}
              />
            ) : null,
          },
        ]}
      />

      {/* 知识库（可展开，可选显示） */}
      {showKnowledge && onKnowledgeSelect && (
        <Collapse
          style={{ marginBottom: 8 }}
          items={[
            {
              key: 'knowledge',
              label: (
                <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <BookOutlined /> 知识库
                  {selectedKnowledge.length > 0 && (
                    <span style={{ color: '#1890ff', fontSize: 12 }}>
                      ({selectedKnowledge.length})
                    </span>
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
      )}

      {/* 显示设置 */}
      <Button 
        icon={<SettingOutlined />} 
        onClick={onSettingsClick}
        block
        style={{ marginTop: 8 }}
      >
        显示设置
      </Button>

      {/* 聊天历史弹窗 */}
      <Modal
        title="聊天历史"
        open={historyModalOpen}
        onCancel={() => setHistoryModalOpen(false)}
        footer={null}
        width={600}
      >
        <ChatSessionDropdown
          open={historyModalOpen}
          onClose={() => setHistoryModalOpen(false)}
          searchKeyword={historySearchKeyword}
          showSearch={true}
          onSearchChange={setHistorySearchKeyword}
        />
      </Modal>
    </div>
  );
}
