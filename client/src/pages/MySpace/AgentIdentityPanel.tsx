import { useState, useEffect, useCallback } from "react";
import {
  Tabs,
  Input,
  Button,
  Space,
  Typography,
  Spin,
  Tag,
  Empty,
  message,
} from "antd";
import {
  SaveOutlined,
  ReloadOutlined,
  FileTextOutlined,
  DatabaseOutlined,
  UserOutlined,
  SettingOutlined,
  BookOutlined,
  RocketOutlined,
  EditOutlined,
  EyeOutlined,
} from "@ant-design/icons";

import { agentsApi } from "@/api/modules/agents";
import { useAgentStore } from "@/stores/agentStore";
import { XMarkdown } from "@ant-design/x-markdown";
import { stripFrontmatter } from "@/utils/markdown";

const { TextArea } = Input;
const { Text } = Typography;

interface FileInfo {
  name: string;
  content: string;
  originalContent: string;
  modified: boolean;
  loading: boolean;
}

const IDENTITY_FILES = [
  { key: "AGENTS.md", label: "AGENTS.md", icon: <BookOutlined />, desc: "工作手册" },
  { key: "SOUL.md", label: "SOUL.md", icon: <FileTextOutlined />, desc: "智能体灵魂" },
  { key: "PROFILE.md", label: "PROFILE.md", icon: <UserOutlined />, desc: "用户资料" },
  { key: "MEMORY.md", label: "MEMORY.md", icon: <DatabaseOutlined />, desc: "长期记忆" },
  { key: "BOOTSTRAP.md", label: "BOOTSTRAP.md", icon: <RocketOutlined />, desc: "首次引导" },
  { key: "HEARTBEAT.md", label: "HEARTBEAT.md", icon: <SettingOutlined />, desc: "心跳检查" },
];

export default function AgentIdentityPanel() {
  const { selectedAgent, agents } = useAgentStore();
  const [activeTab, setActiveTab] = useState("AGENTS.md");
  const [files, setFiles] = useState<Record<string, FileInfo>>({});
  const [saving, setSaving] = useState(false);
  const [previewMode, setPreviewMode] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(false);

  const currentAgent = agents?.find((a) => a.id === selectedAgent);
  const agentId = selectedAgent;
  const agentName = currentAgent?.name || selectedAgent;

  // Load file content
  const loadFile = useCallback(
    async (fileName: string) => {
      if (!agentId) return;
      setFiles((prev) => ({
        ...prev,
        [fileName]: { ...prev[fileName], loading: true, name: fileName } as FileInfo,
      }));
      try {
        const res = await agentsApi.readWorkingFile(agentId, fileName);
        const content = res.content || "";
        setFiles((prev) => ({
          ...prev,
          [fileName]: {
            name: fileName,
            content,
            originalContent: content,
            modified: false,
            loading: false,
          },
        }));
      } catch {
        setFiles((prev) => ({
          ...prev,
          [fileName]: {
            name: fileName,
            content: "",
            originalContent: "",
            modified: false,
            loading: false,
          },
        }));
      }
    },
    [agentId]
  );

  // Load all files on agent change
  useEffect(() => {
    if (!agentId) return;
    setLoading(true);
    const loadAll = async () => {
      for (const f of IDENTITY_FILES) {
        await loadFile(f.key);
      }
      setLoading(false);
    };
    loadAll();
  }, [agentId, loadFile]);

  // Save file
  const handleSave = async (fileName: string) => {
    if (!agentId) return;
    const file = files[fileName];
    if (!file) return;
    setSaving(true);
    try {
      await agentsApi.writeWorkingFile(agentId, fileName, file.content);
      message.success(`${fileName} 保存成功`);
      setFiles((prev) => ({
        ...prev,
        [fileName]: { ...prev[fileName], originalContent: file.content, modified: false },
      }));
    } catch (e: any) {
      message.error(e?.message || `${fileName} 保存失败`);
    } finally {
      setSaving(false);
    }
  };

  // Reload file
  const handleReload = (fileName: string) => {
    loadFile(fileName);
  };

  // Update content
  const updateContent = (fileName: string, content: string) => {
    setFiles((prev) => ({
      ...prev,
      [fileName]: {
        ...prev[fileName],
        content,
        modified: content !== prev[fileName]?.originalContent,
      },
    }));
  };

  // Toggle preview
  const togglePreview = (fileName: string) => {
    setPreviewMode((prev) => ({ ...prev, [fileName]: !prev[fileName] }));
  };

  if (!agentId) {
    return (
      <div style={{ textAlign: "center", padding: "80px 0" }}>
        <Empty description="请先在左上角选择一个智能体" />
      </div>
    );
  }

  if (loading) {
    return (
      <div style={{ textAlign: "center", padding: "80px 0" }}>
        <Spin size="large" tip="加载身份文件中..." />
      </div>
    );
  }

  const tabItems = IDENTITY_FILES.map((f) => {
    const file = files[f.key];
    const isModified = file?.modified ?? false;
    const isPreview = previewMode[f.key] ?? false;

    return {
      key: f.key,
      label: (
        <Space size={4}>
          {f.icon}
          <span>{f.label}</span>
          {isModified && <Tag color="orange" style={{ marginLeft: 4 }}>已修改</Tag>}
        </Space>
      ),
      children: (
        <div style={{ padding: "8px 0" }}>
          {/* 文件描述 + 操作按钮 */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginBottom: 12,
            }}
          >
            <Text type="secondary">{f.desc}</Text>
            <Space>
              <Button
                size="small"
                icon={isPreview ? <EditOutlined /> : <EyeOutlined />}
                onClick={() => togglePreview(f.key)}
              >
                {isPreview ? "编辑" : "预览"}
              </Button>
              <Button
                size="small"
                icon={<ReloadOutlined />}
                onClick={() => handleReload(f.key)}
                disabled={file?.loading}
              >
                刷新
              </Button>
              <Button
                type="primary"
                size="small"
                icon={<SaveOutlined />}
                onClick={() => handleSave(f.key)}
                disabled={!isModified || saving}
                loading={saving}
              >
                保存
              </Button>
            </Space>
          </div>

          {/* 编辑/预览区域 */}
          {isPreview ? (
            <div
              style={{
                background: "#fafafa",
                border: "1px solid #e8e8e8",
                borderRadius: 8,
                padding: 20,
                minHeight: 400,
                maxHeight: "calc(100vh - 360px)",
                overflow: "auto",
              }}
            >
              {file?.content ? (
                <XMarkdown>{stripFrontmatter(file.content)}</XMarkdown>
              ) : (
                <Text type="secondary">文件为空</Text>
              )}
            </div>
          ) : (
            <TextArea
              value={file?.content ?? ""}
              onChange={(e) => updateContent(f.key, e.target.value)}
              autoSize={{ minRows: 18, maxRows: 40 }}
              style={{
                fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
                fontSize: 13,
                lineHeight: 1.6,
                background: "#1e1e1e",
                color: "#d4d4d4",
                border: "1px solid #333",
                borderRadius: 8,
                padding: 16,
              }}
              placeholder={`编辑 ${f.label}...`}
            />
          )}
        </div>
      ),
    };
  });

  return (
    <div style={{ padding: "0 4px" }}>
      {/* Agent header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          marginBottom: 16,
          padding: "8px 0",
        }}
      >
        <FileTextOutlined style={{ fontSize: 18, color: "#736dff" }} />
        <Text strong style={{ fontSize: 15 }}>
          {agentName}
        </Text>
        <Tag color="blue">{agentId}</Tag>
      </div>

      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={tabItems}
        size="small"
      />
    </div>
  );
}
