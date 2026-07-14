// 全局工具组件

import { useState } from 'react';
import { Collapse, Input, Button } from 'antd';
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
  showKnowledge?: boolean;  // 是否显示知识库
}

/**
 * 全局工具列表
 * 包含模型选择、聊天历史、我的空间、知识库、显示设置
 */
export function GlobalTools({ 
  onSettingsClick,
  selectedFiles = [],
  selectedKnowledge = [],
  onFileSelect,
  onKnowledgeSelect,
  showKnowledge = true,
}: GlobalToolsProps) {
  const [historySearchKeyword, setHistorySearchKeyword] = useState('');
  const [historyOpen, setHistoryOpen] = useState(false);
  
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

      {/* 聊天历史 */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ 
          fontSize: 14, 
          fontWeight: 500, 
          marginBottom: 8,
          display: 'flex',
          alignItems: 'center',
          gap: 8,
        }}>
          <HistoryOutlined /> 聊天历史
        </div>
        <Input.Search
          placeholder="搜索聊天历史..."
          allowClear
          onSearch={setHistorySearchKeyword}
          style={{ marginBottom: 8 }}
        />
        <div style={{ 
          maxHeight: 300, 
          overflowY: 'auto',
          border: '1px solid #f0f0f0',
          borderRadius: 8,
        }}>
          <ChatSessionDropdown 
            open={historyOpen}
            onClose={() => setHistoryOpen(false)}
            searchKeyword={historySearchKeyword}
          />
        </div>
      </div>

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
    </div>
  );
}
