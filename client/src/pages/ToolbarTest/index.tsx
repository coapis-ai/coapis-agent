# 工具栏测试页面

import { useState } from 'react';
import { Button, Card, Space, message } from 'antd';
import { MenuOutlined } from '@ant-design/icons';
import { ChatToolbarDrawer } from '@/components/Chat';
import type { FileInfo, KnowledgeInfo } from '@/components/Chat';
import './ToolbarTest.module.less';

/**
 * 工具栏测试页面
 * 用于验证 ChatToolbarDrawer 组件功能
 */
export function ToolbarTestPage() {
  const [toolbarOpen, setToolbarOpen] = useState(false);
  const [selectedFiles, setSelectedFiles] = useState<FileInfo[]>([]);
  const [selectedKnowledge, setSelectedKnowledge] = useState<KnowledgeInfo[]>([]);

  const handleFileSelect = (files: FileInfo[]) => {
    setSelectedFiles(files);
    message.success(`已选择 ${files.length} 个文件`);
  };

  const handleKnowledgeSelect = (items: KnowledgeInfo[]) => {
    setSelectedKnowledge(items);
    message.success(`已选择 ${items.length} 个知识库`);
  };

  return (
    <div className="toolbar-test-page">
      <Card title="工具栏测试" style={{ maxWidth: 800, margin: '0 auto' }}>
        <Space direction="vertical" style={{ width: '100%' }}>
          {/* 打开工具栏按钮 */}
          <Button
            icon={<MenuOutlined />}
            onClick={() => setToolbarOpen(true)}
          >
            打开工具栏
          </Button>

          {/* 已选文件 */}
          <div>
            <strong>已选文件：</strong>
            {selectedFiles.length > 0 ? (
              <ul>
                {selectedFiles.map(file => (
                  <li key={file.id}>{file.name} ({file.path})</li>
                ))}
              </ul>
            ) : (
              <span style={{ color: '#999' }}>未选择</span>
            )}
          </div>

          {/* 已选知识库 */}
          <div>
            <strong>已选知识库：</strong>
            {selectedKnowledge.length > 0 ? (
              <ul>
                {selectedKnowledge.map(item => (
                  <li key={item.id}>{item.name} - {item.description}</li>
                ))}
              </ul>
            ) : (
              <span style={{ color: '#999' }}>未选择</span>
            )}
          </div>

          {/* 使用说明 */}
          <Card type="inner" title="功能说明">
            <ul>
              <li>点击"打开工具栏"按钮，左侧会展开工具栏</li>
              <li>工具栏包含：工具、文件、知识库三个标签页</li>
              <li>PC端可以看到"固定"按钮，点击后工具栏不会自动收起</li>
              <li>文件标签页：树形结构，支持搜索、多选</li>
              <li>知识库标签页：列表展示，支持多选</li>
              <li>底部显示已选引用</li>
            </ul>
          </Card>
        </Space>
      </Card>

      {/* 工具栏抽屉 */}
      <ChatToolbarDrawer
        visible={toolbarOpen}
        onClose={() => setToolbarOpen(false)}
        selectedFiles={selectedFiles}
        selectedKnowledge={selectedKnowledge}
        onFileSelect={handleFileSelect}
        onKnowledgeSelect={handleKnowledgeSelect}
      />
    </div>
  );
}
