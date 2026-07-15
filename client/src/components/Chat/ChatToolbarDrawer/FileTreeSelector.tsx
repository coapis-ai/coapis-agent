// 文件树选择器组件

import { useState, useEffect, useMemo } from 'react';
import { Tree, Input, Button, Empty, Spin } from 'antd';
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
 * - 文件和文件夹都可以被选中
 * - 选中文件夹：设置对话工作路径，可能涉及文件夹下的文件
 * - 选中文件：明确使用该文件
 * - 支持搜索过滤
 */
export function FileTreeSelector({ selected, onSelect }: FileTreeSelectorProps) {
  const { treeData, loading, searchText, setSearchText, refresh } = useFileTree();
  const [expandedKeys, setExpandedKeys] = useState<string[]>([]);

  // 转换为 Tree 组件数据格式
  const treeDataForAntd = useMemo(() => {
    return convertToTreeData(treeData);
  }, [treeData]);

  // 默认展开所有文件夹
  useEffect(() => {
    if (treeData.length > 0 && expandedKeys.length === 0) {
      const folderKeys = getAllFolderKeys(treeData);
      setExpandedKeys(folderKeys);
    }
  }, [treeData]);

  // 处理选择（文件和文件夹都可以选中）
  const handleCheck = (checkedKeys: any) => {
    const items = findItemsByIds(treeData, checkedKeys as string[]);
    onSelect(items);
  };

  return (
    <div style={{ maxHeight: 300, overflowY: 'auto' }}>
      {/* 搜索框和刷新按钮 */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
        <Input
          placeholder="搜索文件..."
          prefix={<SearchOutlined />}
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          allowClear
          size="small"
        />
        <Button
          type="text"
          icon={<ReloadOutlined />}
          onClick={refresh}
          loading={loading}
          title="刷新"
          size="small"
        />
      </div>

      {/* 文件树 */}
      <Spin spinning={loading}>
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
            blockNode
          />
        ) : (
          <Empty 
            description="暂无文件" 
            image={Empty.PRESENTED_IMAGE_SIMPLE} 
          />
        )}
      </Spin>
    </div>
  );
}

// 辅助函数：获取所有文件夹的key
function getAllFolderKeys(nodes: FileNode[]): string[] {
  const keys: string[] = [];
  
  function traverse(node: FileNode) {
    if (node.type === 'folder') {
      keys.push(node.id);
      if (node.children) {
        node.children.forEach(traverse);
      }
    }
  }
  
  nodes.forEach(traverse);
  return keys;
}

// 辅助函数：转换树数据格式
function convertToTreeData(nodes: FileNode[]): any[] {
  return nodes.map(node => ({
    key: node.id,
    title: node.name,
    icon: node.type === 'folder' ? <FolderOutlined /> : <FileOutlined />,
    children: node.children && node.children.length > 0 ? convertToTreeData(node.children) : undefined,
    isLeaf: node.type === 'file',
  }));
}

// 辅助函数：根据ID查找文件或文件夹
function findItemsByIds(nodes: FileNode[], ids: string[]): FileInfo[] {
  const items: FileInfo[] = [];
  
  function traverse(node: FileNode) {
    if (ids.includes(node.id)) {
      items.push({
        id: node.id,
        name: node.name,
        path: node.path,
        type: node.type,  // 保留类型，可以是 'file' 或 'folder'
        size: node.size,
        mimeType: node.mimeType,
      });
    }
    if (node.children) {
      node.children.forEach(traverse);
    }
  }
  
  nodes.forEach(traverse);
  return items;
}
