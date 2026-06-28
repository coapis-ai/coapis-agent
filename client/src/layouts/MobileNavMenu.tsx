import { Menu, Select, Avatar, Tag, Divider } from "antd";
import { useNavigate, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAgentStore } from "../stores/agentStore";
import { getAgentDisplayName } from "../utils/agentDisplayName";
import { useUser } from "../contexts/UserContext";
import { GlobalOutlined, LogoutOutlined } from "@ant-design/icons";
import { languageApi } from "../api/modules/language";
import ModelSelector from "../pages/Chat/ModelSelector";
import {
  SparkChatTabFill,
  SparkWifiLine,
  SparkUserGroupLine,
  SparkDateLine,
  SparkVoiceChat01Line,
  SparkMagicWandLine,
  SparkToolLine,
  SparkMcpMcpLine,
  // SparkScanLine,  // ACP 模块已隐藏 — 2026-06-28
  SparkModifyLine,
  SparkModePlazaLine,
  SparkBarChartLine,
  SparkAgentLine,
  SparkSaveLine,
} from "@agentscope-ai/icons";

interface MobileNavMenuProps {
  onNavigate?: () => void;
}

const NAV_ITEMS = [
  { key: "/chat", icon: <SparkChatTabFill size={16} />, labelKey: "nav.chat" },
  { key: "/channels", icon: <SparkWifiLine size={16} />, labelKey: "nav.channels" },
  { key: "/sessions", icon: <SparkUserGroupLine size={16} />, labelKey: "nav.sessions" },
  { key: "/cron-jobs", icon: <SparkDateLine size={16} />, labelKey: "nav.cronJobs" },
  { key: "/heartbeat", icon: <SparkVoiceChat01Line size={16} />, labelKey: "nav.heartbeat" },
  { key: "/skills", icon: <SparkMagicWandLine size={16} />, labelKey: "nav.skills" },
  { key: "/tools", icon: <SparkToolLine size={16} />, labelKey: "nav.tools" },
  { key: "/mcp", icon: <SparkMcpMcpLine size={16} />, labelKey: "nav.mcp" },
  // ACP 模块已隐藏 — 2026-06-28
  // { key: "/acp", icon: <SparkScanLine size={16} />, labelKey: "nav.acp" },
  { key: "/agent-config", icon: <SparkModifyLine size={16} />, labelKey: "nav.agentConfig" },
  { key: "/agent-stats", icon: <SparkBarChartLine size={16} />, labelKey: "nav.agentStats" },
  { key: "/agents", icon: <SparkAgentLine size={16} />, labelKey: "nav.agents" },
  { key: "/models", icon: <SparkModePlazaLine size={16} />, labelKey: "nav.models" },
  { key: "/backups", icon: <SparkSaveLine size={16} />, labelKey: "nav.backups" },
];

export default function MobileNavMenu({ onNavigate }: MobileNavMenuProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const { t, i18n } = useTranslation();
  const { selectedAgent, agents, setSelectedAgent } = useAgentStore();
  const { user, logout } = useUser();

  const changeLanguage = (lang: string) => {
    i18n.changeLanguage(lang);
    localStorage.setItem("language", lang);
    languageApi.updateLanguage(lang).catch(() => {});
  };

  const currentLangKey = (i18n.resolvedLanguage || i18n.language).split("-")[0];

  const langItems = [
    { key: "en", label: "English", onClick: () => changeLanguage("en") },
    { key: "zh", label: "简体中文", onClick: () => changeLanguage("zh") },
    { key: "ja", label: "日本語", onClick: () => changeLanguage("ja") },
    { key: "ru", label: "Русский", onClick: () => changeLanguage("ru") },
  ];

  const displayName = user?.display_name || user?.username || "";
  const initials = displayName.charAt(0).toUpperCase();
  const roleLabels: Record<string, string> = {
    visitor: t("header.profile.roleVisitor"),
    user: t("header.profile.roleUser"),
    admin: t("header.profile.roleAdmin"),
    superadmin: t("header.profile.roleSuperadmin"),
  };
  const roleColors: Record<string, string> = {
    visitor: "default", user: "blue", admin: "orange", superadmin: "red",
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* Agent selector */}
      <div style={{ padding: "12px 12px", borderBottom: "1px solid rgba(0,0,0,0.06)" }}>
        <Select
          style={{ width: "100%" }}
          value={selectedAgent || undefined}
          onChange={(val: string) => {
            setSelectedAgent(val);
            navigate("/chat");
            onNavigate?.();
          }}
          placeholder={t("sidebar.selectAgent")}
          options={agents.map((a: any) => ({
            value: a.id,
            label: getAgentDisplayName(a, t),
          }))}
        />
      </div>

      {/* Model selector */}
      <div style={{ padding: "0 12px 8px", borderBottom: "1px solid rgba(0,0,0,0.06)" }}>
        <ModelSelector />
      </div>

      {/* Navigation */}
      <Menu
        mode="inline"
        selectedKeys={[location.pathname]}
        items={NAV_ITEMS.map((item) => ({
          key: item.key,
          icon: item.icon,
          label: t(item.labelKey),
        }))}
        onClick={({ key }) => {
          navigate(key);
          onNavigate?.();
        }}
        style={{ borderInlineEnd: "none", flex: 1 }}
      />

      {/* Bottom section: language + user info */}
      <div style={{ borderTop: "1px solid rgba(0,0,0,0.06)", padding: "8px 12px" }}>
        {/* Language switcher */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
          <GlobalOutlined style={{ fontSize: 14, color: "rgba(0,0,0,0.45)" }} />
          <Select
            size="small"
            value={currentLangKey}
            onChange={changeLanguage}
            style={{ width: 120 }}
            bordered={false}
            options={langItems.map((item) => ({ value: item.key, label: item.label }))}
          />
        </div>

        {/* User info */}
        {user && (
          <>
            <Divider style={{ margin: "4px 0" }} />
            <div
              style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 0" }}
              onClick={() => {
                navigate("/user/profile");
                onNavigate?.();
              }}
            >
              <Avatar
                size={28}
                style={{ backgroundColor: "#722ed1", color: "#fff", fontSize: 12, cursor: "pointer" }}
              >
                {initials}
              </Avatar>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {displayName}
                </div>
                <Tag
                  color={roleColors[user.role] || "default"}
                  style={{ padding: "0 4px", fontSize: 10, marginTop: 2 }}
                >
                  {roleLabels[user.role] || user.role}
                </Tag>
              </div>
              <LogoutOutlined
                style={{ fontSize: 14, color: "rgba(0,0,0,0.45)", cursor: "pointer" }}
                onClick={(e) => {
                  e.stopPropagation();
                  logout();
                }}
              />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
