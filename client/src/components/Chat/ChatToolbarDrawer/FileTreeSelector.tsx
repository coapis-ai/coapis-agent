# 文件选择器组件

import { useState, useEffect, useMemo } from 'react';
import { Tree, Input, Empty, Spin, Button } from 'antd';
import { SearchOutlined, FolderOutlined, FileOutlined } from '@ant-design/icons';
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
  const [loading, setLoading] = useState(false);
  const [fileTree, setFileTree] = useState<FileNode[]>([]);
  const [searchText, setSearchText] = useState('');
  const [expandedKeys, setExpandedKeys] = useState<string[]>([]);

  // TODO: 加载文件树（后续对接API）
  useEffect(() => {
    // 模拟数据
    setLoading(true);
    setTimeout(() => {
      setFileTree([
        {
          id: 'folder-1',
          name: '文档',
          path: '/文档',
          type: 'folder',
          children: [
            { id: 'file-1', name: '需求文档.docx', path: '/文档/需求文档.docx', type: 'file', size: 102400 },
            { id: 'file-2', name: '设计文档.pdf', path: '/文档/设计文档.pdf', type: 'file', size: 204800 },
          ],
        },
        {
          id: 'folder-2',
          name: '图片',
          path: '/图片',
          type: 'folder',
          children: [
            { id: 'file-3', name: 'logo.png', path: '/图片/logo.png', type: 'file', size: 51200 },
          ],
        },
      ]);
      setLoading(false);
    }, 500);
  }, []);

  // 过滤文件树
  const filteredTree = useMemo(() => {
    if (!searchText) return fileTree;
    return filterTree(fileTree, searchText.toLowerCase());
  }, [fileTree, searchText]);

  // 转换为 Tree 组件数据格式
  const treeData = useMemo(() => {
    return convertToTreeData(filteredTree);
  }, [filteredTree]);

  // 处理选择
  const handleCheck = (checkedKeys: any) => {
    const files = findFilesByIds(fileTree, checkedKeys as string[]);
    onSelect(files);
  };

  return (
    <div className="chat-toolbar-file-tree">
      {/* 搜索框 */}
      <div className="search-box">
        <Input
          placeholder="搜索文件..."
          prefix={<SearchOutlined />}
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          allowClear
        />
      </div>

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
          <Empty description="暂无文件" />
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

// 辅助函数：过滤文件树
function filterTree(nodes: FileNode[], searchText: string): FileNode[] {
  return nodes
    .map((node) => {
      if (node.children) {
        const filteredChildren = filterTree(node.children, searchText);
        if (filteredChildren.length > 0 || node.name.toLowerCase().includes(searchText)) {
          return { ...node, children: filteredChildren };
        }
        return null;
      }
      return node.name.toLowerCase().includes(searchText) ? node : null;
    })
    .filter(Boolean) as FileNode[];
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
