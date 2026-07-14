// 文件树数据加载 Hook

import { useState, useEffect, useCallback, useMemo } from 'react';
import { message } from 'antd';
import { fileApi } from '@/api/modules/file';
import type { FileNode } from '../types';

/**
 * 文件树数据加载和管理
 */
export function useFileTree() {
  const [loading, setLoading] = useState(false);
  const [fileTree, setFileTree] = useState<FileNode[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [searchText, setSearchText] = useState('');
  const [expandedKeys, setExpandedKeys] = useState<string[]>([]);

  // 加载文件树
  const loadFileTree = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fileApi.getFileTree();
      setFileTree(response.tree || []);
    } catch (err: any) {
      console.error('Failed to load file tree:', err);
      setError(err.message || '加载文件树失败');
      message.error('加载文件树失败');
    } finally {
      setLoading(false);
    }
  }, []);

  // 初始加载
  useEffect(() => {
    loadFileTree();
  }, [loadFileTree]);

  // 过滤文件树
  const filteredTree = useMemo(() => {
    if (!searchText) return fileTree;
    return filterTree(fileTree, searchText.toLowerCase());
  }, [fileTree, searchText]);

  // 搜索文件
  const handleSearch = useCallback((text: string) => {
    setSearchText(text);
    // 搜索时自动展开所有匹配的目录
    if (text) {
      const matchedKeys = findMatchedKeys(fileTree, text.toLowerCase());
      setExpandedKeys(matchedKeys);
    }
  }, [fileTree]);

  // 刷新文件树
  const refresh = useCallback(() => {
    loadFileTree();
  }, [loadFileTree]);

  return {
    loading,
    fileTree,
    filteredTree,
    error,
    searchText,
    setSearchText: handleSearch,
    expandedKeys,
    setExpandedKeys,
    refresh,
  };
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

// 辅助函数：查找匹配的节点keys
function findMatchedKeys(nodes: FileNode[], searchText: string): string[] {
  const keys: string[] = [];

  function traverse(node: FileNode, parentKeys: string[]) {
    const currentKeys = [...parentKeys, node.id];

    if (node.name.toLowerCase().includes(searchText)) {
      keys.push(...parentKeys); // 展开所有父节点
    }

    if (node.children) {
      node.children.forEach(child => traverse(child, currentKeys));
    }
  }

  nodes.forEach(node => traverse(node, []));
  return [...new Set(keys)]; // 去重
}
