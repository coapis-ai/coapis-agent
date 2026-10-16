import {
  Layout,
  Menu,
  Button,
  Tooltip,
  Select,
} from "antd";
import { useState, useEffect, useMemo } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  SparkMenuExpandLine,
  SparkMenuFoldLine,
} from "@agentscope-ai/icons";
import { AppstoreAddOutlined } from "@ant-design/icons";
import { agentsApi } from "../api/modules/agents";
import { permissionsApi } from "../api/modules/permissions";
import { usePlugins } from "../plugins/PluginContext";
import { useAgentStore } from "../stores/agentStore";
import { useUser } from "../contexts/UserContext";
import styles from "./index.module.less";
import { useTheme } from "../contexts/ThemeContext";
import { KEY_TO_PATH } from "./constants";
// import { DEFAULT_OPEN_KEYS } from "./constants";  // unused — 2026-07-21
import { getAgentDisplayName, isDefaultAgent } from "../utils/agentDisplayName";
import { isMenuKeyAllowed } from "../config/permissionMapping";
import { useMenuItems, FALLBACK_MENU_ITEMS } from "../config/menuConfig";

// ── Layout ────────────────────────────────────────────────────────────────

const { Sider } = Layout;

// ── Types ─────────────────────────────────────────────────────────────────

interface SidebarProps {
  selectedKey: string;
}

/** 插件分组的菜单 key（受控 openKeys / 高亮计算共用） */
const PLUGINS_GROUP_KEY = "plugins-group";

// ── Sidebar ───────────────────────────────────────────────────────────────

export default function Sidebar({ selectedKey }: SidebarProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const currentPath = location.pathname;
  const { t } = useTranslation();
  const { isDark } = useTheme();
  const { selectedAgent, agents, setSelectedAgent, setAgents } = useAgentStore();
  const { pluginRoutes } = usePlugins();
  const { user } = useUser();
  const [collapsed, setCollapsed] = useState(false);
  
  // 受控的菜单展开状态（避免 items 引用变化时丢失展开/收缩状态）
  const [openKeys, setOpenKeys] = useState<string[]>(["settings-group"]);
  
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
        // Check if current selection is valid (match by id or agent_id)
        const currentValid = sorted.some(
          (a) => a.id === current || a.agent_id === current
        );
        if (!currentValid) {
          const defaultAgent = sorted.find((a) => isDefaultAgent(a.id));
          if (defaultAgent) {
            // Use agent_id (ASCII-safe) if available, fallback to id
            setSelectedAgent(defaultAgent.agent_id || defaultAgent.id);
          } else if (sorted.length > 0) {
            const first = sorted[0];
            setSelectedAgent(first.agent_id || first.id);
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
   * Uses unified permission mapping.
   */
  /**
   * Check if a module is allowed for current user.
   * 判定逻辑统一在 permissionMapping.isMenuKeyAllowed（与设置页共用），
   * 侧栏不再用菜单 key 兜底 —— 兜底曾把映射名错的问题掩盖掉。
   */
  const isModuleAllowed = (menuKey: string): boolean =>
    isMenuKeyAllowed(menuKey, allowedModules, permissionsLoaded);
  
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

  // ── 一级菜单（按设计方案v4，社区版5项）──────────────────────────────────
  // 首页、工作场景、我的空间、设置
  // 对话功能改用浮动聊天图标（不占菜单）
  
  // Load menu items from API (/menus endpoint)
  const { menuItems: dynamicMenuItems } = useMenuItems();
  
  // 使用统一的菜单配置，并动态添加工作场景二级菜单
  // useMemo 避免每次 render 创建新数组导致 Menu 重置内部状态
  const collapsedNavItems = useMemo(() => {
    const menuSource = dynamicMenuItems.length > 0 ? dynamicMenuItems : FALLBACK_MENU_ITEMS;
    
    const items: any[] = menuSource.map(item => {
      const menuItem: any = {
        key: item.key,
        icon: item.icon,
        path: item.path,
        label: item.label,
      };

      // 子菜单直接使用 API 返回的 children
      if (item.children && item.children.length > 0) {
        menuItem.children = item.children.map((child: any) => ({
          key: child.key,
          icon: child.icon ? <span>{child.icon}</span> : undefined,
          path: child.path,
          label: child.label,
        }));
      }

      return menuItem;
    });

    // ── 插件分组 ──────────────────────────────────────────────────────────
    // 插件通过 window.CoApis.registerRoutes 注册的路由，路由本身在 MainLayout
    // 已挂上（可直接访问 URL），这里补的是侧栏入口。旧实现把插件项 push 进
    // settingsMenuItems —— 那个数组从未被 render，所以插件页一直进不了菜单。
    // 权限：插件 key 没有对应的权限模块登记，统一判定函数会放行它，
    // 与 MainLayout 插件路由不做权限门控的现状保持一致。
    if (pluginRoutes.length > 0) {
      const seen = new Set<string>();
      const children = [...pluginRoutes]
        .sort((a, b) => (a.priority ?? 0) - (b.priority ?? 0))
        .filter((r) => {
          if (seen.has(r.path)) return false;
          seen.add(r.path);
          return true;
        })
        .map((r) => ({
          key: r.path.replace(/^\//, ""),
          label: r.label,
          icon: r.icon ? (
            <span style={{ fontSize: 16 }}>{r.icon}</span>
          ) : undefined,
          path: r.path,
        }));

      if (children.length > 0) {
        items.push({
          key: PLUGINS_GROUP_KEY,
          label: t("nav.plugins", "插件"),
          icon: <AppstoreAddOutlined />,
          // 折叠态点分组图标时进第一个插件页（分组自身无落地页）
          path: children[0].path,
          children,
        });
      }
    }

    return items;
  }, [t, dynamicMenuItems, pluginRoutes]);

  // 根据当前路径和菜单配置计算真正高亮的 key
  // 叶子菜单（含子菜单中的子项）优先匹配自身 key；
  // 如果命中的是某个父菜单下的子项，折叠导航栏高亮该父菜单。
  const { activeMenuKey, activeTopKey } = useMemo(() => {
    for (const item of collapsedNavItems) {
      if (item.path === currentPath) {
        return { activeMenuKey: item.key, activeTopKey: item.key };
      }
      if (item.children) {
        for (const child of item.children) {
          if (child.path === currentPath) {
            return { activeMenuKey: child.key, activeTopKey: item.key };
          }
        }
      }
    }
    return { activeMenuKey: selectedKey, activeTopKey: selectedKey };
  }, [collapsedNavItems, currentPath, selectedKey]);

  // 当前页属于插件时展开插件分组（openKeys 是受控的，默认只展开设置组）
  useEffect(() => {
    if (pluginRoutes.length === 0) return;
    const onPluginPage = pluginRoutes.some(
      (r) => currentPath === r.path || currentPath.startsWith(`${r.path}/`),
    );
    if (!onPluginPage) return;
    setOpenKeys((prev) =>
      prev.includes(PLUGINS_GROUP_KEY) ? prev : [...prev, PLUGINS_GROUP_KEY],
    );
  }, [currentPath, pluginRoutes]);

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
            const isActive = activeTopKey === item.key;
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

          {/* 统一的5个一级菜单（首页、办公、我的场景、我的空间、设置） */}
          <Menu
            mode="inline"
            selectedKeys={[activeMenuKey]}
            openKeys={openKeys}
            onOpenChange={(keys) => setOpenKeys(keys as string[])}
            onClick={({ key }) => {
              // 查找点击的菜单项
              let targetPath: string | undefined;
              let hasChildren = false;
              
              for (const item of collapsedNavItems) {
                if (item.key === key) {
                  // 父级菜单（有 children）：不导航，只让 Menu 处理展开/收缩
                  if (item.children) {
                    hasChildren = true;
                    break;
                  }
                  targetPath = item.path;
                  break;
                }
                // 二级菜单（叶子节点）：导航
                if (item.children) {
                  const child = item.children.find((child: any) => child.key === key);
                  if (child) {
                    targetPath = child.path;
                    break;
                  }
                }
              }
              
              // 只有叶子节点才导航
              if (!hasChildren && targetPath) {
                navigate(targetPath);
              } else if (!hasChildren) {
                // 回退：使用 KEY_TO_PATH 映射或默认路径
                const path = KEY_TO_PATH[String(key)] ?? `/${String(key)}`;
                navigate(path);
              }
            }}
            items={filterMenuItems(collapsedNavItems)}
            theme={isDark ? "dark" : "light"}
            className={styles.sideMenu}
          />

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
