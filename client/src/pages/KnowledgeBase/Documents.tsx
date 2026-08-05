/**
 * 知识库文档管理页面 (企业版)
 * 
 * 功能：
 * - 文件上传组件（支持 PDF, MD, TXT, DOCX）
 * - 文档列表展示表格（文件名、文档 ID、上传时间、状态、操作）
 */

import { useState, useEffect } from 'react';
import { Table, Button, Upload, message, Popconfirm, Tag, Space, Card, Empty } from 'antd';
import { UploadOutlined, DeleteOutlined, ReloadOutlined } from '@ant-design/icons';
import type { UploadProps } from 'antd';
import { useParams } from 'react-router-dom';
import { PageHeader } from '@/components/PageHeader';
import { knowledgeApi, type KnowledgeDocument } from '@/api/modules/knowledge';

export default function KnowledgeDocumentsPage() {
  const { id: kbId } = useParams<{ id: string }>();
  
  const [kbName, setKbName] = useState<string>('');
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [loading, setLoading] = useState(false);

  // Load KB info and documents on mount
  useEffect(() => {
    if (!kbId) return;
    
    loadDocuments();
  }, [kbId]);

  const loadDocuments = async () => {
    if (!kbId) return;
    
    setLoading(true);
    try {
      // Load KB info first (simplified - in real app, use knowledgeApi.getBase)
      setKbName(`知识库 ${kbId}`);
      
      const res = await knowledgeApi.listDocuments(kbId);
      setDocuments(res.documents || []);
    } catch (error) {
      console.error('加载文档列表失败:', error);
      message.error('加载文档列表失败');
    } finally {
      setLoading(false);
    }
  };

  // Upload props for document upload
  const uploadProps: UploadProps = {
    name: 'file',
    multiple: true,
    showUploadList: false,
    accept: '.pdf,.md,.txt,.docx',
    customRequest: async (options) => {
      const { file, onSuccess, onError } = options;
      if (!kbId) return;
      
      try {
        await knowledgeApi.uploadDocument(kbId, file as File);
        message.success('上传成功，正在处理...');
        onSuccess?.(file);
        
        // Refresh document list after a short delay
        setTimeout(() => loadDocuments(), 1000);
      } catch (error) {
        console.error('上传文档失败:', error);
        message.error('上传失败');
        onError?.(new Error('上传失败'));
      }
    },
    beforeUpload: (file) => {
      const isValidType = [
        'application/pdf',
        'text/markdown',
        'text/plain',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
      ].includes(file.type) || 
      file.name.endsWith('.pdf') || 
      file.name.endsWith('.md') || 
      file.name.endsWith('.txt') || 
      file.name.endsWith('.docx');
      
      if (!isValidType) {
        message.error('仅支持 PDF, MD, TXT, DOCX 格式文件');
        return false;
      }
      return true;
    },
  };

  // Delete document handler
  const handleDeleteDoc = async (docId: string) => {
    try {
      await knowledgeApi.deleteDocument(docId);
      message.success('删除成功');
      
      // Refresh document list
      if (kbId) {
        const res = await knowledgeApi.listDocuments(kbId);
        setDocuments(res.documents || []);
      }
    } catch (error) {
      console.error('删除文档失败:', error);
      message.error('删除失败');
    }
  };

  // Document table columns
  const docColumns = [
    {
      title: '文档标题',
      dataIndex: 'title',
      key: 'title',
      render: (text: string, record: KnowledgeDocument) => text || record.source || '-',
    },
    {
      title: '来源文件',
      dataIndex: 'source',
      key: 'source',
      width: 200,
    },
    {
      title: '文档 ID (doc_id)',
      dataIndex: 'id',
      key: 'doc_id',
      width: 150,
      render: (id: string) => id?.substring(0, 32) || '-',
    },
    {
      title: '分片数',
      dataIndex: 'chunk_count',
      key: 'chunk_count',
      width: 100,
      render: (count: number | undefined) => count || 0,
    },
    {
      title: '上传时间',
      dataIndex: 'created_at',
      key: 'upload_time',
      width: 180,
      render: (timestamp: number) => new Date(timestamp * 1000).toLocaleString('zh-CN'),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 120,
      render: (status: string) => {
        const map: Record<string, { color: string; text: string }> = {
          completed: { color: 'success', text: '已完成' },
          processing: { color: 'processing', text: '处理中' },
          failed: { color: 'error', text: '失败' },
        };
        const config = map[status] || map.completed;
        return <Tag color={config.color}>{config.text}</Tag>;
      },
    },
    {
      title: '操作',
      key: 'actions',
      width: 120,
      render: (_: unknown, record: KnowledgeDocument) => (
        <Popconfirm
          title="确定删除此文档？"
          onConfirm={() => handleDeleteDoc(record.id)}
        >
          <Button size="small" danger icon={<DeleteOutlined />}>删除</Button>
        </Popconfirm>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <PageHeader 
        parent={`知识库管理 / ${kbName || '文档列表'}`}
        current="文档管理与上传"
        backTo="/knowledge/bases"
      />

      <Card>
        <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Space>
            <Upload {...uploadProps}>
              <Button icon={<UploadOutlined />}>上传文档</Button>
            </Upload>
          </Space>
          
          <Space>
            <Button icon={<ReloadOutlined />} onClick={loadDocuments} loading={loading}>
              刷新列表
            </Button>
          </Space>
        </div>

        {documents.length === 0 && !loading ? (
          <Empty description="暂无文档，请上传文档" />
        ) : (
          <Table
            dataSource={documents}
            columns={docColumns}
            rowKey="id"
            loading={loading}
            pagination={{ pageSize: 10, showSizeChanger: true }}
          />
        )}
      </Card>
    </div>
  );
}
