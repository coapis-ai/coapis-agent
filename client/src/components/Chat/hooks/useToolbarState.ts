# 工具栏状态管理 Hook

import { useState, useCallback, useEffect } from 'react';
import type { FileInfo, KnowledgeInfo } from '../types';

const TOOLBAR_PINNED_KEY = 'chat-toolbar-pinned';

/**
 * 工具栏状态管理
 */
export function useToolbarState() {
  // 工具栏可见性
  const [visible, setVisible] = useState(false);

  // 固定状态（从 localStorage 读取）
  const [pinned, setPinned] = useState(() => {
    if (typeof window === 'undefined') return false;
    const isMobile = window.innerWidth < 768;
    if (isMobile) return false; // 移动端不支持固定
    return localStorage.getItem(TOOLBAR_PINNED_KEY) === 'true';
  });

  // 已选文件
  const [selectedFiles, setSelectedFiles] = useState<FileInfo[]>([]);

  // 已选知识库
  const [selectedKnowledge, setSelectedKnowledge] = useState<KnowledgeInfo[]>([]);

  // 保存固定状态到 localStorage
  useEffect(() => {
    localStorage.setItem(TOOLBAR_PINNED_KEY, String(pinned));
  }, [pinned]);

  // 打开工具栏
  const openToolbar = useCallback(() => {
    setVisible(true);
  }, []);

  // 关闭工具栏
  const closeToolbar = useCallback(() => {
    if (!pinned) {
      setVisible(false);
    }
  }, [pinned]);

  // 切换工具栏
  const toggleToolbar = useCallback(() => {
    setVisible(prev => !prev);
  }, []);

  // 切换固定状态
  const togglePinned = useCallback(() => {
    setPinned(prev => !prev);
  }, []);

  // 添加文件引用
  const addFileReference = useCallback((file: FileInfo) => {
    setSelectedFiles(prev => {
      if (prev.some(f => f.id === file.id)) return prev;
      return [...prev, file];
    });
  }, []);

  // 移除文件引用
  const removeFileReference = useCallback((fileId: string) => {
    setSelectedFiles(prev => prev.filter(f => f.id !== fileId));
  }, []);

  // 添加知识库引用
  const addKnowledgeReference = useCallback((item: KnowledgeInfo) => {
    setSelectedKnowledge(prev => {
      if (prev.some(k => k.id === item.id)) return prev;
      return [...prev, item];
    });
  }, []);

  // 移除知识库引用
  const removeKnowledgeReference = useCallback((knowledgeId: string) => {
    setSelectedKnowledge(prev => prev.filter(k => k.id !== knowledgeId));
  }, []);

  // 清空所有引用
  const clearAllReferences = useCallback(() => {
    setSelectedFiles([]);
    setSelectedKnowledge([]);
  }, []);

  // 获取总引用数
  const totalReferences = selectedFiles.length + selectedKnowledge.length;

  return {
    // 状态
    visible,
    pinned,
    selectedFiles,
    selectedKnowledge,
    totalReferences,

    // 操作
    openToolbar,
    closeToolbar,
    toggleToolbar,
    togglePinned,
    setSelectedFiles,
    setSelectedKnowledge,
    addFileReference,
    removeFileReference,
    addKnowledgeReference,
    removeKnowledgeReference,
    clearAllReferences,
  };
}
