import { Suspense } from "react";
import { Layout, Spin } from "antd";
import { Routes, Route, useLocation, Navigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import Sidebar from "../Sidebar";
import Header from "../Header";
import ConsolePollService from "../../components/ConsolePollService";
import { ChunkErrorBoundary } from "../../components/ChunkErrorBoundary";
import { lazyImportWithRetry } from "../../utils/lazyWithRetry";
import { usePlugins } from "../../plugins/PluginContext";
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
const ACPPage = lazyImportWithRetry("../../pages/Agent/ACP");
const ModelsPage = lazyImportWithRetry("../../pages/Settings/Models");
const EnvironmentsPage = lazyImportWithRetry(
  "../../pages/Settings/Environments",
);
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
const MultiLayerEvolutionPage = lazyImportWithRetry("../../pages/MultiLayerEvolution/index");
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
  "/acp": "acp",
  "/workspace": "workspace",
  "/agents": "agents",
  "/models": "models",
  "/environments": "environments",
  "/agent-config": "agent-config",
  "/security": "security",
  "/token-usage": "token-usage",
  "/agent-stats": "agent-stats",
  "/voice-transcription": "voice-transcription",
  "/debug": "debug",
  "/backups": "backups",
  "/workspace/myspace": "myspace",
  "/user-system": "user-system",
  "/evolution": "evolution",
  "/knowledge": "knowledge",
  // P2 Enterprise Features
  "/monitoring": "monitoring",
  "/sso": "sso",
};

export default function MainLayout() {
  const { t } = useTranslation();
  const location = useLocation();
  const currentPath = location.pathname;
  const { pluginRoutes } = usePlugins();

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
      <Header />
      <Layout>
        <Sidebar selectedKey={selectedKey} />
        <Content className="page-container">
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
                  <Route path="/acp" element={<ACPPage />} />
                  <Route path="/ACP" element={<Navigate to="/acp" replace />} />
                  <Route path="/workspace" element={<WorkspacePage />} />
                  <Route path="/agents" element={<AgentsPage />} />
                  <Route path="/models" element={<ModelsPage />} />
                  <Route path="/environments" element={<EnvironmentsPage />} />
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
                  <Route path="/admin" element={<AdminPage />} />
                  <Route path="/evolution" element={<MultiLayerEvolutionPage />} />
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
    </Layout>
  );
}
