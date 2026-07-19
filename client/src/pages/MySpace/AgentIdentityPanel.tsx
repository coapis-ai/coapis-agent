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
  Segmented,
  List,
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
  CalendarOutlined,
  FileOutlined,
} from "@ant-design/icons";

import { agentsApi } from "@/api/modules/agents";
import { workspaceApi } from "@/api/modules/workspace";
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

interface MemoryFileInfo {
  filename: string;
  path: string;
  size: number;
  created_time: string;
  modified_time: string;
  date: string;
  updated_at: number;
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

  // Two-level memory state
  const [memoryLevel, setMemoryLevel] = useState<"user" | "agent">("user");
  const [memoryContent, setMemoryContent] = useState<Record<string, { content: string; originalContent: string; modified: boolean; loading: boolean }>>({});
  
  // Memory files list state
  const [memoryFiles, setMemoryFiles] = useState<MemoryFileInfo[]>([]);
  const [loadingMemoryFiles, setLoadingMemoryFiles] = useState(false);
  const [selectedMemoryDate, setSelectedMemoryDate] = useState<string | null>(null);
  const [selectedMemoryContent, setSelectedMemoryContent] = useState<string>("");
  const [loadingSelectedMemory, setLoadingSelectedMemory] = useState(false);

  const currentAgent = agents?.find((a) => a.id === selectedAgent);
  const agentId = selectedAgent;
  const agentName = currentAgent?.name || selectedAgent;

  // Load two-level memory content
  const loadMemoryContent = useCallback(async (level: "user" | "agent") => {
    if (!agentId) return;
    setMemoryContent(prev => ({
      ...prev,
      [level]: { ...prev[level], loading: true },
    }));
    try {
      const res = await workspaceApi.getMemoryContent(level, agentId);
      const content = res.content || "";
      setMemoryContent(prev => ({
        ...prev,
        [level]: { content, originalContent: content, modified: false, loading: false },
      }));
    } catch {
      setMemoryContent(prev => ({
        ...prev,
        [level]: { content: "", originalContent: "", modified: false, loading: false },
      }));
    }
  }, [agentId]);

  // Save two-level memory content
  const handleSaveMemory = async (level: "user" | "agent") => {
    if (!agentId) return;
    const mem = memoryContent[level];
    if (!mem) return;
    setSaving(true);
    try {
      await workspaceApi.saveMemoryContent(level, mem.content, agentId);
      message.success(`${level === "user" ? "用户级" : "智能体级"}记忆保存成功`);
      setMemoryContent(prev => ({
        ...prev,
        [level]: { ...prev[level], originalContent: mem.content, modified: false },
      }));
    } catch (e: any) {
      message.error(e?.message || "保存失败");
    } finally {
      setSaving(false);
    }
  };

  // Load memory on agent change and level switch
  useEffect(() => {
    if (agentId) {
      loadMemoryContent(memoryLevel);
    }
  }, [agentId, memoryLevel, loadMemoryContent]);

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

  // Load memory files list (daily notes)
  const loadMemoryFiles = useCallback(async () => {
    setLoadingMemoryFiles(true);
    try {
      const files = await workspaceApi.listDailyMemory();
      // Sort by date descending (newest first)
      const sorted = files.sort((a: any, b: any) => b.updated_at - a.updated_at);
      setMemoryFiles(sorted);
    } catch (error: any) {
      console.error('Failed to load memory files:', error);
      setMemoryFiles([]);
    } finally {
      setLoadingMemoryFiles(false);
    }
  }, []);

  // Load selected memory file content
  const loadSelectedMemoryContent = useCallback(async (date: string) => {
    setLoadingSelectedMemory(true);
    try {
      const res = await workspaceApi.loadDailyMemory(date);
      setSelectedMemoryContent(res.content || "");
    } catch (error: any) {
      console.error('Failed to load memory file:', error);
      setSelectedMemoryContent("");
    } finally {
      setLoadingSelectedMemory(false);
    }
  }, []);

  // Load memory files on component mount
  useEffect(() => {
    loadMemoryFiles();
  }, [loadMemoryFiles]);

  // Load selected memory content when date changes
  useEffect(() => {
    if (selectedMemoryDate) {
      loadSelectedMemoryContent(selectedMemoryDate);
    }
  }, [selectedMemoryDate, loadSelectedMemoryContent]);

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

  // ── Render MEMORY.md tab with two-level editor ──
  const renderMemoryTab = () => {
    return (
      <Tabs defaultActiveKey="long-term" style={{ padding: "8px 0" }}>
        <Tabs.TabPane
          key="long-term"
          tab={
            <Space size={4}>
              <DatabaseOutlined />
              <span>长期记忆</span>
            </Space>
          }
        >
          {renderLongTermMemory()}
        </Tabs.TabPane>
        <Tabs.TabPane
          key="daily"
          tab={
            <Space size={4}>
              <CalendarOutlined />
              <span>每日笔记</span>
              {memoryFiles.length > 0 && (
                <Tag color="blue" style={{ marginLeft: 4 }}>
                  {memoryFiles.length}
                </Tag>
              )}
            </Space>
          }
        >
          {renderDailyMemory()}
        </Tabs.TabPane>
      </Tabs>
    );
  };

  const renderLongTermMemory = () => {
    const mem = memoryContent[memoryLevel];
    const isModified = mem?.modified ?? false;
    const isPreview = previewMode["MEMORY.md"] ?? false;

    return (
      <div>
        {/* Level switcher */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: 12,
          }}
        >
          <Space>
            <Segmented
              value={memoryLevel}
              onChange={(val) => setMemoryLevel(val as "user" | "agent")}
              options={[
                {
                  label: (
                    <Space size={4}>
                      <UserOutlined />
                      <span>用户级</span>
                    </Space>
                  ),
                  value: "user",
                },
                {
                  label: (
                    <Space size={4}>
                      <DatabaseOutlined />
                      <span>智能体级</span>
                    </Space>
                  ),
                  value: "agent",
                },
              ]}
            />
            {isModified && <Tag color="orange">已修改</Tag>}
          </Space>
          <Space>
            <Button
              size="small"
              icon={isPreview ? <EditOutlined /> : <EyeOutlined />}
              onClick={() => togglePreview("MEMORY.md")}
            >
              {isPreview ? "编辑" : "预览"}
            </Button>
            <Button
              size="small"
              icon={<ReloadOutlined />}
              onClick={() => loadMemoryContent(memoryLevel)}
              disabled={mem?.loading}
            >
              刷新
            </Button>
            <Button
              type="primary"
              size="small"
              icon={<SaveOutlined />}
              onClick={() => handleSaveMemory(memoryLevel)}
              disabled={!isModified || saving}
              loading={saving}
            >
              保存
            </Button>
          </Space>
        </div>

        <Text type="secondary" style={{ display: "block", marginBottom: 8 }}>
          {memoryLevel === "user"
            ? "用户级记忆：跨所有智能体共享的偏好、习惯和项目上下文"
            : "智能体级记忆：仅此智能体拥有的专业知识和技能经验"}
        </Text>

        {/* Editor / Preview */}
        {isPreview ? (
          <div
            style={{
              background: "#fafafa",
              border: "1px solid #e8e8e8",
              borderRadius: 8,
              padding: 20,
              minHeight: 400,
              maxHeight: "calc(100vh - 400px)",
              overflow: "auto",
            }}
          >
            {mem?.content ? (
              <XMarkdown>{stripFrontmatter(mem.content)}</XMarkdown>
            ) : (
              <Text type="secondary">记忆为空</Text>
            )}
          </div>
        ) : (
          <TextArea
            value={mem?.content ?? ""}
            onChange={(e) => {
              const newContent = e.target.value;
              setMemoryContent((prev) => ({
                ...prev,
                [memoryLevel]: {
                  ...prev[memoryLevel],
                  content: newContent,
                  modified: newContent !== prev[memoryLevel]?.originalContent,
                },
              }));
            }}
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
            placeholder={`编辑${memoryLevel === "user" ? "用户级" : "智能体级"}记忆...`}
          />
        )}
      </div>
    );
  };

  const renderDailyMemory = () => {
    return (
      <div style={{ display: "flex", gap: 16, height: "calc(100vh - 300px)" }}>
        {/* Left: Memory files list */}
        <div style={{ width: 280, borderRight: "1px solid #f0f0f0", paddingRight: 16 }}>
          <div style={{ marginBottom: 12 }}>
            <Text strong>记忆文件列表</Text>
            <Button
              size="small"
              icon={<ReloadOutlined />}
              onClick={loadMemoryFiles}
              loading={loadingMemoryFiles}
              style={{ float: "right" }}
            >
              刷新
            </Button>
          </div>
          
          {loadingMemoryFiles ? (
            <div style={{ textAlign: "center", padding: 40 }}>
              <Spin />
            </div>
          ) : memoryFiles.length === 0 ? (
            <Empty description="暂无记忆文件" />
          ) : (
            <List
              dataSource={memoryFiles}
              renderItem={(file) => (
                <List.Item
                  onClick={() => setSelectedMemoryDate(file.date)}
                  style={{
                    cursor: "pointer",
                    backgroundColor: selectedMemoryDate === file.date ? "#e6f7ff" : "transparent",
                    borderRadius: 4,
                    padding: "8px 12px",
                  }}
                >
                  <List.Item.Meta
                    avatar={<FileOutlined style={{ fontSize: 18, color: "#1890ff" }} />}
                    title={file.date}
                    description={`${(file.size / 1024).toFixed(1)} KB`}
                  />
                </List.Item>
              )}
              style={{ maxHeight: "calc(100vh - 380px)", overflow: "auto" }}
            />
          )}
        </div>

        {/* Right: Selected memory content */}
        <div style={{ flex: 1 }}>
          {selectedMemoryDate ? (
            <div>
              <div style={{ marginBottom: 12 }}>
                <Text strong style={{ fontSize: 16 }}>
                  {selectedMemoryDate}
                </Text>
              </div>
              
              {loadingSelectedMemory ? (
                <div style={{ textAlign: "center", padding: 40 }}>
                  <Spin />
                </div>
              ) : (
                <div
                  style={{
                    background: "#fafafa",
                    border: "1px solid #e8e8e8",
                    borderRadius: 8,
                    padding: 20,
                    maxHeight: "calc(100vh - 380px)",
                    overflow: "auto",
                  }}
                >
                  {selectedMemoryContent ? (
                    <XMarkdown>{stripFrontmatter(selectedMemoryContent)}</XMarkdown>
                  ) : (
                    <Text type="secondary">文件内容为空</Text>
                  )}
                </div>
              )}
            </div>
          ) : (
            <div style={{ textAlign: "center", padding: 80 }}>
              <Empty description="请从左侧选择一个日期查看记忆内容" />
            </div>
          )}
        </div>
      </div>
    );
  };

  // ── Render regular file tabs ──
  const tabItems = IDENTITY_FILES.map((f) => {
    // MEMORY.md gets special two-level editor
    if (f.key === "MEMORY.md") {
      const mem = memoryContent[memoryLevel];
      const isModified = mem?.modified ?? false;
      return {
        key: f.key,
        label: (
          <Space size={4}>
            {f.icon}
            <span>{f.label}</span>
            {isModified && <Tag color="orange" style={{ marginLeft: 4 }}>已修改</Tag>}
          </Space>
        ),
        children: renderMemoryTab(),
      };
    }

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
