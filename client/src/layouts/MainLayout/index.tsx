import { Suspense, useEffect } from "react";
import { Layout, Spin } from "antd";
import { Routes, Route, useLocation, Navigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { MessageOutlined, CloseOutlined } from "@ant-design/icons";
import Sidebar from "../Sidebar";
import Header from "../Header";
import useIsMobile from "../../hooks/useIsMobile";
import ConsolePollService from "../../components/ConsolePollService";
import { ChunkErrorBoundary } from "../../components/ChunkErrorBoundary";
import { lazyImportWithRetry } from "../../utils/lazyWithRetry";
import { usePlugins } from "../../plugins/PluginContext";
import { agentsApi } from "../../api/modules/agents";
import { useAgentStore } from "../../stores/agentStore";
import { isDefaultAgent } from "../../utils/agentDisplayName";
import FloatingChatWindow from "../../components/FloatingChatWindow";
import { useChatWindow } from "../../contexts/ChatWindowContext";
import styles from "../index.module.less";

// Chat is eagerly loaded (default landing page)
import Chat from "../../pages/Chat";

// All other pages are lazily loaded with automatic retry on chunk failure
const ChannelsPage = lazyImportWithRetry("../../pages/Control/Channels");
const SessionsPage = lazyImportWithRetry("../../pages/Control/Sessions");
const CronJobsPage = lazyImportWithRetry("../../pages/Control/CronJobs");
const HeartbeatPage = lazyImportWithRetry("../../pages/Control/Heartbeat");
const AgentConfigPage = lazyImportWithRetry("../../pages/Agent/Config");
const SkillsPage = lazyImportWithRetry("../../pages/Agent/Skills");
const ToolsPage = lazyImportWithRetry("../../pages/Agent/Tools");
const WorkspacePage = lazyImportWithRetry("../../pages/Agent/Workspace");
const MCPPage = lazyImportWithRetry("../../pages/Agent/MCP");
// ACP 模块已隐藏 — 2026-06-28
// const ACPPage = lazyImportWithRetry("../../pages/Agent/ACP");
const SettingsPage = lazyImportWithRetry("../../pages/Settings");
const ModelsPage = lazyImportWithRetry("../../pages/Settings/Models");
// 环境变量功能已隐藏 — 2026-07-05
// const EnvironmentsPage = lazyImportWithRetry(
//   "../../pages/Settings/Environments",
// );
const SecurityPage = lazyImportWithRetry("../../pages/Settings/Security");
const TokenUsagePage = lazyImportWithRetry("../../pages/Settings/TokenUsage");
const AgentStatsPage = lazyImportWithRetry("../../pages/Settings/AgentStats");
const VoiceTranscriptionPage = lazyImportWithRetry(
  "../../pages/Settings/VoiceTranscription",
);
const AgentsPage = lazyImportWithRetry("../../pages/Settings/Agents");
const DebugPage = lazyImportWithRetry("../../pages/Settings/Debug");
const BackupsPage = lazyImportWithRetry("../../pages/Settings/Backups");
const MySpacePage = lazyImportWithRetry("../../pages/MySpace/index");
const UserSystemPage = lazyImportWithRetry("../../pages/UserSystem/index");
const UserProfilePage = lazyImportWithRetry("../../pages/UserProfile/index");
const AdminPage = lazyImportWithRetry("../../pages/Admin/index");
const AdminOverviewPage = lazyImportWithRetry("../../pages/Admin/Overview");
const AdminUsersPage = lazyImportWithRetry("../../pages/Admin/Users");
const AdminPermissionsPage = lazyImportWithRetry("../../pages/Admin/Permissions");
const AdminAuditPage = lazyImportWithRetry("../../pages/Admin/Audit");
const AdminConfigPage = lazyImportWithRetry("../../pages/Admin/Config");
const AdminScenesPage = lazyImportWithRetry("../../pages/Admin/Scenes");
const AdminTagsPage = lazyImportWithRetry("../../pages/Admin/Tags");
const MultiLayerEvolutionPage = lazyImportWithRetry("../../pages/MultiLayerEvolution/index");
const WorkbenchPage = lazyImportWithRetry("../../pages/Workbench/index");
// 知识库功能 - 企业版扩展
const KnowledgeBasePage = lazyImportWithRetry("../../pages/KnowledgeBase/index");

// P2 Enterprise Features
const MonitoringPage = lazyImportWithRetry("../../pages/Monitoring/index");
const SSOPage = lazyImportWithRetry("../../pages/SSO/index");

const { Content } = Layout;

const pathToKey: Record<string, string> = {
  "/chat": "chat",
  "/channels": "channels",
  "/sessions": "sessions",
  "/cron-jobs": "cron-jobs",
  "/heartbeat": "heartbeat",
  "/skills": "skills",
  "/tools": "tools",
  "/mcp": "mcp",
  // ACP 模块已隐藏 — 2026-06-28
  // "/acp": "acp",
  "/workspace": "workspace",
  "/agents": "agents",
  "/models": "models",
  // "/environments": "environments",
  "/agent-config": "agent-config",
  "/security": "security",
  "/token-usage": "token-usage",
  "/agent-stats": "agent-stats",
  "/voice-transcription": "voice-transcription",
  "/debug": "debug",
  "/backups": "backups",
  "/workspace/myspace": "myspace",
  "/user-system": "user-system",
  "/user/profile": "user-profile",
  "/settings": "settings",
  "/admin": "admin",
  "/admin/overview": "admin-overview",
  "/admin/users": "admin-users",
  "/admin/permissions": "admin-permissions",
  "/admin/audit": "admin-audit",
  "/admin/config": "admin-config",
  "/admin/scenes": "admin-scenes",
  "/admin/tags": "admin-tags",
  "/evolution": "evolution",
  "/workbench": "workbench",
  // "/knowledge": "knowledge",
  // P2 Enterprise Features
  "/monitoring": "monitoring",
  "/sso": "sso",
};

export default function MainLayout() {
  const { t } = useTranslation();
  const location = useLocation();
  const currentPath = location.pathname;
  const { pluginRoutes } = usePlugins();
  const isMobile = useIsMobile();
  const { setAgents, setSelectedAgent } = useAgentStore();
  
  // 使用全局聊天窗口状态
  const { visible: chatVisible, scene: chatScene, openChat, closeChat } = useChatWindow();

  // Load agents globally (works on both desktop and mobile)
  useEffect(() => {
    agentsApi
      .listAgents()
      .then((res) => {
        const agentList = Array.isArray(res) ? res : (res as any).agents || [];
        const sorted = [...agentList].sort((a, b) => {
          const aDefault = isDefaultAgent(a.id) ? 0 : 1;
          const bDefault = isDefaultAgent(b.id) ? 0 : 1;
          return aDefault - bDefault;
        });
        setAgents(sorted);
        // Auto-select if no valid agent selected
        const current = useAgentStore.getState().selectedAgent;
        const currentValid = sorted.some((a) => a.id === current);
        if (!currentValid) {
          const defaultAgent = sorted.find((a) => isDefaultAgent(a.id));
          if (defaultAgent) {
            setSelectedAgent(defaultAgent.id);
          } else if (sorted.length > 0) {
            setSelectedAgent(sorted[0].id);
          }
        }
      })
      .catch(() => {});
  }, [setAgents, setSelectedAgent]);

  // Resolve selected key: check static routes first, then plugin routes
  let selectedKey = pathToKey[currentPath] || "";
  if (!selectedKey) {
    const matchedPlugin = pluginRoutes.find(
      (route) => currentPath === route.path,
    );
    selectedKey = matchedPlugin
      ? matchedPlugin.path.replace(/^\//, "")
      : "chat";
  }

  // Keep Chat always mounted to preserve SSE streams during navigation.
  // When user navigates away mid-stream, React Router would unmount <Chat />,
  // causing the @agentscope-ai/chat library to abort the SSE connection.
  const isChatRoute =
    currentPath === "/" || currentPath.startsWith("/chat");

  return (
    <Layout className={styles.mainLayout}>
      {!(isMobile && isChatRoute) && <Header />}
      <Layout style={isMobile ? { flexDirection: "column" } : undefined}>
        {!isMobile && <Sidebar selectedKey={selectedKey} />}
        <Content className="page-container" style={isMobile ? { width: "100%" } : undefined}>
          <ConsolePollService />
          <div className="page-content">
            {/* Chat: always mounted, hidden when not active */}
            <div style={{ display: isChatRoute ? "contents" : "none" }}>
              <ChunkErrorBoundary resetKey="chat-keepalive">
                <Chat />
              </ChunkErrorBoundary>
            </div>
            <ChunkErrorBoundary resetKey={currentPath}>
              <Suspense
                fallback={
                  <Spin
                    tip={t("common.loading")}
                    style={{ display: "block", margin: "20vh auto" }}
                  />
                }
              >
                <Routes>
                  <Route path="/" element={<Navigate to="/chat" replace />} />
                  <Route path="/chat/*" element={<div />} />
                  <Route path="/channels" element={<ChannelsPage />} />
                  <Route path="/sessions" element={<SessionsPage />} />
                  <Route path="/cron-jobs" element={<CronJobsPage />} />
                  <Route path="/heartbeat" element={<HeartbeatPage />} />
                  <Route path="/skills" element={<SkillsPage />} />
                  <Route path="/tools" element={<ToolsPage />} />
                  <Route path="/mcp" element={<MCPPage />} />
                  {/* ACP 模块已隐藏 — 2026-06-28 */}
                  {/* <Route path="/acp" element={<ACPPage />} /> */}
                  {/* <Route path="/ACP" element={<Navigate to="/acp" replace />} /> */}
                  <Route path="/workspace" element={<WorkspacePage />} />
                  <Route path="/agents" element={<AgentsPage />} />
                  <Route path="/models" element={<ModelsPage />} />
                  {/* <Route path="/environments" element={<EnvironmentsPage />} /> */}
                  <Route path="/agent-config" element={<AgentConfigPage />} />
                  <Route path="/security" element={<SecurityPage />} />
                  <Route path="/token-usage" element={<TokenUsagePage />} />
                  <Route path="/agent-stats" element={<AgentStatsPage />} />
                  <Route
                    path="/voice-transcription"
                    element={<VoiceTranscriptionPage />}
                  />
                  <Route path="/debug" element={<DebugPage />} />
                  <Route path="/backups" element={<BackupsPage />} />
                  <Route path="/workspace/myspace" element={<MySpacePage />} />
                  <Route path="/user-system" element={<UserSystemPage />} />
                  <Route path="/user/profile" element={<UserProfilePage />} />
                  <Route path="/settings" element={<SettingsPage />} />
                  <Route path="/admin" element={<AdminPage />} />
                  <Route path="/admin/overview" element={<AdminOverviewPage />} />
                  <Route path="/admin/users" element={<AdminUsersPage />} />
                  <Route path="/admin/permissions" element={<AdminPermissionsPage />} />
                  <Route path="/admin/audit" element={<AdminAuditPage />} />
                  <Route path="/admin/config" element={<AdminConfigPage />} />
                  <Route path="/admin/scenes" element={<AdminScenesPage />} />
                  <Route path="/admin/tags" element={<AdminTagsPage />} />
                  <Route path="/evolution" element={<MultiLayerEvolutionPage />} />
                  <Route path="/workbench" element={<WorkbenchPage />} />
                  <Route path="/knowledge" element={<KnowledgeBasePage />} />
                  <Route path="/cross-agent" element={<Navigate to="/evolution" replace />} />

                  {/* P2 Enterprise Features */}
                  <Route path="/monitoring" element={<MonitoringPage />} />
                  <Route path="/sso" element={<SSOPage />} />

                  {/* Plugin routes — dynamically injected at runtime */}
                  {pluginRoutes.map((route) => (
                    <Route
                      key={route.path}
                      path={route.path}
                      element={<route.component />}
                    />
                  ))}
                </Routes>
              </Suspense>
            </ChunkErrorBoundary>
          </div>
        </Content>
      </Layout>
      
      {/* 浮动聊天按钮 - 在聊天界面时隐藏 */}
      {!isChatRoute && (
        <>
          {/* 浮动按钮 */}
          <div 
            style={{
              position: 'fixed',
              right: 24,
              bottom: 24,
              zIndex: 1000,
            }}
          >
            <div
              onClick={() => {
                if (chatVisible) {
                  closeChat();
                } else {
                  openChat(null); // 无场景，使用默认智能体
                }
              }}
              style={{
                width: 56,
                height: 56,
                borderRadius: '50%',
                background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                boxShadow: '0 4px 12px rgba(102, 126, 234, 0.4)',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'white',
                transition: 'all 0.3s ease',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.transform = 'scale(1.1)';
                e.currentTarget.style.boxShadow = '0 6px 16px rgba(102, 126, 234, 0.6)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.transform = 'scale(1)';
                e.currentTarget.style.boxShadow = '0 4px 12px rgba(102, 126, 234, 0.4)';
              }}
            >
              {chatVisible ? (
                <CloseOutlined style={{ fontSize: 20 }} />
              ) : (
                <MessageOutlined style={{ fontSize: 24 }} />
              )}
            </div>
          </div>
          
          {/* 全局浮动聊天窗口 */}
          <FloatingChatWindow
            visible={chatVisible}
            scene={chatScene}
            onClose={closeChat}
          />
        </>
      )}
    </Layout>
  );
}
