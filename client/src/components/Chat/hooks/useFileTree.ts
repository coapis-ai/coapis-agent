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
function convertToTree(items: BackendFileInfo[]): FileNode[] {
  return items.map(item => {
    const node: FileNode = {
      id: item.path,
      name: item.name,
      path: item.path,
      type: item.type === 'directory' ? 'folder' : 'file',
      size: item.size,
      mimeType: item.mimeType,
    };

    // 目录可能有子项（但后端没有返回，需要前端异步加载）
    if (item.type === 'directory') {
      node.children = [];
    }

    return node;
  });
}

/**
 * 文件树加载 Hook
 * 
 * 功能：
 * - 加载文件列表并转换为树形结构
 * - 支持搜索过滤
 */
export function useFileTree() {
  const [treeData, setTreeData] = useState<FileNode[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchText, setSearchText] = useState('');

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
      const tree = convertToTree(data.items);
      setTreeData(tree);
    } catch (error) {
      console.error('Failed to load file tree:', error);
      message.error('加载文件列表失败');
      setTreeData([]);
    } finally {
      setLoading(false);
    }
  }, []);

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

  return {
    treeData: filteredTree,
    loading,
    searchText,
    setSearchText,
    refresh: () => loadFiles('/'),
  };
}
