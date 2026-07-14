// 文件树选择器组件

import { useState, useMemo, useEffect } from 'react';
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
 * - 点击文件夹可展开/收缩
 */
export function FileTreeSelector({ selected, onSelect }: FileTreeSelectorProps) {
  const { treeData, loading, searchText, setSearchText, refresh } = useFileTree();
  const [expandedKeys, setExpandedKeys] = useState<string[]>([]);

  // 转换为 Tree 组件数据格式
  const treeDataForAntd = useMemo(() => {
    console.log('🔍 FileTreeSelector - treeData:', treeData);
    const converted = convertToTreeData(treeData);
    console.log('🔍 FileTreeSelector - treeDataForAntd:', converted);
    return converted;
  }, [treeData]);

  // 默认展开所有文件夹
  useEffect(() => {
    if (treeData.length > 0 && expandedKeys.length === 0) {
      const folderKeys = getAllFolderKeys(treeData);
      setExpandedKeys(folderKeys);
    }
  }, [treeData]);

  // 处理选择
  const handleCheck = (checkedKeys: any) => {
    const files = findFilesByIds(treeData, checkedKeys as string[]);
    onSelect(files);
  };

  // 处理展开/收缩
  const handleExpand = (keys: React.Key[]) => {
    setExpandedKeys(keys as string[]);
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
      {treeDataForAntd.length > 0 ? (
        <Tree
          checkable
          checkedKeys={selected.map((f) => f.id)}
          expandedKeys={expandedKeys}
          onExpand={handleExpand}
          onCheck={handleCheck}
          onSelect={(_selectedKeys, info) => {
            // 点击节点内容时，如果是文件夹则展开/收缩
            const node = info.node as any;
            const isFolder = node.isFolder || node.icon?.type?.displayName === 'FolderOutlined';
            
            if (isFolder) {
              const key = node.key as string;
              if (expandedKeys.includes(key)) {
                setExpandedKeys(expandedKeys.filter(k => k !== key));
              } else {
                setExpandedKeys([...expandedKeys, key]);
              }
            }
          }}
          treeData={treeDataForAntd}
          selectable={true}
          showIcon
          blockNode
        />
      ) : (
        <Empty description="暂无文件" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      )}

      {/* 已选文件数量 */}
      {selected.length > 0 && (
        <div style={{ 
          display: 'flex', 
          justifyContent: 'space-between', 
          alignItems: 'center',
          marginTop: 8,
          padding: '8px 0',
          borderTop: '1px solid #f0f0f0',
        }}>
          <span style={{ fontSize: 12, color: '#666' }}>
            已选择 {selected.length} 个文件
          </span>
          <Button type="link" size="small" onClick={() => onSelect([])}>
            清空
          </Button>
        </div>
      )}
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
    // 只有当 children 有内容时才传递，否则传 undefined（空数组会导致无法展开）
    children: node.children && node.children.length > 0 ? convertToTreeData(node.children) : undefined,
    isFolder: node.type === 'folder',  // 标记是否为文件夹
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
