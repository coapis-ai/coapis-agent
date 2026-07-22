import { useMemo } from "react";
import {
  Switch,
  Empty,
  Button,
  Tooltip,
  Input,
  Tag,
  Drawer,
  Spinner,
  Popconfirm,
  Badge,
} from "@agentscope-ai/design";
import {
  SearchOutlined,
  DeleteOutlined,
  InfoCircleOutlined,
} from "@ant-design/icons";
import { useTools } from "./useTools";
import { useTranslation } from "react-i18next";
import type { ToolInfo } from "../../../api/modules/tools";
import { PageHeader } from "@/components/PageHeader";
import { usePermission } from "@/hooks/usePermission";
import styles from "./index.module.less";

/* ── Icon helpers ──────────────────────────────────────────────────────── */

const ICON_PALETTE = [
  "#f56a00", "#7265e6", "#ffbf00", "#00a2ae",
  "#87d068", "#1890ff", "#eb2f96", "#722ed1",
];

function hashStringToIndex(value: string, mod: number): number {
  let hash = 0;
  for (let i = 0; i < value.length; i++) {
    hash = (hash * 31 + value.charCodeAt(i)) | 0;
  }
  return Math.abs(hash) % mod;
}

function ToolIcon({ icon, name }: { icon: string; name: string }) {
  if (icon) {
    return <span className={styles.toolEmoji}>{icon}</span>;
  }
  const letter = name.charAt(0).toUpperCase();
  const bg = ICON_PALETTE[hashStringToIndex(name, ICON_PALETTE.length)];
  return (
    <span className={styles.toolIconFallback} style={{ backgroundColor: bg }}>
      {letter}
    </span>
  );
}

/* ── Group color map ──────────────────────────────────────────────── */

const GROUP_COLOR: Record<string, string> = {
  basic: "blue",
  web: "cyan",
  media: "purple",
  agent: "geekblue",
  data: "green",
  other: "default",
};

/* ── Tool Card ─────────────────────────────────────────────────────────── */

function ToolCard({
  tool,
  onToggle,
  onDelete,
  onOpenDetail,
  canWrite,
  t,
}: {
  tool: ToolInfo;
  onToggle: () => void;
  onDelete: () => void;
  onOpenDetail: () => void;
  canWrite: boolean;
  t: (key: string) => string;
}) {
  const isDisabled = !tool.enabled;

  return (
    <div
      className={`${styles.toolCard} ${isDisabled ? styles.toolCardDisabled : ""}`}
      onClick={onOpenDetail}
    >
      {/* Disabled overlay */}
      {isDisabled && <div className={styles.disabledOverlay} />}

      {/* Top row: icon + name + toggle */}
      <div className={styles.toolCardHeader}>
        <div className={styles.toolCardIcon}>
          <ToolIcon icon={tool.icon} name={tool.name} />
        </div>
        <div className={styles.toolCardTitleBlock}>
          <span className={styles.toolCardName}>{tool.name}</span>
          <Tag
            color={GROUP_COLOR[tool.group] || "default"}
            className={styles.toolCardCategory}
          >
            {tool.group}
          </Tag>
        </div>
        {canWrite && (
          <div className={styles.toolCardToggle} onClick={(e) => e.stopPropagation()}>
            <Switch
              size="small"
              checked={tool.enabled}
              onChange={onToggle}
            />
          </div>
        )}
      </div>

      {/* Description */}
      <p className={styles.toolCardDesc}>
        {tool.description || t("tools.noDescription")}
      </p>

      {/* Tags */}
      {tool.tags.length > 0 && (
        <div className={styles.toolCardTags}>
          {tool.tags.slice(0, 3).map((tag) => (
            <Tag key={tag} className={styles.toolCardTag}>
              {tag}
            </Tag>
          ))}
          {tool.tags.length > 3 && (
            <span className={styles.toolCardTagMore}>+{tool.tags.length - 3}</span>
          )}
        </div>
      )}

      {/* Footer actions */}
      <div className={styles.toolCardFooter}>
        <Tooltip title={t("tools.detail")}>
          <Button
            type="text"
            size="small"
            icon={<InfoCircleOutlined />}
            onClick={(e) => { e.stopPropagation(); onOpenDetail(); }}
          />
        </Tooltip>
        {!tool.builtin && canWrite && (
          <Popconfirm
            title={`确定删除自定义工具 ${tool.name}？`}
            onConfirm={(e) => { e?.stopPropagation(); onDelete(); }}
            onCancel={(e) => e?.stopPropagation()}
          >
            <Tooltip title={t("tools.delete")}>
              <Button
                type="text"
                size="small"
                danger
                icon={<DeleteOutlined />}
                onClick={(e) => e.stopPropagation()}
              />
            </Tooltip>
          </Popconfirm>
        )}
        {tool.builtin && (
          <Tag color="blue" className={styles.toolCardBuiltinBadge}>builtin</Tag>
        )}
      </div>
    </div>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────────── */

export default function ToolsPage() {
  const { t } = useTranslation();
  const {
    tools, loading,
    search, setSearch,
    selectedGroup, setSelectedGroup,
    toggleEnabled, deleteTool,
    selectedTool, drawerOpen,
    openDetail, closeDetail,
  } = useTools();

  const { hasPermission } = usePermission();
  const canWrite = hasPermission("tools:write");

  const enabledCount = useMemo(() => tools.filter((t) => t.enabled).length, [tools]);
  const disabledCount = useMemo(() => tools.filter((t) => !t.enabled).length, [tools]);

  /* ── Tools content ────────────────────────────────────────────────── */

  const renderToolsContent = () => (
    <>
      {/* Stats row */}
      <div className={styles.statsRow}>
        <span className={styles.statItem}>
          <span className={`${styles.statDot} ${styles.statDotAll}`} />
          {t("tools.total")}: {tools.length}
        </span>
        <span className={styles.statItem}>
          <span className={`${styles.statDot} ${styles.statDotEnabled}`} />
          {t("tools.enabled")}: {enabledCount}
        </span>
        <span className={styles.statItem}>
          <span className={`${styles.statDot} ${styles.statDotDisabled}`} />
          {t("tools.disabled")}: {disabledCount}
        </span>
      </div>

      {/* Category filter bar + Search */}
      <div className={styles.tagBar}>
        <span className={styles.tagBarLabel}>分类:</span>
        {(() => {
          const groupLabels: Record<string, string> = {
            basic: "🔧 基础",
            web: "🌐 网络",
            media: "🖼️ 媒体",
            agent: "🤖 智能体",
            data: "📊 数据",
            other: "📦 其他",
          };
          const groupCount: Record<string, number> = {};
          tools.forEach((t) => {
            const g = t.group || "other";
            groupCount[g] = (groupCount[g] || 0) + 1;
          });
          const total = tools.length;
          const activeGroups = ["basic", "web", "media", "agent", "data", "other"]
            .filter((g) => (groupCount[g] || 0) > 0);
          return [
            <span
              key="all"
              className={`${styles.tagItem} ${selectedGroup === null ? styles.tagItemSelected : ""}`}
              onClick={() => setSelectedGroup(null)}
            >
              📁 全部
              <span className={styles.tagCount}>{total}</span>
            </span>,
            ...activeGroups.map((g) => (
              <span
                key={g}
                className={`${styles.tagItem} ${selectedGroup === g ? styles.tagItemSelected : ""}`}
                onClick={() => setSelectedGroup(selectedGroup === g ? null : g)}
              >
                {groupLabels[g] || g}
                <span className={styles.tagCount}>{groupCount[g] || 0}</span>
              </span>
            )),
          ];
        })()}
        <Input
          className={styles.tagBarSearch}
          prefix={<SearchOutlined />}
          placeholder={t("tools.searchPlaceholder")}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          allowClear
          size="small"
        />
      </div>

      {/* Flat card grid */}
      {loading ? (
        <div className={styles.loading}><Spinner tip={t("common.loading")} /></div>
      ) : tools.length === 0 ? (
        <Empty description="没有找到匹配的工具" />
      ) : (
        <div className={styles.cardGrid}>
          {tools.map((tool) => (
            <ToolCard
              key={tool.name}
              tool={tool}
              onToggle={() => toggleEnabled(tool)}
              onDelete={() => deleteTool(tool.name)}
              onOpenDetail={() => openDetail(tool)}
              canWrite={canWrite}
              t={t}
            />
          ))}
        </div>
      )}
    </>
  );

  return (
    <div className={styles.toolsPage}>
      <PageHeader
        items={[{ title: "设置" }, { title: t("tools.title") }]}
      />

      {/* Tools content (directly rendered, no tabs) */}
      {renderToolsContent()}

      {/* Detail Drawer */}
      <Drawer
        title={selectedTool ? `${selectedTool.icon} ${selectedTool.name}` : ""}
        open={drawerOpen}
        onClose={closeDetail}
        width={480}
      >
        {selectedTool && (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div><strong>名称：</strong>{selectedTool.name}</div>
            <div><strong>描述：</strong>{selectedTool.description || "暂无描述"}</div>
            <div>
              <strong>场景：</strong>
              <Tag color="blue">{selectedTool.scene || "general"}</Tag>
            </div>
            <div>
              <strong>分组：</strong>
              <Tag color={GROUP_COLOR[selectedTool.group] || "default"}>
                {selectedTool.group}
              </Tag>
            </div>
            <div>
              <strong>标签：</strong>
              {selectedTool.tags.length > 0
                ? selectedTool.tags.map((tag) => (
                    <Tag key={tag}>{tag}</Tag>
                  ))
                : "无标签"}
            </div>
            <div>
              <strong>状态：</strong>
              <Badge
                status={selectedTool.enabled ? "success" : "default"}
                text={selectedTool.enabled ? "已启用" : "已禁用"}
              />
            </div>
            <div><strong>内置工具：</strong>{selectedTool.builtin ? "是" : "否（自定义）"}</div>
            <div><strong>异步执行：</strong>{selectedTool.async_execution ? "是" : "否"}</div>
          </div>
        )}
      </Drawer>
    </div>
  );
}
