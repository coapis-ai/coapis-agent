import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "antd";
import {
  ClearOutlined,
  FileTextOutlined,
  GlobalOutlined,
  DatabaseOutlined,
  ApiOutlined,
  DownOutlined,
  UpOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { chatApi, type ChatResourceItem } from "../../../api/modules/chat";
import { getApiToken, getApiUrl } from "../../../api/config";
import { toMyfilesParams } from "../workspaceLinks";

/** 折叠态跨刷新保持（默认折叠；用户展开后不该被刷新打回） */
const EXPANDED_KEY = "coapis.chat.resourceBar.expanded";

/**
 * 会话资源条（B3 · 会话级清单）。
 *
 * 权威源是资源台账（`GET /api/chats/{id}/resources`），所以**刷新页面、
 * 切换会话、会话压缩之后清单都还在** —— 答案气泡里那份是实时增量，这份是
 * 全量底账。默认折叠成一行「资源 · N」，点开成列表：标题 + 链接，文件走
 * 预览抽屉，网页新窗口。
 *
 * 位置：悬浮在聊天区底部、输入框上方（与历史浮层同层，不遮输入框）。
 */

interface Props {
  chatId: string;
  onPreview?: (target: { path: string; title?: string }) => void;
  /** 每次回答结束触发刷新（completed 事件后调用） */
  refreshSignal?: number;
}

const kindIcon = (kind: string) => {
  switch (kind) {
    case "web":
      return <GlobalOutlined style={{ flexShrink: 0, opacity: 0.6 }} />;
    case "kb":
      return <DatabaseOutlined style={{ flexShrink: 0, opacity: 0.6 }} />;
    case "mcp":
      return <ApiOutlined style={{ flexShrink: 0, opacity: 0.6 }} />;
    default:
      return <FileTextOutlined style={{ flexShrink: 0, opacity: 0.6 }} />;
  }
};

const fileDownloadUrl = (path: string) => {
  // 台账给的是工作区相对路径（files/x.md），myfiles 要的是分类内路径（x.md）
  const { category, path: rel } = toMyfilesParams(path);
  return getApiUrl(
    `/myfiles/download?path=${encodeURIComponent(rel)}&category=${encodeURIComponent(
      category,
    )}&token=${encodeURIComponent(getApiToken())}`,
  );
};

export default function CoApisChatResourceBar({
  chatId,
  onPreview,
  refreshSignal,
}: Props) {
  const { t } = useTranslation();
  const [items, setItems] = useState<ChatResourceItem[]>([]);
  const [total, setTotal] = useState(0);
  const [expanded, setExpanded] = useState(
    // 折叠态跨刷新保持（§2.4：默认折叠，用户展开后不该被刷新打回）
    () => {
      try {
        return localStorage.getItem(EXPANDED_KEY) === "1";
      } catch {
        return false;
      }
    },
  );

  const toggleExpanded = (next: boolean) => {
    setExpanded(next);
    try {
      localStorage.setItem(EXPANDED_KEY, next ? "1" : "0");
    } catch {
      /* 隐私模式 / 配额满：记住算赚到，记不住不影响功能 */
    }
  };

  const load = useCallback(async () => {
    if (!chatId) {
      setItems([]);
      setTotal(0);
      return;
    }
    try {
      const res = await chatApi.listChatResources(chatId, 200, 0);
      setItems(res?.items || []);
      setTotal(res?.total || 0);
    } catch {
      // 台账坏了就整条不显示——资源条是增强，不该制造报错
      setItems([]);
      setTotal(0);
    }
  }, [chatId]);

  useEffect(() => {
    void load();
  }, [load, refreshSignal]);

  const rows = useMemo(() => (expanded ? items : []), [items, expanded]);

  if (!chatId || items.length === 0) return null;

  return (
    <div
      style={{
        border: "1px solid var(--coapis-border, #e8e8e8)",
        borderRadius: 10,
        background: "var(--coapis-card-bg, #fff)",
        boxShadow: "0 2px 10px rgba(0,0,0,0.06)",
        padding: "6px 10px",
        fontSize: 12,
        maxWidth: 520,
        maxHeight: expanded ? "40vh" : undefined,
        overflow: expanded ? "auto" : "visible",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ opacity: 0.75 }}>
          {t("chat.resources.barTitle", "会话资源")} · {total}
        </span>
        <Button
          size="small"
          type="text"
          style={{ fontSize: 12 }}
          icon={expanded ? <UpOutlined /> : <DownOutlined />}
          onClick={() => toggleExpanded(!expanded)}
        >
          {expanded
            ? t("chat.resources.collapse", "收起")
            : t("chat.resources.expand", "展开")}
        </Button>
        <span style={{ flex: 1 }} />
        <Button
          size="small"
          type="text"
          style={{ fontSize: 12 }}
          icon={<ClearOutlined />}
          onClick={() => void load()}
        >
          {t("chat.resources.refresh", "刷新")}
        </Button>
      </div>
      {expanded && (
        <div style={{ display: "flex", flexDirection: "column", gap: 3, marginTop: 6 }}>
          {rows.map((r) => {
            const title = r.title || r.path;
            const href = r.kind === "file" ? fileDownloadUrl(r.path) : r.path;
            return (
              <div
                key={r.resource_key || `${r.kind}-${r.path}`}
                style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}
              >
                {kindIcon(r.kind)}
                <a
                  href={href}
                  target="_blank"
                  rel="noreferrer noopener"
                  title={r.path}
                  onClick={(e) => {
                    if (r.kind === "file" && onPreview) {
                      e.preventDefault();
                      onPreview({ path: r.path, title });
                    }
                  }}
                  style={{
                    flex: "1 1 auto",
                    minWidth: 0,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                    color: "inherit",
                    textDecoration: "none",
                    borderBottom: "1px dotted rgba(0,0,0,0.25)",
                  }}
                >
                  {title}
                </a>
                {r.role === "producer" && (
                  <span style={{ flexShrink: 0, opacity: 0.55, fontSize: 11 }}>
                    {t("chat.resources.produced", "产出")}
                  </span>
                )}
                {r.exists === false && (
                  <span style={{ flexShrink: 0, opacity: 0.55, fontSize: 11 }}>
                    {t("chat.resources.missing", "已删除")}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
