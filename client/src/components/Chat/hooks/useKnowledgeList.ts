// 知识库列表数据加载 Hook

import { useState, useEffect, useCallback } from 'react';
import { message } from 'antd';
import type { KnowledgeInfo } from '../types';
import { buildAuthHeaders } from '@/api/authHeaders';

interface BackendKnowledgeBase {
  id: string;
  name: string;
  description: string;
  scope: string;
  status: string;
  chunk_count: number;
  config: Record<string, unknown>;
  created_at: number;
  updated_at: number;
}

interface BackendKnowledgeListResponse {
  bases: BackendKnowledgeBase[];
  total: number;
}

/**
 * 知识库列表数据加载 Hook
 * 
 * 功能：
 * - 加载知识库列表
 * - 支持搜索过滤
 */
export function useKnowledgeList() {
  const [loading, setLoading] = useState(false);
  const [knowledgeList, setKnowledgeList] = useState<KnowledgeInfo[]>([]);
  const [searchText, setSearchText] = useState('');

  // 加载知识库列表
  const loadKnowledgeList = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/knowledge/bases', {
        headers: buildAuthHeaders(),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const data: BackendKnowledgeListResponse = await response.json();
      
      // 转换为 KnowledgeInfo 格式
      const list: KnowledgeInfo[] = (data.bases || []).map(base => ({
        id: base.id,
        name: base.name,
        description: base.description,
        documentCount: base.chunk_count,
        createdAt: new Date(base.created_at).toISOString(),
      }));
      
      setKnowledgeList(list);
    } catch (error) {
      console.error('Failed to load knowledge list:', error);
      message.error('加载知识库列表失败');
      setKnowledgeList([]);
    } finally {
      setLoading(false);
    }
  }, []);

  // 初始加载
  useEffect(() => {
    loadKnowledgeList();
  }, [loadKnowledgeList]);

  // 搜索过滤
  const filteredList = useCallback(() => {
    if (!searchText) return knowledgeList;
    
    const search = searchText.toLowerCase();
    return knowledgeList.filter(item => 
      item.name.toLowerCase().includes(search) ||
      item.description?.toLowerCase().includes(search)
    );
  }, [knowledgeList, searchText]);

  return {
    knowledgeList: filteredList(),
    loading,
    searchText,
    setSearchText,
    refresh: loadKnowledgeList,
  };
}
