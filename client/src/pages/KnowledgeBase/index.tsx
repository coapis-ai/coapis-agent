import { useState, useEffect, useCallback } from "react";
import {
  Card,
  Table,
  Button,
  Modal,
  Form,
  Input,
  Select,
  Space,
  Tag,
  Popconfirm,
  message,
  Upload,
  Drawer,
  Empty,
  Spin,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  PlusOutlined,
  DeleteOutlined,
  FileTextOutlined,
  SearchOutlined,
  UploadOutlined,
  DatabaseOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import { knowledgeApi } from "@/api/modules/knowledge";
import type {
  KnowledgeBase,
  KnowledgeDocument,
  KnowledgeSearchResult,
} from "@/api/modules/knowledge";
import { usePermission } from "@/hooks/usePermission";
import { PageHeader } from "@/components/PageHeader";

const { Text, Paragraph } = Typography;
const { TextArea } = Input;

// ── Scope options ──
const SCOPE_OPTIONS = [
  { label: "全局", value: "global" },
  { label: "用户级", value: "user" },
  { label: "智能体级", value: "agent" },
];

export default function KnowledgeBasePage() {
  const { hasPermission } = usePermission();
  const canWrite = hasPermission("knowledge:write");

  // ── State ──
  const [bases, setBases] = useState<KnowledgeBase[]>([]);
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);

  // Document drawer
  const [docDrawerOpen, setDocDrawerOpen] = useState(false);
  const [selectedBase, setSelectedBase] = useState<KnowledgeBase | null>(null);
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [docLoading, setDocLoading] = useState(false);
  const [uploading, setUploading] = useState(false);

  // Search
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchText, setSearchText] = useState("");
  const [searchResults, setSearchResults] = useState<KnowledgeSearchResult[]>([]);
  const [searching, setSearching] = useState(false);

  const [createForm] = Form.useForm();

  // ── Load bases ──
  const loadBases = useCallback(async () => {
    setLoading(true);
    try {
      const res = await knowledgeApi.listBases();
      setBases(res.bases || []);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      message.error(`加载知识库列表失败: ${msg}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadBases();
  }, [loadBases]);

  // ── Create base ──
  const handleCreate = async () => {
    try {
      const values = await createForm.validateFields();
      setCreating(true);
      await knowledgeApi.createBase({
        name: values.name,
        description: values.description || "",
        scope: values.scope || "global",
      });
      message.success("知识库创建成功");
      setCreateOpen(false);
      createForm.resetFields();
      loadBases();
    } catch (e: unknown) {
      if (e instanceof Error) message.error(`创建失败: ${e.message}`);
    } finally {
      setCreating(false);
    }
  };

  // ── Delete base ──
  const handleDelete = async (kbId: string) => {
    try {
      await knowledgeApi.deleteBase(kbId);
      message.success("知识库已删除");
      loadBases();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      message.error(`删除失败: ${msg}`);
    }
  };

  // ── Document management ──
  const openDocDrawer = async (base: KnowledgeBase) => {
    setSelectedBase(base);
    setDocDrawerOpen(true);
    setDocLoading(true);
    try {
      const res = await knowledgeApi.listDocuments(base.id);
      setDocuments(res.documents || []);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      message.error(`加载文档失败: ${msg}`);
    } finally {
      setDocLoading(false);
    }
  };

  const handleUpload = async (file: File) => {
    if (!selectedBase) return;
    setUploading(true);
    try {
      await knowledgeApi.uploadDocument(selectedBase.id, file);
      message.success(`文档 ${file.name} 上传成功`);
      const res = await knowledgeApi.listDocuments(selectedBase.id);
      setDocuments(res.documents || []);
      loadBases();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      message.error(`上传失败: ${msg}`);
    } finally {
      setUploading(false);
    }
    return false; // Prevent default upload
  };

  const handleDeleteDoc = async (docId: string) => {
    try {
      await knowledgeApi.deleteDocument(docId);
      message.success("文档已删除");
      if (selectedBase) {
        const res = await knowledgeApi.listDocuments(selectedBase.id);
        setDocuments(res.documents || []);
        loadBases();
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      message.error(`删除失败: ${msg}`);
    }
  };

  // ── Search ──
  const handleSearch = async () => {
    if (!searchText.trim()) return;
    setSearching(true);
    try {
      const res = await knowledgeApi.search({ text: searchText, limit: 10 });
      setSearchResults(res.results || []);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      message.error(`搜索失败: ${msg}`);
    } finally {
      setSearching(false);
    }
  };

  // ── Scope label ──
  const scopeLabel = (scope: string) => {
    const map: Record<string, { color: string; text: string }> = {
      global: { color: "blue", text: "全局" },
      user: { color: "green", text: "用户" },
      agent: { color: "purple", text: "智能体" },
    };
    const s = map[scope] || { color: "default", text: scope };
    return <Tag color={s.color}>{s.text}</Tag>;
  };

  // ── Table columns ──
  const columns: ColumnsType<KnowledgeBase> = [
    {
      title: "名称",
      dataIndex: "name",
      key: "name",
      render: (name: string, record) => (
        <Space>
          <DatabaseOutlined />
          <a onClick={() => openDocDrawer(record)}>{name}</a>
        </Space>
      ),
    },
    {
      title: "描述",
      dataIndex: "description",
      key: "description",
      ellipsis: true,
      width: 200,
    },
    {
      title: "作用域",
      dataIndex: "scope",
      key: "scope",
      width: 100,
      render: scopeLabel,
    },
    {
      title: "文档数",
      key: "chunk_count",
      width: 100,
      render: (_, record) => (
        <Space>
          <FileTextOutlined />
          <span>{record.chunk_count} chunks</span>
        </Space>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      width: 80,
      render: (status: string) => (
        <Tag color={status === "active" ? "success" : "default"}>{status}</Tag>
      ),
    },
    {
      title: "操作",
      key: "actions",
      width: 160,
      render: (_, record) => (
        <Space>
          <Button
            size="small"
            icon={<FileTextOutlined />}
            onClick={() => openDocDrawer(record)}
          >
            文档
          </Button>
          {canWrite && (
            <Popconfirm
              title="确定删除此知识库？"
              description="所有文档和索引将被永久删除"
              onConfirm={() => handleDelete(record.id)}
              okText="删除"
              okType="danger"
              cancelText="取消"
            >
              <Button size="small" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  // ── Document columns ──
  const docColumns: ColumnsType<KnowledgeDocument> = [
    {
      title: "标题",
      dataIndex: "title",
      key: "title",
      ellipsis: true,
    },
    {
      title: "类型",
      dataIndex: "content_type",
      key: "content_type",
      width: 80,
      render: (t: string) => <Tag>{t}</Tag>,
    },
    {
      title: "Chunks",
      dataIndex: "chunk_count",
      key: "chunk_count",
      width: 80,
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      width: 80,
      render: (s: string) => (
        <Tag color={s === "indexed" ? "success" : s === "error" ? "error" : "default"}>
          {s}
        </Tag>
      ),
    },
    {
      title: "",
      key: "actions",
      width: 60,
      render: (_, record) =>
        canWrite ? (
          <Popconfirm
            title="确定删除此文档？"
            onConfirm={() => handleDeleteDoc(record.id)}
            okText="删除"
            okType="danger"
            cancelText="取消"
          >
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        ) : null,
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <PageHeader
        current="知识库"
        subRow={<span style={{ color: '#999', fontSize: 13 }}>管理知识库文档，智能体可在对话中自动检索相关知识</span>}
        extra={
          <Space>
            <Button icon={<SearchOutlined />} onClick={() => setSearchOpen(true)}>
              搜索知识库
            </Button>
            <Button icon={<ReloadOutlined />} onClick={loadBases} />
            {canWrite && (
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={() => setCreateOpen(true)}
              >
                新建知识库
              </Button>
            )}
          </Space>
        }
      />

      <Card>
        <Table
          columns={columns}
          dataSource={bases}
          rowKey="id"
          loading={loading}
          locale={{ emptyText: <Empty description="暂无知识库，点击上方按钮创建" /> }}
          pagination={false}
        />
      </Card>

      {/* ── Create Modal ── */}
      <Modal
        title="新建知识库"
        open={createOpen}
        onOk={handleCreate}
        onCancel={() => {
          setCreateOpen(false);
          createForm.resetFields();
        }}
        confirmLoading={creating}
        okText="创建"
        cancelText="取消"
      >
        <Form form={createForm} layout="vertical">
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: "请输入知识库名称" }]}
          >
            <Input placeholder="例如：产品文档、API 手册" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <TextArea rows={2} placeholder="可选描述" />
          </Form.Item>
          <Form.Item name="scope" label="作用域" initialValue="global">
            <Select options={SCOPE_OPTIONS} />
          </Form.Item>
        </Form>
      </Modal>

      {/* ── Document Drawer ── */}
      <Drawer
        title={
          <Space>
            <FileTextOutlined />
            <span>{selectedBase?.name} — 文档管理</span>
          </Space>
        }
        open={docDrawerOpen}
        onClose={() => {
          setDocDrawerOpen(false);
          setSelectedBase(null);
          setDocuments([]);
        }}
        width={640}
        extra={
          canWrite ? (
            <Upload
              accept=".md,.txt,.json,.csv,.html"
              showUploadList={false}
              beforeUpload={handleUpload}
            >
              <Button
                type="primary"
                icon={<UploadOutlined />}
                loading={uploading}
              >
                上传文档
              </Button>
            </Upload>
          ) : undefined
        }
      >
        {docLoading ? (
          <div style={{ textAlign: "center", padding: 40 }}>
            <Spin />
          </div>
        ) : (
          <Table
            columns={docColumns}
            dataSource={documents}
            rowKey="id"
            size="small"
            pagination={false}
            locale={{ emptyText: <Empty description="暂无文档，点击右上角上传" /> }}
          />
        )}
      </Drawer>

      {/* ── Search Modal ── */}
      <Modal
        title="搜索知识库"
        open={searchOpen}
        onCancel={() => {
          setSearchOpen(false);
          setSearchText("");
          setSearchResults([]);
        }}
        footer={null}
        width={720}
      >
        <Space.Compact style={{ width: "100%", marginBottom: 16 }}>
          <Input
            placeholder="输入关键词搜索..."
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            onPressEnter={handleSearch}
          />
          <Button
            type="primary"
            icon={<SearchOutlined />}
            loading={searching}
            onClick={handleSearch}
          >
            搜索
          </Button>
        </Space.Compact>

        {searchResults.length > 0 ? (
          <div style={{ maxHeight: 400, overflow: "auto" }}>
            {searchResults.map((r) => (
              <Card
                key={r.chunk_id}
                size="small"
                style={{ marginBottom: 8 }}
                title={
                  <Space>
                    <Text type="secondary">[{r.score.toFixed(2)}]</Text>
                    <Text>{r.source_title || "未知来源"}</Text>
                  </Space>
                }
              >
                <Paragraph
                  style={{ marginBottom: 0, whiteSpace: "pre-wrap" }}
                  ellipsis={{ rows: 3, expandable: true }}
                >
                  {r.text}
                </Paragraph>
              </Card>
            ))}
          </div>
        ) : searchText && !searching ? (
          <Empty description="未找到相关内容" />
        ) : null}
      </Modal>
    </div>
  );
}
