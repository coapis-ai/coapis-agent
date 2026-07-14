// 文件树选择器组件

import { useState, useMemo } from 'react';
import { Tree, Input, Button, Empty } from 'antd';
import { SearchOutlined, ReloadOutlined, FileOutlined, FolderOutlined } from '@ant-design/icons';
import { useFileTree } from '../hooks/useFileTree';
import type { FileInfo, FileNode } from '../types';

interface FileTreeSelectorProps {
  selected: FileInfo[];
  onSelect: (files: FileInfo[]) => void;
}

/**
 * 文件树选择器
 * 
 * 功能：
 * - 树形展示文件和目录
 * - 支持搜索过滤
 * - 支持多选（复选框）
 * - 显示文件大小、类型图标
 */
export function FileTreeSelector({ selected, onSelect }: FileTreeSelectorProps) {
  const { treeData, loading, searchText, setSearchText, refresh } = useFileTree();
  const [expandedKeys, setExpandedKeys] = useState<string[]>([]);

  // 转换为 Tree 组件数据格式
  const treeDataForAntd = useMemo(() => {
    return convertToTreeData(treeData);
  }, [treeData]);

  // 处理选择
  const handleCheck = (checkedKeys: any) => {
    const files = findFilesByIds(treeData, checkedKeys as string[]);
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
        />
        <Button
          type="text"
          icon={<ReloadOutlined />}
          onClick={refresh}
          loading={loading}
          title="刷新"
        />
      </div>

      {/* 文件树 */}
      <div className="file-tree-container">
        {treeDataForAntd.length > 0 ? (
          <Tree
            checkable
            checkedKeys={selected.map((f) => f.id)}
            expandedKeys={expandedKeys}
            onExpand={(keys) => setExpandedKeys(keys as string[])}
            onCheck={handleCheck}
            treeData={treeDataForAntd}
            selectable={false}
            showIcon
          />
        ) : (
          <Empty description="暂无文件" />
        )}
      </div>

      {/* 已选文件数量 */}
      {selected.length > 0 && (
        <div className="selected-count">
          <span>已选择 {selected.length} 个文件</span>
          <Button type="link" size="small" onClick={() => onSelect([])}>
            清空
          </Button>
        </div>
      )}
    </div>
  );
}

// 辅助函数：转换树数据格式
function convertToTreeData(nodes: FileNode[]): any[] {
  return nodes.map(node => ({
    key: node.id,
    title: node.name,
    icon: node.type === 'folder' ? <FolderOutlined /> : <FileOutlined />,
    children: node.children ? convertToTreeData(node.children) : undefined,
  }));
}

// 辅助函数：根据ID查找文件
function findFilesByIds(nodes: FileNode[], ids: string[]): FileInfo[] {
  const files: FileInfo[] = [];
  
  function traverse(node: FileNode) {
    if (ids.includes(node.id)) {
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
