import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Breadcrumb,
  Button,
  Input,
  List,
  message,
  Modal,
  Space,
  Empty,
  Tag,
  Tooltip,
  Select,
  Progress,
  Typography,
  Divider,
  Image,
  Tabs,
} from 'antd';
import type { InputRef } from 'antd';
import {
  FolderOutlined,
  FileOutlined,
  FileTextOutlined,
  FileImageOutlined,
  FilePdfOutlined,
  FileZipOutlined,
  HomeOutlined,
  FolderAddOutlined,
  EditOutlined,
  DeleteOutlined,
  UploadOutlined,
  DownloadOutlined,
  UnorderedListOutlined,
  AppstoreOutlined,
  EyeOutlined,
  CopyOutlined,
  CloudUploadOutlined,
  LoadingOutlined,
  RobotOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { api, getApiUrl } from '@/api';
import { buildAuthHeaders } from '@/api/authHeaders';
import { usePermission } from '@/hooks/usePermission';
import AgentIdentityPanel from './AgentIdentityPanel';

const FILES_API = '/myfiles';

const { Text } = Typography;

// MySpace 类别定义（技能已有独立菜单，不在此重复）
const CATEGORIES = [
  { key: 'files', label: '文件', icon: <FolderOutlined /> },
  { key: 'agents', label: '智能体', icon: <RobotOutlined /> },
];

// ═══════════════════════════════════════════════════════════
// 工具函数
// ═══════════════════════════════════════════════════════════

const getFileIcon = (item: any) => {
  if (item.type === 'directory') return <FolderOutlined style={{ fontSize: 22, color: '#736dff' }} />;
  const mime = item.mimeType || '';
  if (mime.startsWith('image/')) return <FileImageOutlined style={{ fontSize: 20, color: '#52c41a' }} />;
  if (mime === 'application/pdf') return <FilePdfOutlined style={{ fontSize: 20, color: '#f5222d' }} />;
  if (mime.startsWith('application/zip') || mime.startsWith('application/gzip') || mime.includes('tar')) return <FileZipOutlined style={{ fontSize: 20, color: '#faad14' }} />;
  if (mime.startsWith('text/') || mime === 'application/json' || mime === 'application/xml') return <FileTextOutlined style={{ fontSize: 20, color: '#1890ff' }} />;
  return <FileOutlined style={{ fontSize: 20 }} />;
};

const formatSize = (bytes: number) => {
  if (bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0)} ${units[i]}`;
};

const formatTime = (timestamp: number) => {
  if (!timestamp) return '-';
  return new Date(timestamp * 1000).toLocaleString('zh-CN');
};

// ═══════════════════════════════════════════════════════════
// 主组件
// ═══════════════════════════════════════════════════════════

const MySpacePage: React.FC = () => {
  const { t } = useTranslation();
  const { hasPermission } = usePermission();
  const canDelete = hasPermission("myspace:delete");
  
  // 当前激活的类别
  const [activeCategory, setActiveCategory] = useState('files');
  
  // 状态
  const [currentPath, setCurrentPath] = useState('/');
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [viewMode, setViewMode] = useState<'list' | 'grid'>('grid');
  const [searchKeyword, setSearchKeyword] = useState('');
  const [fileTypeFilter, setFileTypeFilter] = useState<string>('all');
  const [usage, setUsage] = useState<{ usage_mb: number; limit_mb: number; usage_percent: number } | null>(null);
  const [previewModal, setPreviewModal] = useState<{ visible: boolean; item: any; content: string }>({
    visible: false,
    item: null,
    content: '',
  });
  const [renameModal, setRenameModal] = useState<{ visible: boolean; item: any; value: string }>({
    visible: false,
    item: null,
    value: '',
  });
  const [newFolderName, setNewFolderName] = useState('');
  const [folderModalVisible, setFolderModalVisible] = useState(false);
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [copyModalVisible, setCopyModalVisible] = useState(false);
  const [copyTarget, setCopyTarget] = useState('');
  const [copySource, setCopySource] = useState<any>(null);
  
  // MySpace 配置（文件大小限制等）
  const [myspaceConfig, setMySpaceConfig] = useState<{ max_file_size: number; max_file_size_mb: number; max_upload_files: number } | null>(null);
  
  const searchInputRef = useRef<InputRef>(null);
  const uploadRef = useRef<HTMLInputElement>(null);

  // 判断当前类别是否只读
  const isReadOnly = activeCategory !== 'files';

  // 构建当前类别的根路径
  const getCategoryRootPath = (_cat: string) => '/';

  // ═══════════════════════════════════════════════════════════
  // 核心操作
  // ═══════════════════════════════════════════════════════════

  // 加载 MySpace 配置（文件大小限制等）
  const loadConfig = useCallback(async () => {
    try {
      const res: any = await api.get(`${FILES_API}/config`);
      setMySpaceConfig(res);
    } catch {
      // Silently fail — use defaults
    }
  }, []);

  const loadFiles = useCallback(async (path: string = currentPath) => {
    setLoading(true);
    try {
      const query = new URLSearchParams({ path, category: activeCategory }).toString();
      const url = `${FILES_API}/list?${query}`;
      const res: any = await api.get(url);
      setCurrentPath(res.path);
      setItems(res.items);
      setSearchResults([]);
      setIsSearching(false);
    } catch (e: any) {
      message.error(e?.message || t('myspace.loadFailed'));
    } finally {
      setLoading(false);
    }
  }, [currentPath, activeCategory, t]);

  const loadUsage = useCallback(async () => {
    try {
      const res: any = await api.get(`${FILES_API}/usage`);
      setUsage(res);
    } catch {
      // Silently fail
    }
  }, []);

  useEffect(() => {
    loadFiles();
    loadUsage();
    loadConfig();
  }, [activeCategory]);

  // Tab 切换时重置路径
  const handleTabChange = (tabKey: string) => {
    setActiveCategory(tabKey);
    setCurrentPath(getCategoryRootPath(tabKey));
    setSearchKeyword('');
    setSearchResults([]);
    setIsSearching(false);
    setFileTypeFilter('all');
  };

  // 搜索
  const handleSearch = async () => {
    if (!searchKeyword.trim()) {
      setSearchResults([]);
      setIsSearching(false);
      loadFiles();
      return;
    }
    setIsSearching(true);
    setLoading(true);
    try {
      const url = `${FILES_API}/search?keyword=${encodeURIComponent(searchKeyword)}&path=${encodeURIComponent(currentPath)}&category=${activeCategory}`;
      const res: any = await api.get(url);
      setSearchResults(res.items || []);
    } catch (e: any) {
      message.error(e?.message || t('myspace.searchFailed'));
      setSearchResults([]);
    } finally {
      setLoading(false);
    }
  };

  // 导航到路径
  const navigateTo = (path: string) => {
    setSearchKeyword('');
    setSearchResults([]);
    setIsSearching(false);
    setCurrentPath(path);
    loadFiles(path);
  };

  // 双击进入目录 / 打开文件
  const handleDoubleClick = (item: any) => {
    if (item.type === 'directory') {
      navigateTo(item.path);
    } else if (item.type === 'file') {
      // 可预览的文件打开预览，否则直接下载
      if (item.previewable) {
        handlePreview(item);
      } else {
        // 非预览文件（如 .docx/.zip/.mp4 等）直接下载
        handleDownload(item);
      }
    }
  };

  // 预览文件
  const handlePreview = async (item: any) => {
    if (item.type !== 'file' || !item.previewable) return;
    setLoading(true);
    try {
      const url = `${FILES_API}/preview?path=${encodeURIComponent(item.path)}&category=${activeCategory}`;
      const res: any = await api.get(url);
      setPreviewModal({ visible: true, item, content: res.content });
    } catch (e: any) {
      message.error(e?.message || t('myspace.previewFailed'));
    } finally {
      setLoading(false);
    }
  };

  // 下载文件（带认证）
  const handleDownload = async (item: any) => {
    try {
      const url = getApiUrl(`${FILES_API}/download?path=${encodeURIComponent(item.path)}&category=${activeCategory}`);
      const response = await fetch(url, {
        headers: { ...buildAuthHeaders() },
      });
      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.detail || err.message || 'Download failed');
      }
      const blob = await response.blob();
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = blobUrl;
      a.download = item.name;
      a.click();
      URL.revokeObjectURL(blobUrl);
    } catch (e: any) {
      message.error(e?.message || 'Download failed');
    }
  };

  // 重命名
  const handleRename = async () => {
    if (!renameModal.value?.trim() || !renameModal.item) return;
    try {
      await api.put(`${FILES_API}/rename?category=${activeCategory}`, {
        path: renameModal.item.path,
        newName: renameModal.value.trim(),
      });
      message.success(t('myspace.renameSuccess'));
      setRenameModal({ visible: false, item: null, value: '' });
      loadFiles();
    } catch (e: any) {
      message.error(e?.message || t('myspace.renameFailed'));
    }
  };

  // 删除
  const handleDelete = async (item: any) => {
    Modal.confirm({
      title: t('myspace.deleteConfirm'),
      content: t('myspace.deleteConfirmMsg', { name: item.name }),
      okText: t('myspace.delete'),
      okType: 'danger',
      onOk: async () => {
        try {
          await api.delete(`${FILES_API}/delete?path=${encodeURIComponent(item.path)}&category=${activeCategory}`);
          message.success(t('myspace.deleteSuccess'));
          loadFiles();
          loadUsage();
        } catch (e: any) {
          message.error(e?.message || t('myspace.deleteFailed'));
        }
      },
    });
  };

  // 复制文件
  const handleCopy = (item: any) => {
    setCopySource(item);
    setCopyTarget(`${item.name}_copy`);
    setCopyModalVisible(true);
  };

  const handleCopyOk = async () => {
    if (!copyTarget?.trim() || !copySource) return;
    try {
      await api.post(`${FILES_API}/copy?category=${activeCategory}`, {
        source: copySource.path,
        target: copyTarget.trim(),
      });
      message.success(t('myspace.copySuccess'));
      setCopyModalVisible(false);
      loadFiles();
    } catch (e: any) {
      message.error(e?.message || t('myspace.copyFailed'));
    }
  };

  // 上传单个文件（支持 409 覆盖确认）
  const uploadFile = async (file: File, path: string, category: string): Promise<boolean> => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('path', path);
    formData.append('category', category);
    
    const url = getApiUrl(`${FILES_API}/upload`);
    const response = await fetch(url, {
      method: 'POST',
      headers: { ...buildAuthHeaders() },
      body: formData,
    });
    
    // 409 Conflict - 文件已存在，询问是否覆盖
    if (response.status === 409) {
      const err = await response.json().catch(() => ({}));
      // Use Promise without explicit type annotation to avoid TSX parsing issues
      const confirmed = await new Promise((resolve) => {
        Modal.confirm({
          title: '覆盖确认',
          content: (
            <div>
              <p><strong>{file.name}</strong> 已存在，是否覆盖？</p>
              <p>当前大小: {formatSize(err.existing_size || 0)}</p>
              <p>新文件大小: {formatSize(file.size)}</p>
            </div>
          ),
          okText: '覆盖',
          cancelText: '跳过',
          okButtonProps: { danger: true },
          onOk: () => resolve(true),
          onCancel: () => resolve(false),
        });
      });
      if (!confirmed) {
        return false; // 用户选择跳过
      }
      
      // 重新上传，携带 overwrite=true
      const overwriteFormData = new FormData();
      overwriteFormData.append('file', file);
      overwriteFormData.append('path', path);
      overwriteFormData.append('category', category);
      overwriteFormData.append('overwrite', 'true');
      
      const overwriteResponse = await fetch(url, {
        method: 'POST',
        headers: { ...buildAuthHeaders() },
        body: overwriteFormData,
      });
      
      if (!overwriteResponse.ok) {
        const err2 = await overwriteResponse.json().catch(() => ({}));
        throw new Error(err2.detail || err2.message || 'Overwrite failed');
      }
      message.warning(`${file.name} 已覆盖`);
      return true;
    }
    
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || err.message || 'Upload failed');
    }
    return true;
  };

  // 拖拽上传
  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const files = Array.from(e.dataTransfer.files);
    if (!files.length) return;
    
    // 预检查上传数量
    const maxFiles = myspaceConfig?.max_upload_files ?? 10;
    if (files.length > maxFiles) {
      message.error(`单次最多上传 ${maxFiles} 个文件，当前 ${files.length} 个`);
      return;
    }
    
    // 预检查文件大小
    const maxBytes = myspaceConfig?.max_file_size ?? 20 * 1024 * 1024;
    const maxMB = (maxBytes / 1024 / 1024).toFixed(0);
    for (const file of files) {
      if (file.size > maxBytes) {
        message.error(`${file.name}: 文件过大（${formatSize(file.size)}），最大允许 ${maxMB}MB`);
        return;
      }
    }
    
    let successCount = 0;
    let skipCount = 0;
    let errorCount = 0;
    
    for (const file of files) {
      try {
        const success = await uploadFile(file, currentPath, activeCategory);
        if (success) {
          successCount++;
        } else {
          skipCount++;
        }
      } catch (e: any) {
        message.error(`${file.name}: ${e.message}`);
        errorCount++;
      }
    }
    
    // 显示汇总消息
    const parts = [];
    if (successCount > 0) parts.push(`${successCount} 个成功`);
    if (skipCount > 0) parts.push(`${skipCount} 个跳过`);
    if (errorCount > 0) parts.push(`${errorCount} 个失败`);
    if (parts.length > 0) {
      message.info(`上传完成: ${parts.join(', ')}`);
    }
    
    loadFiles();
    loadUsage();
  };

  // 过滤后的列表
  const displayItems = isSearching ? searchResults : items;
  const filteredItems = fileTypeFilter === 'all' 
    ? displayItems 
    : displayItems.filter(item => {
        if (fileTypeFilter === 'folders') return item.type === 'directory';
        if (fileTypeFilter === 'files') return item.type === 'file';
        if (fileTypeFilter === 'images') return item.mimeType?.startsWith('image/');
        if (fileTypeFilter === 'texts') return item.mimeType?.startsWith('text/') || item.mimeType === 'application/json';
        return true;
      });

  // 面包屑
  const breadcrumbItems = currentPath.split('/').filter(Boolean).reduce((acc: any[], _, index) => {
    const path = '/' + currentPath.split('/').slice(1, index + 1).join('/');
    const name = currentPath.split('/')[index + 1] || activeCategory;
    acc.push({ title: name, key: path, href: '#', onClick: (e: React.MouseEvent) => { e.preventDefault(); navigateTo(path); } });
    return acc;
  }, [{ title: <HomeOutlined />, key: getCategoryRootPath(activeCategory), href: '#', onClick: (e: React.MouseEvent) => { e.preventDefault(); navigateTo(getCategoryRootPath(activeCategory)); } }]);

  // Tab items
  const tabItems = CATEGORIES.map(cat => ({
    key: cat.key,
    label: (
      <Space size={4}>
        {cat.icon}
        <span>{cat.label}</span>
      </Space>
    ),
  }));

  // ═══════════════════════════════════════════════════════════
  // 渲染
  // ═══════════════════════════════════════════════════════════

  return (
    <div 
      className="page-container myspace-container"
      onDragOver={(e) => { e.preventDefault(); if (!isReadOnly) setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={isReadOnly ? undefined : handleDrop}
      style={{ position: 'relative', padding: '24px', boxSizing: 'border-box' }}
    >
      {/* 拖拽上传遮罩 */}
      {dragOver && !isReadOnly && (
        <div style={{
          position: 'absolute', top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(115, 109, 255, 0.1)',
          border: '3px dashed #736dff',
          borderRadius: 8,
          zIndex: 100,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          pointerEvents: 'none',
        }}>
          <div style={{ textAlign: 'center', color: '#736dff' }}>
            <CloudUploadOutlined style={{ fontSize: 64 }} />
            <div style={{ fontSize: 18, marginTop: 12 }}>{t('myspace.dropToUpload')}</div>
          </div>
        </div>
      )}

      {/* Tab 切换 */}
      <Tabs
        activeKey={activeCategory}
        onChange={handleTabChange}
        items={tabItems}
        size="large"
        style={{ marginBottom: 16 }}
        tabBarStyle={{ marginBottom: 0, paddingLeft: 0 }}
      />

      {/* 顶部工具栏 (仅文件 tab) */}
      {activeCategory !== 'agents' && (
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <Breadcrumb items={breadcrumbItems} />
        
        <Divider type="vertical" style={{ margin: '0 8px' }} />
        
        {/* 搜索 */}
        <Input.Search
          ref={searchInputRef}
          placeholder={t('myspace.searchPlaceholder')}
          value={searchKeyword}
          onChange={(e) => setSearchKeyword(e.target.value)}
          onSearch={handleSearch}
          style={{ width: 220 }}
          allowClear
        />
        
        <Divider type="vertical" style={{ margin: '0 8px' }} />
        
        {/* 文件类型过滤 */}
        <Select
          value={fileTypeFilter}
          onChange={setFileTypeFilter}
          style={{ width: 120 }}
          size="small"
        >
          <Select.Option value="all">{t('myspace.allFiles')}</Select.Option>
          <Select.Option value="folders">{t('myspace.folders')}</Select.Option>
          <Select.Option value="files">{t('myspace.files')}</Select.Option>
          <Select.Option value="images">{t('myspace.images')}</Select.Option>
          <Select.Option value="texts">{t('myspace.textFiles')}</Select.Option>
        </Select>
        
        <div style={{ flex: 1 }} />
        
        {/* 只读提示 */}
        {isReadOnly && (
          <Tag color="orange" style={{ margin: 0 }}>
            {t('myspace.readOnly')}
          </Tag>
        )}
        
        {/* 存储用量 (仅文件 Tab 显示) */}
        {!isReadOnly && usage && (
          <Tooltip title={`${formatSize(usage.usage_mb * 1024 * 1024)} / ${formatSize(usage.limit_mb * 1024 * 1024)}`}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Progress
                type="circle"
                size={28}
                percent={Math.min(usage.usage_percent, 100)}
                strokeColor={usage.usage_percent > 80 ? '#ff4d4f' : '#736dff'}
                format={() => <CloudUploadOutlined style={{ fontSize: 14 }} />}
              />
              <Text type="secondary" style={{ fontSize: 12 }}>{formatSize(usage.usage_mb * 1024 * 1024)}</Text>
            </div>
          </Tooltip>
        )}
        
        {/* 视图切换 */}
        <Space>
          <Tooltip title={t('myspace.listView')}>
            <Button
              type={viewMode === 'list' ? 'primary' : 'text'}
              icon={<UnorderedListOutlined />}
              size="small"
              onClick={() => setViewMode('list')}
            />
          </Tooltip>
          <Tooltip title={t('myspace.gridView')}>
            <Button
              type={viewMode === 'grid' ? 'primary' : 'text'}
              icon={<AppstoreOutlined />}
              size="small"
              onClick={() => setViewMode('grid')}
            />
          </Tooltip>
        </Space>
        
        {/* 操作按钮 (仅文件 Tab 显示) */}
        {!isReadOnly && (
          <>
            <Divider type="vertical" style={{ margin: '0 8px' }} />
            <Space>
              <Button
                type="primary"
                icon={<UploadOutlined />}
                size="small"
                onClick={() => uploadRef.current?.click()}
              >
                {t('myspace.upload')}
              </Button>
              <Button
                icon={<FolderAddOutlined />}
                size="small"
                onClick={() => setFolderModalVisible(true)}
              >
                {t('myspace.newFolder')}
              </Button>
            </Space>
            
            {/* 文件大小限制提示 */}
            {myspaceConfig && (
              <Text type="secondary" style={{ fontSize: 11, marginLeft: 8 }}>
                单次最多 {myspaceConfig.max_upload_files} 个，单文件最大 {myspaceConfig.max_file_size_mb.toFixed(0)}MB
              </Text>
            )}
            
            {/* 隐藏的文件输入 */}
            <input
              ref={uploadRef}
              type="file"
              multiple
              style={{ display: 'none' }}
              onChange={async (e) => {
                const files = Array.from(e.target.files || []);
                if (!files.length) {
                  e.target.value = '';
                  return;
                }
                
                // 预检查上传数量
                const maxFiles = myspaceConfig?.max_upload_files ?? 10;
                if (files.length > maxFiles) {
                  message.error(`单次最多上传 ${maxFiles} 个文件，当前 ${files.length} 个`);
                  e.target.value = '';
                  return;
                }
                
                // 预检查文件大小
                const maxBytes = myspaceConfig?.max_file_size ?? 20 * 1024 * 1024;
                const maxMB = (maxBytes / 1024 / 1024).toFixed(0);
                for (const file of files) {
                  if (file.size > maxBytes) {
                    message.error(`${file.name}: 文件过大（${formatSize(file.size)}），最大允许 ${maxMB}MB`);
                    e.target.value = '';
                    return;
                  }
                }
                
                let successCount = 0;
                let skipCount = 0;
                let errorCount = 0;
                
                for (const file of files) {
                  try {
                    const success = await uploadFile(file, currentPath, activeCategory);
                    if (success) {
                      successCount++;
                    } else {
                      skipCount++;
                    }
                  } catch (err: any) {
                    message.error(`${file.name}: ${err.message}`);
                    errorCount++;
                  }
                }
                
                // 显示汇总消息
                const parts = [];
                if (successCount > 0) parts.push(`${successCount} 个成功`);
                if (skipCount > 0) parts.push(`${skipCount} 个跳过`);
                if (errorCount > 0) parts.push(`${errorCount} 个失败`);
                if (parts.length > 0) {
                  message.info(`上传完成: ${parts.join(', ')}`);
                }
                
                loadFiles();
                loadUsage();
                e.target.value = '';
              }}
            />
          </>
        )}
      </div>
      )}

      {/* 文件列表 - 列表视图 (仅文件 tab) */}
      {activeCategory === 'agents' && (
        <AgentIdentityPanel />
      )}
      {activeCategory !== 'agents' && viewMode === 'list' && (
        <List
          loading={loading}
          dataSource={filteredItems}
          locale={{ emptyText: <Empty description={t('myspace.emptyFolder')} /> }}
          renderItem={(item: any) => (
            <List.Item
              actions={[
                item.type === 'file' && item.previewable && (
                  <Tooltip key="preview" title={t('myspace.preview')}>
                    <Button type="text" icon={<EyeOutlined />} onClick={() => handlePreview(item)} />
                  </Tooltip>
                ),
                item.type === 'file' && (
                  <Tooltip key="download" title={t('myspace.download')}>
                    <Button type="text" icon={<DownloadOutlined />} onClick={() => handleDownload(item)} />
                  </Tooltip>
                ),
                // 只读模式隐藏写操作按钮
                !isReadOnly && (
                  <Tooltip key="copy" title={t('myspace.copy')}>
                    <Button type="text" icon={<CopyOutlined />} onClick={() => handleCopy(item)} />
                  </Tooltip>
                ),
                !isReadOnly && (
                  <Tooltip key="rename" title={t('myspace.rename')}>
                    <Button type="text" icon={<EditOutlined />} onClick={() => setRenameModal({ visible: true, item, value: item.name })} />
                  </Tooltip>
                ),
                !isReadOnly && canDelete && (
                  <Tooltip key="delete" title={t('myspace.delete')}>
                    <Button type="text" danger icon={<DeleteOutlined />} onClick={() => handleDelete(item)} />
                  </Tooltip>
                ),
              ].filter(Boolean)}
            >
              <div
                onClick={() => handleDoubleClick(item)}
                onDoubleClick={() => handleDoubleClick(item)}
                style={{ display: 'flex', alignItems: 'center', gap: 12, width: '100%', cursor: 'pointer' }}
              >
                {getFileIcon(item)}
                <Text strong style={{ flex: 1 }}>{item.name}</Text>
                {item.type === 'file' && <Text type="secondary" style={{ width: 80 }}>{formatSize(item.size)}</Text>}
                {item.type === 'file' && <Text type="secondary" style={{ width: 160 }}>{formatTime(item.modified)}</Text>}
                {item.type === 'directory' && <Tag color="blue">{t('myspace.folder')}</Tag>}
              </div>
            </List.Item>
          )}
        />
      )}

      {/* 文件列表 - 网格视图 (仅文件 tab) */}
      {activeCategory !== 'agents' && viewMode === 'grid' && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, padding: 8 }}>
          {loading && <LoadingOutlined style={{ fontSize: 24, color: '#736dff', margin: '40px auto' }} />}
          {!loading && filteredItems.length === 0 && <Empty description={t('myspace.emptyFolder')} style={{ margin: '40px auto' }} />}
          {!loading && filteredItems.map((item: any) => (
            <div
              key={item.path}
              style={{
                width: 140, padding: 16, textAlign: 'center',
                border: '1px solid #f0f0f0', borderRadius: 8,
                cursor: 'pointer', transition: 'all 0.2s',
                position: 'relative', overflow: 'hidden',
              }}
              onClick={() => handleDoubleClick(item)}
              onDoubleClick={() => handleDoubleClick(item)}
              onMouseEnter={(e) => {
                e.currentTarget.style.boxShadow = '0 2px 8px rgba(0,0,0,0.1)';
                const overlay = e.currentTarget.querySelector('.grid-overlay') as HTMLElement | null;
                if (overlay) overlay.style.opacity = '1';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.boxShadow = 'none';
                const overlay = e.currentTarget.querySelector('.grid-overlay') as HTMLElement | null;
                if (overlay) overlay.style.opacity = '0';
              }}
            >
              <div style={{ fontSize: 36, marginBottom: 8 }}>{getFileIcon(item)}</div>
              <Text ellipsis style={{ display: 'block', fontSize: 13 }}>{item.name}</Text>
              {item.type === 'file' && <Text type="secondary" style={{ fontSize: 11 }}>{formatSize(item.size)}</Text>}
              
              {/* Hover 操作遮罩层 - 按钮放在底部 */}
              <div className="grid-overlay" style={{
                position: 'absolute', top: 0, left: 0, right: 0, bottom: 0,
                background: 'rgba(0,0,0,0.55)',
                display: 'flex', flexDirection: 'column',
                alignItems: 'center', justifyContent: 'flex-end',
                paddingBottom: 8,
                gap: 4, opacity: 0, transition: 'opacity 0.2s',
                cursor: 'pointer',
              }}>
                <div style={{ display: 'flex', gap: 4 }}>
                  {item.type === 'file' && item.previewable && (
                    <Button size="small" type="text" icon={<EyeOutlined style={{ fontSize: 16 }} />}
                      style={{ color: '#fff' }}
                      onClick={(e) => { e.stopPropagation(); handlePreview(item); }} />
                  )}
                  {item.type === 'file' && (
                    <Button size="small" type="text" icon={<DownloadOutlined style={{ fontSize: 16 }} />}
                      style={{ color: '#fff' }}
                      onClick={(e) => { e.stopPropagation(); handleDownload(item); }} />
                  )}
                  {!isReadOnly && (
                    <Button size="small" type="text" icon={<EditOutlined style={{ fontSize: 16 }} />}
                      style={{ color: '#fff' }}
                      onClick={(e) => { e.stopPropagation(); setRenameModal({ visible: true, item, value: item.name }); }} />
                  )}
                  {!isReadOnly && canDelete && (
                    <Button size="small" type="text" danger
                      icon={<DeleteOutlined style={{ fontSize: 16, color: '#ff4d4f' }} />}
                      onClick={(e) => { e.stopPropagation(); handleDelete(item); }} />
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 新建文件夹弹窗 (仅文件 Tab) */}
      {!isReadOnly && (
        <Modal
          title={t('myspace.newFolder')}
          open={folderModalVisible}
          onOk={async () => {
            if (!newFolderName?.trim()) return;
            try {
              await api.post(`${FILES_API}/mkdir?category=${activeCategory}`, {
                path: currentPath,
                name: newFolderName.trim(),
              });
              message.success(t('myspace.folderCreated'));
              setFolderModalVisible(false);
              setNewFolderName('');
              loadFiles();
            } catch (e: any) {
              message.error(e?.message || t('myspace.folderCreateFailed'));
            }
          }}
          onCancel={() => { setFolderModalVisible(false); setNewFolderName(''); }}
          okText={t('myspace.create')}
          cancelText={t('myspace.cancel')}
        >
          <Input
            value={newFolderName}
            onChange={(e) => setNewFolderName(e.target.value)}
            onPressEnter={() => {
              if (newFolderName?.trim()) {
                api.post(`${FILES_API}/mkdir?category=${activeCategory}`, {
                  path: currentPath,
                  name: newFolderName.trim(),
                }).then(() => {
                  message.success(t('myspace.folderCreated'));
                  setFolderModalVisible(false);
                  setNewFolderName('');
                  loadFiles();
                }).catch((e: any) => message.error(e?.message || t('myspace.folderCreateFailed')));
              }
            }}
            placeholder={t('myspace.folderName')}
            autoFocus
          />
        </Modal>
      )}

      {/* 重命名弹窗 (仅文件 Tab) */}
      {!isReadOnly && (
        <Modal
          title={t('myspace.rename')}
          open={renameModal.visible}
          onOk={handleRename}
          onCancel={() => setRenameModal({ visible: false, item: null, value: '' })}
          okText={t('myspace.confirm')}
          cancelText={t('myspace.cancel')}
          mask={false}
          getContainer={false}
          forceRender
          style={{ zIndex: 10000 }}
        >
          <Input
            value={renameModal.value}
            onChange={(e) => setRenameModal(prev => ({ ...prev, value: e.target.value }))}
            onPressEnter={handleRename}
            autoFocus
          />
        </Modal>
      )}

      {/* 复制弹窗 (仅文件 Tab) */}
      {!isReadOnly && (
        <Modal
          title={t('myspace.copyFile')}
          open={copyModalVisible}
          onOk={handleCopyOk}
          onCancel={() => setCopyModalVisible(false)}
          okText={t('myspace.copy')}
          cancelText={t('myspace.cancel')}
        >
          <div>
            <p style={{ marginBottom: 8 }}>{t('myspace.copyToPath')}</p>
            <Input
              value={copyTarget}
              onChange={(e) => setCopyTarget(e.target.value)}
              placeholder={currentPath}
              autoFocus
            />
          </div>
        </Modal>
      )}

      {/* 预览弹窗 */}
      <Modal
        title={
          <Space>
            {previewModal.item?.type === 'file' && getFileIcon(previewModal.item)}
            <Text ellipsis style={{ maxWidth: 300 }}>{previewModal.item?.name}</Text>
          </Space>
        }
        open={previewModal.visible}
        onCancel={() => setPreviewModal({ visible: false, item: null, content: '' })}
        footer={null}
        width={800}
        closable
      >
        {previewModal.item?.mimeType?.startsWith('image/') ? (
          <Image
            src={`data:${previewModal.item.mimeType};base64,${previewModal.content}`}
            alt={previewModal.item.name}
            style={{ maxWidth: '100%', maxHeight: 600, objectFit: 'contain' }}
          />
        ) : (
          <pre style={{ 
            whiteSpace: 'pre-wrap', wordBreak: 'break-word', 
            maxHeight: 500, overflow: 'auto', 
            background: '#f6f6f6', padding: 16, borderRadius: 8,
            fontSize: 13, lineHeight: 1.6,
          }}>
            {previewModal.content}
          </pre>
        )}
      </Modal>
    </div>
  );
};

export default MySpacePage;
