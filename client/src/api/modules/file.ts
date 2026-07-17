// 文件API接口

import { request } from '../request';

// ── Types ──────────────────────────────────────────────

export interface FileInfo {
  id: string;
  name: string;
  path: string;
  type: 'file' | 'folder';
  size?: number;
  mimeType?: string;
  createdAt?: string;
  updatedAt?: string;
}

export interface FileNode {
  id: string;
  name: string;
  path: string;
  type: 'file' | 'folder';
  size?: number;
  mimeType?: string;
  children?: FileNode[];
}

export interface FileListResponse {
  files: FileInfo[];
  total: number;
}

export interface FileTreeResponse {
  tree: FileNode[];
}

// ── API ────────────────────────────────────────────────

export const fileApi = {
  /**
   * 获取文件列表
   */
  listFiles: (params?: {
    path?: string;
    type?: 'file' | 'folder';
    limit?: number;
    offset?: number;
  }) => {
    const query = new URLSearchParams();
    if (params?.path) query.set('path', params.path);
    if (params?.type) query.set('type', params.type);
    if (params?.limit) query.set('limit', String(params.limit));
    if (params?.offset) query.set('offset', String(params.offset));
    const qs = query.toString();
    return request<FileListResponse>(`/files${qs ? `?${qs}` : ''}`);
  },

  /**
   * 获取文件树
   */
  getFileTree: (rootPath?: string) => {
    const query = rootPath ? `?root=${encodeURIComponent(rootPath)}` : '';
    return request<FileTreeResponse>(`/files/tree${query}`);
  },

  /**
   * 获取文件信息
   */
  getFileInfo: (fileId: string) =>
    request<FileInfo>(`/files/${encodeURIComponent(fileId)}`),

  /**
   * 上传文件
   */
  uploadFile: (file: File, targetPath?: string) => {
    const form = new FormData();
    form.append('file', file);
    if (targetPath) form.append('target_path', targetPath);
    return request<FileInfo>('/files/upload', {
      method: 'POST',
      body: form,
      headers: {} as HeadersInit,
    });
  },

  /**
   * 删除文件
   */
  deleteFile: (fileId: string) =>
    request<{ success: boolean; message: string }>(
      `/files/${encodeURIComponent(fileId)}`,
      { method: 'DELETE' }
    ),

  /**
   * 搜索文件
   */
  searchFiles: (query: string, limit?: number) => {
    const params = new URLSearchParams();
    params.set('q', query);
    if (limit) params.set('limit', String(limit));
    return request<FileListResponse>(`/files/search?${params.toString()}`);
  },
};
