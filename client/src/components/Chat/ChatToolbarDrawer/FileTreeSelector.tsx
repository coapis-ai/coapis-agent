// 文件树选择器组件

import { useState, useEffect, useMemo } from 'react';
import { Tree, Input, Button, Empty, Spin, Tag } from 'antd';
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

  // 统计选中的文件和文件夹数量
  const selectedFiles = selected.filter(item => item.type === 'file');
  const selectedFolders = selected.filter(item => item.type === 'folder');

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

      {/* 已选统计 */}
      {selected.length > 0 && (
        <div style={{ 
          marginTop: 8,
          padding: '8px 0',
          borderTop: '1px solid #f0f0f0',
        }}>
          <div style={{ 
            display: 'flex', 
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 4,
          }}>
            <span style={{ fontSize: 12, color: '#666' }}>
              已选择 {selected.length} 项
            </span>
            <Button type="link" size="small" onClick={() => onSelect([])}>
              清空
            </Button>
          </div>
          
          {/* 分类显示 */}
          {selectedFolders.length > 0 && (
            <div style={{ marginBottom: 4 }}>
              <Tag color="blue" style={{ fontSize: 11 }}>
                <FolderOutlined /> {selectedFolders.length} 个工作路径
              </Tag>
            </div>
          )}
          {selectedFiles.length > 0 && (
            <div>
              <Tag color="green" style={{ fontSize: 11 }}>
                <FileOutlined /> {selectedFiles.length} 个文件
              </Tag>
            </div>
          )}
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
