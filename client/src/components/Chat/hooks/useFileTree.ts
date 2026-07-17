// 文件树数据加载 Hook

import { useState, useEffect, useCallback, useMemo } from 'react';
import { message } from 'antd';
import type { FileNode } from '../types';
import { buildAuthHeaders } from '@/api/authHeaders';

interface BackendFileInfo {
  name: string;
  type: 'file' | 'directory';
  path: string;
  size: number;
  mimeType: string;
  previewable: boolean;
  downloadable: boolean;
  modified?: string;
  items_count?: number;
}

interface BackendFileListResponse {
  items: BackendFileInfo[];
  total: number;
  path: string;
}

/**
 * 将后端文件列表转换为树形结构
 */
function convertToTree(items: BackendFileInfo[], parentPath: string = ''): FileNode[] {
  return items.map(item => {
    // 构建完整路径
    const fullPath = item.path.startsWith('/') ? item.path : `${parentPath}/${item.path}`.replace(/\/+/g, '/');
    
    const node: FileNode = {
      id: fullPath,
      name: item.name,
      path: fullPath,
      type: item.type === 'directory' ? 'folder' : 'file',
      size: item.size,
      mimeType: item.mimeType,
    };

    // 目录标记为可展开（但不预加载子项）
    if (item.type === 'directory') {
      node.children = undefined; // 使用 undefined 表示未加载
    }

    return node;
  });
}

/**
 * 文件树加载 Hook
 * 
 * 功能：
 * - 加载文件列表并转换为树形结构
 * - 支持异步加载子目录
 * - 支持搜索过滤
 */
export function useFileTree() {
  const [treeData, setTreeData] = useState<FileNode[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchText, setSearchText] = useState('');
  const [loadedPaths, setLoadedPaths] = useState<Set<string>>(new Set());

  // 加载文件列表
  const loadFiles = useCallback(async (path: string = '/') => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        path: path,
        category: 'files',
        page_size: '1000',
      });

      const response = await fetch(`/api/myfiles/list?${params}`, {
        headers: buildAuthHeaders(),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const data: BackendFileListResponse = await response.json();
      
      // 转换为树形结构
      const tree = convertToTree(data.items, path);
      
      if (path === '/') {
        // 根目录，直接设置
        setTreeData(tree);
        setLoadedPaths(new Set(['/']));
      } else {
        // 子目录，更新到对应的节点
        setTreeData(prevTree => {
          return updateNodeChildren(prevTree, path, tree);
        });
        setLoadedPaths(prev => new Set(prev).add(path));
      }
    } catch (error) {
      console.error('Failed to load file tree:', error);
      message.error('加载文件列表失败');
      if (path === '/') {
        setTreeData([]);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  // 加载指定目录的内容（用于异步展开）
  const loadDirectory = useCallback(async (directoryPath: string) => {
    // 如果已经加载过，跳过
    if (loadedPaths.has(directoryPath)) {
      return;
    }
    
    await loadFiles(directoryPath);
  }, [loadedPaths, loadFiles]);

  // 初始加载
  useEffect(() => {
    loadFiles('/');
  }, [loadFiles]);

  // 搜索过滤
  const filteredTree = useMemo(() => {
    if (!searchText) return treeData;
    
    const search = searchText.toLowerCase();
    const filterNode = (nodes: FileNode[]): FileNode[] => {
      return nodes.reduce<FileNode[]>((acc, node) => {
        const matches = node.name.toLowerCase().includes(search);
        const childMatches = node.children ? filterNode(node.children) : [];
        
        if (matches || childMatches.length > 0) {
          acc.push({
            ...node,
            children: childMatches.length > 0 ? childMatches : node.children,
          });
        }
        
        return acc;
      }, []);
    };
    
    return filterNode(treeData);
  }, [treeData, searchText]);

  // 刷新
  const refresh = useCallback(() => {
    setLoadedPaths(new Set());
    loadFiles('/');
  }, [loadFiles]);

  return {
    treeData: filteredTree,
    loading,
    searchText,
    setSearchText,
    refresh,
    loadDirectory,
    loadedPaths,
  };
}

// 辅助函数：更新指定路径节点的子节点
function updateNodeChildren(nodes: FileNode[], targetPath: string, newChildren: FileNode[]): FileNode[] {
  return nodes.map(node => {
    if (node.path === targetPath) {
      // 找到目标节点，更新子节点
      return {
        ...node,
        children: newChildren,
      };
    }
    
    // 递归查找
    if (node.children) {
      return {
        ...node,
        children: updateNodeChildren(node.children, targetPath, newChildren),
      };
    }
    
    return node;
  });
}
