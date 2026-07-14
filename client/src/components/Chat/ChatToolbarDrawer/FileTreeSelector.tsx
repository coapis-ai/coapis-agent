# 文件选择器组件（更新：使用真实API）

import { useMemo } from 'react';
import { Tree, Input, Empty, Spin, Button } from 'antd';
import { SearchOutlined, FolderOutlined, FileOutlined, ReloadOutlined } from '@ant-design/icons';
import { useFileTree } from '../hooks/useFileTree';
import type { FileInfo, FileNode } from '../types';
import './index.module.less';

interface FileTreeSelectorProps {
  selected: FileInfo[];
  onSelect: (files: FileInfo[]) => void;
}

/**
 * 文件树选择器
 * 
 * 功能：
 * - 树形结构展示文件
 * - 支持搜索过滤
 * - 支持多选（复选框）
 * - 显示文件大小、类型图标
 */
export function FileTreeSelector({ selected, onSelect }: FileTreeSelectorProps) {
  const {
    loading,
    filteredTree,
    error,
    searchText,
    setSearchText,
    expandedKeys,
    setExpandedKeys,
    refresh,
  } = useFileTree();

  // 转换为 Tree 组件数据格式
  const treeData = useMemo(() => {
    return convertToTreeData(filteredTree);
  }, [filteredTree]);

  // 处理选择
  const handleCheck = (checkedKeys: any) => {
    const files = findFilesByIds(filteredTree, checkedKeys as string[]);
    onSelect(files);
  };

  return (
    <div className="chat-toolbar-file-tree">
      {/* 搜索框和刷新按钮 */}
      <div className="search-box">
        <Input
          placeholder="搜索文件..."
          prefix={<SearchOutlined />}
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          allowClear
          suffix={
            <Button
              type="text"
              size="small"
              icon={<ReloadOutlined />}
              onClick={refresh}
              title="刷新"
            />
          }
        />
      </div>

      {/* 错误提示 */}
      {error && (
        <div className="error-message" style={{ padding: 16, color: '#ff4d4f' }}>
          {error}
        </div>
      )}

      {/* 文件树 */}
      <div className="file-tree-container">
        {loading ? (
          <div className="loading-container">
            <Spin />
          </div>
        ) : treeData.length > 0 ? (
          <Tree
            checkable
            checkedKeys={selected.map((f) => f.id)}
            expandedKeys={expandedKeys}
            onExpand={setExpandedKeys}
            onCheck={handleCheck}
            treeData={treeData}
            selectable={false}
            showIcon
          />
        ) : (
          <Empty 
            description={searchText ? "未找到匹配的文件" : "暂无文件"} 
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          />
        )}
      </div>

      {/* 已选数量 */}
      {selected.length > 0 && (
        <div className="selected-count">
          已选择 {selected.length} 个文件
          <Button type="link" size="small" onClick={() => onSelect([])}>
            清空
          </Button>
        </div>
      )}
    </div>
  );
}

// 辅助函数：转换文件树数据
function convertToTreeData(nodes: FileNode[]): any[] {
  return nodes.map((node) => ({
    key: node.id,
    title: (
      <span>
        {node.name}
        {node.size && <span style={{ marginLeft: 8, color: '#999', fontSize: 12 }}>
          {formatFileSize(node.size)}
        </span>}
      </span>
    ),
    icon: node.type === 'folder' ? <FolderOutlined /> : <FileOutlined />,
    children: node.children ? convertToTreeData(node.children) : undefined,
  }));
}

// 辅助函数：根据ID查找文件
function findFilesByIds(nodes: FileNode[], ids: string[]): FileInfo[] {
  const files: FileInfo[] = [];
  
  function traverse(node: FileNode) {
    if (ids.includes(node.id) && node.type === 'file') {
      files.push({
        id: node.id,
        name: node.name,
        path: node.path,
        type: node.type,
        size: node.size,
        mimeType: node.mimeType,
      });
    }
    if (node.children) {
      node.children.forEach(traverse);
    }
  }
  
  nodes.forEach(traverse);
  return files;
}

// 辅助函数：格式化文件大小
function formatFileSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}
