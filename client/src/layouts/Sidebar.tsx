import {
  Layout,
  Menu,
  Button,
  Tooltip,
  Select,
  type MenuProps,
} from "antd";
import { useState, useEffect, useMemo } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  SparkChatTabFill,
  SparkWifiLine,
  SparkUserGroupLine,
  SparkDateLine,
  SparkVoiceChat01Line,
  SparkMagicWandLine,
  SparkLocalFileLine,
  SparkModePlazaLine,
  // SparkInternetLine,  // unused — 2026-07-06
  SparkModifyLine,
  SparkBrowseLine,
  SparkMcpMcpLine,
  // SparkScanLine,  // ACP 模块已隐藏 — 2026-06-28
  SparkToolLine,
  SparkDataLine,
  SparkMicLine,
  SparkAgentLine,
  SparkMenuExpandLine,
  SparkMenuFoldLine,
  SparkBarChartLine,
  SparkDebugLine,
  SparkSaveLine,
} from "@agentscope-ai/icons";
import { ThunderboltOutlined, CrownOutlined } from "@ant-design/icons";
import { agentsApi } from "../api/modules/agents";
import { permissionsApi } from "../api/modules/permissions";
import { usePlugins } from "../plugins/PluginContext";
import { useAgentStore } from "../stores/agentStore";
import { useUser } from "../contexts/UserContext";
import styles from "./index.module.less";
import { useTheme } from "../contexts/ThemeContext";
import { KEY_TO_PATH, DEFAULT_OPEN_KEYS } from "./constants";
import { getAgentDisplayName, isDefaultAgent } from "../utils/agentDisplayName";
import {
  MENU_TO_PERMISSION,
} from "../config/menuModules";

// ── Layout ────────────────────────────────────────────────────────────────

const { Sider } = Layout;

// ── Types ─────────────────────────────────────────────────────────────────

interface SidebarProps {
  selectedKey: string;
}

// ── Sidebar ───────────────────────────────────────────────────────────────

export default function Sidebar({ selectedKey }: SidebarProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useTranslation();
  const { isDark } = useTheme();
  const { pluginRoutes } = usePlugins();
  const { selectedAgent, agents, setSelectedAgent, setAgents } = useAgentStore();
  const { user } = useUser();
  const [collapsed, setCollapsed] = useState(false);
  
  // Check if we're on workbench route
  const isWorkbench = location.pathname === '/workbench';
  
  // For workbench, get category from URL and use it as selectedKey
  const workbenchSelectedKey = useMemo(() => {
    if (!isWorkbench) return selectedKey;
    
    const params = new URLSearchParams(location.search);
    const category = params.get('category');
    
    if (category) {
      return `category-${category}`;
    }
    
    return 'category-all';
  }, [isWorkbench, selectedKey, location.search]);
  
  // Permission state
  const [allowedModules, setAllowedModules] = useState<string[]>([]);
  const [permissionsLoaded, setPermissionsLoaded] = useState(false);

  // ── Effects ──────────────────────────────────────────────────────────────

  // Load agents on mount
  useEffect(() => {
    agentsApi
      .listAgents()
      .then((res) => {
        const agentList = Array.isArray(res) ? res : (res as any).agents || [];
        // Sort: user's default agent (user:*) first, then by API order (creation time)
        const sorted = [...agentList].sort((a, b) => {
          const aDefault = isDefaultAgent(a.id) ? 0 : 1;
          const bDefault = isDefaultAgent(b.id) ? 0 : 1;
          return aDefault - bDefault;
        });
        setAgents(sorted);

        // Auto-select: if no valid agent selected, pick the user's default agent
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
  
  // Load permissions on mount and when user changes
  useEffect(() => {
    if (!user) {
      // No user logged in, allow all modules (anonymous mode)
      setAllowedModules(["all"]);
      setPermissionsLoaded(true);
      return;
    }
    
    permissionsApi
      .getAllowedModules()
      .then((res) => {
        setAllowedModules(res.modules || []);
        setPermissionsLoaded(true);
      })
      .catch(() => {
        // Fallback: allow all modules if permission API fails
        setAllowedModules(["all"]);
        setPermissionsLoaded(true);
      });
  }, [user]);
  
  // ── Permission helpers ───────────────────────────────────────────────────

  /**
   * Maps permission module keys to sidebar menu keys.
   * Uses unified config from menuModules.ts as single source of truth.
   */
  /**
   * Reverse map: sidebar menu key -> permission module key.
   * Uses unified config from menuModules.ts as single source of truth.
   */
  const MENU_TO_PERMISSION_KEY: Record<string, string> = {
    ...MENU_TO_PERMISSION,
    // collapsedNavItems uses "workspace" key for myspace module
    workspace: "myspace",
  };

  /** Check if a module is allowed for current user */
  const isModuleAllowed = (menuKey: string): boolean => {
    if (!permissionsLoaded) return true; // Allow while loading (prevent flicker)
    if (allowedModules.includes("all")) return true; // Admin
    
    // First check direct match
    if (allowedModules.includes(menuKey)) return true;
    
    // Then check mapping (menu key -> permission module key)
    const permKey = MENU_TO_PERMISSION_KEY[menuKey];
    if (permKey && allowedModules.includes(permKey)) return true;
    
    return false;
  };
  
  /** Filter menu items based on permissions */
  const filterMenuItems = (items: any[]): any[] => {
    if (allowedModules.includes("all")) {
      return items; // Admin: allow all
    }
    if (!permissionsLoaded) {
      return items; // Loading: show all (prevent menu flicker)
    }
    
    return items.flatMap((item: any) => {
      // If item has children, filter children recursively
      if (item.children) {
        const filteredChildren = filterMenuItems(item.children);
        // Keep group if at least one child is allowed
        if (filteredChildren.length > 0) {
          return [{ ...item, children: filteredChildren }];
        }
        return []; // Remove group if no children allowed
      }
      
      // Leaf item: check if module is allowed
      return isModuleAllowed(item.key) ? [item] : [];
    });
  };

  // ── Collapsed nav items (all leaf pages) ──────────────────────────────

  const collapsedNavItems = [
    {
      key: "chat",
      icon: <SparkChatTabFill size={18} />,
      path: "/chat",
      label: t("nav.chat"),
    },
    {
      key: "workbench",
      icon: <SparkModePlazaLine size={18} />,
      path: "/workbench",
      label: t("nav.workbench", "工作台"),
    },
    {
      key: "channels",
      icon: <SparkWifiLine size={18} />,
      path: "/channels",
      label: t("nav.channels"),
    },
    {
      key: "sessions",
      icon: <SparkUserGroupLine size={18} />,
      path: "/sessions",
      label: t("nav.sessions"),
    },
    {
      key: "cron-jobs",
      icon: <SparkDateLine size={18} />,
      path: "/cron-jobs",
      label: t("nav.cronJobs"),
    },
    {
      key: "heartbeat",
      icon: <SparkVoiceChat01Line size={18} />,
      path: "/heartbeat",
      label: t("nav.heartbeat"),
    },
    // "文件"菜单已移至"我的空间"Tab中
    // {
    //   key: "workspace",
    //   icon: <SparkLocalFileLine size={18} />,
    //   path: "/workspace",
    //   label: t("nav.workspace"),
    // },
    {
      key: "skills",
      icon: <SparkMagicWandLine size={18} />,
      path: "/skills",
      label: t("nav.skills"),
    },
    {
      key: "tools",
      icon: <SparkToolLine size={18} />,
      path: "/tools",
      label: t("nav.tools"),
    },
    {
      key: "mcp",
      icon: <SparkMcpMcpLine size={18} />,
      path: "/mcp",
      label: t("nav.mcp"),
    },
    // ACP 模块已隐藏 — 2026-06-28
    // {
    //   key: "acp",
    //   icon: <SparkScanLine size={18} />,
    //   path: "/acp",
    //   label: t("nav.acp"),
    // },
    {
      key: "agent-config",
      icon: <SparkModifyLine size={18} />,
      path: "/agent-config",
      label: t("nav.agentConfig"),
    },
    {
      key: "agent-stats",
      icon: <SparkBarChartLine size={18} />,
      path: "/agent-stats",
      label: t("nav.agentStats"),
    },
    {
      key: "agents",
      icon: <SparkAgentLine size={18} />,
      path: "/agents",
      label: t("nav.agents"),
    },
    {
      key: "models",
      icon: <SparkModePlazaLine size={18} />,
      path: "/models",
      label: t("nav.models"),
    },
    // {
    //   key: "environments",
    //   icon: <SparkInternetLine size={18} />,
    //   path: "/environments",
    //   label: t("nav.environments"),
    // },
    {
      key: "security",
      icon: <SparkBrowseLine size={18} />,
      path: "/security",
      label: t("nav.security"),
    },
    {
      key: "token-usage",
      icon: <SparkDataLine size={18} />,
      path: "/token-usage",
      label: t("nav.tokenUsage"),
    },
    {
      key: "backups",
      icon: <SparkSaveLine size={18} />,
      path: "/backups",
      label: t("nav.backups"),
    },
    {
      key: "voice-transcription",
      icon: <SparkMicLine size={18} />,
      path: "/voice-transcription",
      label: t("nav.voiceTranscription"),
    },
    {
      key: "debug",
      icon: <SparkDebugLine size={18} />,
      path: "/debug",
      label: t("nav.debug", "Debug"),
    },
    {
      key: "evolution",
      icon: <ThunderboltOutlined />,
      path: "/evolution",
      label: t("nav.evolution", "Evolution"),
    },
    // P2 Enterprise Features
    {
      key: "monitoring",
      icon: <SparkBarChartLine size={18} />,
      path: "/monitoring",
      label: t("nav.monitoring", "Monitoring"),
    },
    {
      key: "sso",
      icon: <SparkWifiLine size={18} />,
      path: "/sso",
      label: t("nav.sso", "SSO"),
    },
    {
      key: "admin",
      icon: <CrownOutlined />,
      path: "/admin",
      label: t("nav.adminPanel", "后台管理"),
    },
    // Append plugin nav items dynamically
    ...pluginRoutes.map((route) => ({
      key: route.path.replace(/^\//, ""),
      icon: <span style={{ fontSize: 18 }}>{route.icon}</span>,
      path: route.path,
      label: route.label,
    })),
  ];

  // ── Menu items — agent-scoped (Chat + Control + Workspace) ──────────────

  const agentMenuItems: MenuProps["items"] = [
    {
      key: "chat",
      label: collapsed ? null : t("nav.chat"),
      icon: <SparkChatTabFill size={16} />,
    },
    {
      key: "control-group",
      label: collapsed ? null : t("nav.control"),
      children: [
        {
          key: "channels",
          label: collapsed ? null : t("nav.channels"),
          icon: <SparkWifiLine size={16} />,
        },
        {
          key: "sessions",
          label: collapsed ? null : t("nav.sessions"),
          icon: <SparkUserGroupLine size={16} />,
        },
        {
          key: "cron-jobs",
          label: collapsed ? null : t("nav.cronJobs"),
          icon: <SparkDateLine size={16} />,
        },
        {
          key: "heartbeat",
          label: collapsed ? null : t("nav.heartbeat"),
          icon: <SparkVoiceChat01Line size={16} />,
        },
      ],
    },
    {
      key: "agent-group",
      label: collapsed ? null : t("nav.agent"),
      children: [
        // "文件"菜单已移至"我的空间"Tab中
        // {
        //   key: "workspace",
        //   label: collapsed ? null : t("nav.workspace"),
        //   icon: <SparkLocalFileLine size={16} />,
        // },
        {
          key: "myspace",
          label: collapsed ? null : t("nav.myspace"),
          icon: <SparkLocalFileLine size={16} />,
        },
        {
          key: "skills",
          label: collapsed ? null : t("nav.skills"),
          icon: <SparkMagicWandLine size={16} />,
        },
        {
          key: "tools",
          label: collapsed ? null : t("nav.tools"),
          icon: <SparkToolLine size={16} />,
        },
        {
          key: "mcp",
          label: collapsed ? null : t("nav.mcp"),
          icon: <SparkMcpMcpLine size={16} />,
        },
        // ACP 模块已隐藏 — 2026-06-28
        // {
        //   key: "acp",
        //   label: collapsed ? null : t("nav.acp"),
        //   icon: <SparkScanLine size={16} />,
        // },
        {
          key: "agent-config",
          label: collapsed ? null : t("nav.agentConfig"),
          icon: <SparkModifyLine size={16} />,
        },
        {
          key: "agent-stats",
          label: collapsed ? null : t("nav.agentStats"),
          icon: <SparkBarChartLine size={16} />,
        },
      ],
    },
  ];

  // ── Menu items — global settings ──────────────────────────────────────

  const settingsMenuItems: MenuProps["items"] = [
    {
      key: "settings-group",
      label: collapsed ? null : t("nav.settings"),
      children: [
        {
          key: "agents",
          label: collapsed ? null : t("nav.agents"),
          icon: <SparkAgentLine size={16} />,
        },
        {
          key: "models",
          label: collapsed ? null : t("nav.models"),
          icon: <SparkModePlazaLine size={16} />,
        },
        // {
        //   key: "environments",
        //   label: collapsed ? null : t("nav.environments"),
        //   icon: <SparkInternetLine size={16} />,
        // },
        {
          key: "security",
          label: collapsed ? null : t("nav.security"),
          icon: <SparkBrowseLine size={16} />,
        },
        {
          key: "token-usage",
          label: collapsed ? null : t("nav.tokenUsage"),
          icon: <SparkDataLine size={16} />,
        },
        {
          key: "backups",
          label: collapsed ? null : t("nav.backups"),
          icon: <SparkSaveLine size={16} />,
        },
        {
          key: "voice-transcription",
          label: collapsed ? null : t("nav.voiceTranscription"),
          icon: <SparkMicLine size={16} />,
        },
        {
          key: "evolution",
          label: collapsed ? null : t("nav.evolution", "进化"),
          icon: <ThunderboltOutlined />,
        },
        {
          key: "admin",
          label: collapsed ? null : t("nav.adminPanel", "后台管理"),
          icon: <CrownOutlined />,
        },
      ],
    },
  ];

  // Append plugin menu items as a group (only when there are plugins)
  if (pluginRoutes.length > 0) {
    settingsMenuItems.push({
      key: "plugins-group",
      label: collapsed ? null : t("nav.plugins"),
      children: pluginRoutes.map((route) => ({
        key: route.path.replace(/^\//, ""),
        label: collapsed ? null : route.label,
        icon: <span style={{ fontSize: 16 }}>{route.icon}</span>,
      })),
    } as any);
  }

  // ── Menu items — workbench ──────────────────────────────────────

  const workbenchMenuItems: MenuProps["items"] = [
    {
      key: "category-all",
      label: collapsed ? null : "全部场景",
      icon: <SparkModePlazaLine size={16} />,
    },
    {
      key: "category-office",
      label: collapsed ? null : "办公",
      icon: <SparkLocalFileLine size={16} />,
    },
    {
      key: "category-data-analysis",
      label: collapsed ? null : "数据分析",
      icon: <SparkBarChartLine size={16} />,
    },
    {
      key: "category-document",
      label: collapsed ? null : "文档处理",
      icon: <SparkBrowseLine size={16} />,
    },
    {
      key: "category-communication",
      label: collapsed ? null : "沟通协作",
      icon: <SparkWifiLine size={16} />,
    },
    {
      type: 'divider',
    },
    {
      key: "admin",
      label: collapsed ? null : "场景管理",
      icon: <CrownOutlined />,
    },
  ];

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <Sider
      width={collapsed ? 72 : 240}
      className={`${styles.sider}${
        collapsed ? ` ${styles.siderCollapsed}` : ""
      }${isDark ? ` ${styles.siderDark}` : ""}`}
    >
      {collapsed ? (
        <nav className={styles.collapsedNav}>
          {filterMenuItems(collapsedNavItems).map((item) => {
            const isActive = selectedKey === item.key;
            return (
              <Tooltip
                key={item.key}
                title={item.label}
                placement="right"
                overlayInnerStyle={{
                  background: "rgba(0,0,0,0.75)",
                  color: "#fff",
                }}
              >
                <button
                  className={`${styles.collapsedNavItem} ${
                    isActive ? styles.collapsedNavItemActive : ""
                  }`}
                  onClick={() => navigate(item.path)}
                >
                  {item.icon}
                </button>
              </Tooltip>
            );
          })}
        </nav>
      ) : (
        <>
          {/* Agent selector at top - always show when user has at least one agent */}
          {agents.length >= 1 && (
            <div className={styles.agentSelectorWrapper}>
              <Select
                value={selectedAgent}
                onChange={(val) => {
                  setSelectedAgent(val);
                  navigate("/chat");
                }}
                size="small"
                style={{ width: "100%", marginBottom: 8 }}
                options={agents.map((a) => ({
                  value: a.id,
                  label: getAgentDisplayName(a, t),
                }))}
                placeholder={t("nav.selectAgent", "Select Agent")}
              />
            </div>
          )}

          {/* Workbench menu or Agent-scoped menu */}
          {isWorkbench ? (
            <Menu
              mode="inline"
              selectedKeys={[workbenchSelectedKey]}
              openKeys={DEFAULT_OPEN_KEYS}
              onClick={({ key }) => {
                // Handle workbench menu clicks
                if (key === 'category-all') {
                  navigate('/workbench');
                } else if (key.startsWith('category-')) {
                  // Filter scenes by category
                  const category = key.replace('category-', '');
                  navigate(`/workbench?category=${category}`);
                } else if (key === 'admin') {
                  navigate('/admin');
                }
              }}
              items={workbenchMenuItems}
              theme={isDark ? "dark" : "light"}
              className={styles.sideMenu}
            />
          ) : (
            <>
              {/* Agent-scoped section: Chat + Control + Workspace */}
              <div className={styles.agentScopedSection}>
                <Menu
                  mode="inline"
                  selectedKeys={[selectedKey]}
                  openKeys={DEFAULT_OPEN_KEYS}
                  onClick={({ key }) => {
                    const path = KEY_TO_PATH[String(key)];
                    if (path) navigate(path);
                  }}
                  items={filterMenuItems(agentMenuItems)}
                  theme={isDark ? "dark" : "light"}
                  className={styles.sideMenu}
                />
              </div>

              {/* Global settings section */}
              <Menu
                mode="inline"
                selectedKeys={[selectedKey]}
                openKeys={[
                  ...DEFAULT_OPEN_KEYS,
                  ...(pluginRoutes.length > 0 ? ["plugins-group"] : []),
                ]}
                onClick={({ key }) => {
                  const path = KEY_TO_PATH[String(key)] ?? `/${String(key)}`;
                  navigate(path);
                }}
                items={filterMenuItems(settingsMenuItems)}
                theme={isDark ? "dark" : "light"}
                className={styles.sideMenu}
              />
            </>
          )}

          <div className={styles.collapseToggleContainer}>
            <Button
              type="text"
              icon={
                collapsed ? (
                  <SparkMenuExpandLine size={20} />
                ) : (
                  <SparkMenuFoldLine size={20} />
                )
              }
              onClick={() => setCollapsed(!collapsed)}
              className={styles.collapseToggle}
            />
          </div>
        </>
      )}
    </Sider>
  );
}
