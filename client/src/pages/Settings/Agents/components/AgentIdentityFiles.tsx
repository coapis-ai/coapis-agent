import { useState, useEffect, useCallback } from "react";
import {
  Drawer,
  Tabs,
  Input,
  Button,
  Space,
  Typography,
  Spin,
  Tag,
  Switch,
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
  EyeOutlined,
  EditOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { agentsApi } from "@/api/modules/agents";
import { workspaceApi } from "@/api/modules/workspace";
import { useAppMessage } from "@/hooks/useAppMessage";
import { XMarkdown } from "@ant-design/x-markdown";
import { stripFrontmatter } from "@/utils/markdown";

const { Text } = Typography;

interface AgentIdentityFilesProps {
  open: boolean;
  agentId: string | null;
  agentName: string;
  onClose: () => void;
}

interface FileInfo {
  name: string;
  content: string;
  originalContent: string;
  modified: boolean;
  loading: boolean;
}

const IDENTITY_FILES = [
  { key: "AGENTS.md", label: "AGENTS.md", icon: <BookOutlined />, desc: "工作手册 — 工具使用、记忆管理、响应风格" },
  { key: "SOUL.md", label: "SOUL.md", icon: <FileTextOutlined />, desc: "智能体灵魂 — 性格、准则、行为风格" },
  { key: "PROFILE.md", label: "PROFILE.md", icon: <UserOutlined />, desc: "用户资料 — 身份信息、偏好" },
  { key: "MEMORY.md", label: "MEMORY.md", icon: <DatabaseOutlined />, desc: "长期记忆 — 经验、决策、笔记" },
  { key: "BOOTSTRAP.md", label: "BOOTSTRAP.md", icon: <RocketOutlined />, desc: "首次引导 — 新用户初始化配置" },
  { key: "HEARTBEAT.md", label: "HEARTBEAT.md", icon: <SettingOutlined />, desc: "心跳检查 — 定期自检任务" },
];

export default function AgentIdentityFiles({
  open,
  agentId,
  agentName,
  onClose,
}: AgentIdentityFilesProps) {
  const { t } = useTranslation();
  const { message: msg } = useAppMessage();
  const [activeTab, setActiveTab] = useState("AGENTS.md");
  const [files, setFiles] = useState<Record<string, FileInfo>>({});
  const [saving, setSaving] = useState(false);
  const [enabledFiles, setEnabledFiles] = useState<string[]>([]);
  const [enabledLoading, setEnabledLoading] = useState(false);
  const [previewMode, setPreviewMode] = useState<Record<string, boolean>>({});

  // Load file content
  const loadFile = useCallback(
    async (fileName: string) => {
      if (!agentId) return;
      setFiles((prev) => ({
        ...prev,
        [fileName]: { ...prev[fileName], loading: true, name: fileName } as FileInfo,
      }));
      try {
        const content = await agentsApi.readWorkingFile(agentId, fileName);
        const text = (content as any)?.content ?? "";
        setFiles((prev) => ({
          ...prev,
          [fileName]: {
            name: fileName,
            content: text,
            originalContent: text,
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

  // Load enabled files list
  const loadEnabledFiles = useCallback(async () => {
    if (!agentId) return;
    setEnabledLoading(true);
    try {
      const list = await workspaceApi.getSystemPromptFiles(agentId || undefined);
      setEnabledFiles(list || []);
    } catch {
      setEnabledFiles([]);
    } finally {
      setEnabledLoading(false);
    }
  }, [agentId]);

  // Load all on open
  useEffect(() => {
    if (open && agentId) {
      IDENTITY_FILES.forEach((f) => loadFile(f.key));
      loadEnabledFiles();
      setPreviewMode({});
    }
  }, [open, agentId, loadFile, loadEnabledFiles]);

  // Handle content change
  const handleContentChange = (fileName: string, content: string) => {
    setFiles((prev) => ({
      ...prev,
      [fileName]: {
        ...prev[fileName],
        content,
        modified: content !== prev[fileName]?.originalContent,
      },
    }));
  };

  // Save single file
  const handleSave = async (fileName: string) => {
    if (!agentId) return;
    const file = files[fileName];
    if (!file) return;
    setSaving(true);
    try {
      await agentsApi.writeWorkingFile(agentId, fileName, file.content);
      setFiles((prev) => ({
        ...prev,
        [fileName]: {
          ...prev[fileName],
          originalContent: file.content,
          modified: false,
        },
      }));
      msg.success(t("agent.identityFileSaved", "已保存") + `: ${fileName}`);
    } catch (err: any) {
      msg.error(err?.message || t("agent.identityFileSaveFailed", "保存失败"));
    } finally {
      setSaving(false);
    }
  };

  // Reload single file
  const handleReload = (fileName: string) => {
    loadFile(fileName);
  };

  // Toggle enabled/disabled
  const handleToggleEnabled = async (fileName: string, checked: boolean) => {
    let newList: string[];
    if (checked) {
      newList = [...enabledFiles, fileName];
    } else {
      newList = enabledFiles.filter((f) => f !== fileName);
    }
    // Deduplicate
    newList = [...new Set(newList)];
    setEnabledFiles(newList);
    try {
      await workspaceApi.setSystemPromptFiles(newList, agentId || undefined);
      msg.success(
        checked
          ? t("agent.fileEnabled", "已启用") + `: ${fileName}`
          : t("agent.fileDisabled", "已禁用") + `: ${fileName}`
      );
    } catch (err: any) {
      // Revert on error
      setEnabledFiles((prev) =>
        checked ? prev.filter((f) => f !== fileName) : [...prev, fileName]
      );
      msg.error(err?.message || t("common.error", "操作失败"));
    }
  };

  // Toggle preview mode for a file
  const togglePreview = (fileName: string) => {
    setPreviewMode((prev) => ({ ...prev, [fileName]: !prev[fileName] }));
  };

  const tabItems = IDENTITY_FILES.map((f) => {
    const file = files[f.key];
    const isEnabled = enabledFiles.includes(f.key);
    const isPreview = previewMode[f.key] ?? true; // default to preview

    return {
      key: f.key,
      label: (
        <Space size={4} align="center">
          {f.icon}
          <span>{f.label}</span>
          {!enabledLoading && (
            <Switch
              size="small"
              checked={isEnabled}
              onChange={(checked) => handleToggleEnabled(f.key, checked)}
              style={{ marginLeft: 4 }}
            />
          )}
          {file?.modified && <Tag color="orange" style={{ marginLeft: 2 }}>*</Tag>}
        </Space>
      ),
      children: (
        <div style={{ padding: "8px 0" }}>
          <Text type="secondary" style={{ display: "block", marginBottom: 8 }}>
            {f.desc}
            {!isEnabled && (
              <Tag color="red" style={{ marginLeft: 8 }}>
                {t("agent.fileDisabledTag", "未启用")}
              </Tag>
            )}
          </Text>
          <div style={{ marginBottom: 8 }}>
            <Space>
              <Button
                size="small"
                icon={isPreview ? <EditOutlined /> : <EyeOutlined />}
                onClick={() => togglePreview(f.key)}
              >
                {isPreview
                  ? t("common.edit", "编辑")
                  : t("common.preview", "预览")}
              </Button>
              <Button
                size="small"
                icon={<SaveOutlined />}
                onClick={() => handleSave(f.key)}
                disabled={!file?.modified}
                loading={saving}
                type="primary"
              >
                {t("common.save", "保存")}
              </Button>
              <Button
                size="small"
                icon={<ReloadOutlined />}
                onClick={() => handleReload(f.key)}
              >
                {t("common.reload", "刷新")}
              </Button>
              {file?.modified && (
                <Text type="warning" style={{ fontSize: 12 }}>
                  {t("agent.unsavedChanges", "有未保存的更改")}
                </Text>
              )}
            </Space>
          </div>
          {isPreview ? (
            <div
              style={{
                border: "1px solid #d9d9d9",
                borderRadius: 6,
                padding: 16,
                minHeight: 400,
                maxHeight: 600,
                overflow: "auto",
                background: "#fafafa",
              }}
            >
              <XMarkdown>{stripFrontmatter(file?.content ?? "")}</XMarkdown>
            </div>
          ) : (
            <Input.TextArea
              value={file?.content ?? ""}
              onChange={(e) => handleContentChange(f.key, e.target.value)}
              placeholder={`${f.label}...`}
              autoSize={{ minRows: 15, maxRows: 30 }}
              style={{ fontFamily: "monospace", fontSize: 13 }}
              disabled={file?.loading}
            />
          )}
        </div>
      ),
    };
  });

  return (
    <Drawer
      title={
        <Space>
          <FileTextOutlined />
          <span>
            {t("agent.identityFiles", "身份文件")} — {agentName}
          </span>
        </Space>
      }
      open={open}
      onClose={onClose}
      width={800}
      destroyOnClose
    >
      <Spin spinning={Object.values(files).some((f) => f?.loading)}>
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={tabItems}
        />
      </Spin>
    </Drawer>
  );
}
