// 知识库列表数据加载 Hook

import { useState, useEffect, useCallback } from 'react';
import { message } from 'antd';
import { knowledgeApi } from '@/api/modules/knowledge';
import type { KnowledgeInfo } from '../types';

/**
 * 知识库列表数据加载和管理
 */
export function useKnowledgeList() {
  const [loading, setLoading] = useState(false);
  const [knowledgeList, setKnowledgeList] = useState<KnowledgeInfo[]>([]);
  const [error, setError] = useState<string | null>(null);

  // 加载知识库列表
  const loadKnowledgeList = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await knowledgeApi.listBases();
      // 转换为 KnowledgeInfo 格式
      const list: KnowledgeInfo[] = (response.bases || []).map(base => ({
        id: base.id,
        name: base.name,
        description: base.description,
        documentCount: base.chunk_count,
        createdAt: new Date(base.created_at).toISOString(),
      }));
      setKnowledgeList(list);
    } catch (err: any) {
      console.error('Failed to load knowledge list:', err);
      setError(err.message || '加载知识库列表失败');
      message.error('加载知识库列表失败');
    } finally {
      setLoading(false);
    }
  }, []);

  // 初始加载
  useEffect(() => {
    loadKnowledgeList();
  }, [loadKnowledgeList]);

  // 刷新列表
  const refresh = useCallback(() => {
    loadKnowledgeList();
  }, [loadKnowledgeList]);

  return {
    loading,
    knowledgeList,
    error,
    refresh,
  };
}
