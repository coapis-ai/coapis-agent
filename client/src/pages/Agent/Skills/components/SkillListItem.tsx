import { Button, Checkbox, Switch, Tag, Progress } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import type { SkillSpec } from "../../../../api/types";

import { getSkillVisual } from "./SkillCard";
import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";
import styles from "../index.module.less";

dayjs.extend(relativeTime);

// ─── Category & Source display helpers ───────────────────────────────────────

// Fallback for components that don't receive API categories
const FALLBACK_CATEGORY_MAP: Record<string, string> = {
  system: "⚙️ 系统",
  browser: "🌐 浏览器",
  office: "📄 办公文档",
  communication: "💬 通信",
  development: "🛠 开发工具",
  research: "🔍 调研",
};

export const SOURCE_COLOR: Record<string, string> = {
  global: "blue",
  user: "cyan",
  agent: "purple",
  builtin: "green",
  customized: "orange",
};

export function getCategoryDisplay(category: string): string {
  return FALLBACK_CATEGORY_MAP[category] || category || "未分类";
}

export function getSourceLabel(source: string, t: (k: string) => string): string {
  switch (source) {
    case "global":
      return t("skills.sourceGlobal") || "全局继承";
    case "user":
      return t("skills.sourceUser") || "用户级";
    case "agent":
      return t("skills.sourceAgent") || "智能体";
    case "builtin":
      return t("skills.builtin") || "内置";
    case "customized":
      return t("skills.custom") || "自定义";
    default:
      return source;
  }
}

// ─── Component ──────────────────────────────────────────────────────────────

interface SkillListItemProps {
  skill: SkillSpec;
  batchModeEnabled: boolean;
  isSelected: boolean;
  onSelect: () => void;
  onClick: () => void;
  onToggleEnabled: () => Promise<void>;
  onDelete: () => void;
}

export function SkillListItem({
  skill,
  batchModeEnabled,
  isSelected,
  onSelect,
  onClick,
  onToggleEnabled,
  onDelete,
}: SkillListItemProps) {
  const { t } = useTranslation();
  const source = skill.source || "customized";
  const priority = skill.priority || "core";
  const sourceColor = SOURCE_COLOR[source] || "default";
  const isOnDemand = priority === "on-demand";

  return (
    <div
      className={`${styles.skillListItem} ${
        isSelected ? styles.selectedListItem : ""
      }`}
      onClick={() => {
        if (batchModeEnabled) onSelect();
        else onClick();
      }}
    >
      {batchModeEnabled && (
        <Checkbox
          checked={isSelected}
          onClick={(e) => {
            e.stopPropagation();
            onSelect();
          }}
        />
      )}
      <div className={styles.listItemLeft}>
        <span className={styles.fileIcon}>
          {getSkillVisual(skill.name, skill.emoji)}
        </span>
        <div className={styles.listItemInfo}>
          <div className={styles.listItemHeader}>
            <span className={styles.skillTitle}>{skill.name}</span>
            <Tag color={sourceColor} style={{ fontSize: 11, lineHeight: "18px" }}>
              {getSourceLabel(source, t)}
            </Tag>
            {isOnDemand && (
              <Tag color="orange" style={{ fontSize: 11, lineHeight: "18px" }}>
                按需加载
              </Tag>
            )}
            {skill.current_version && (
              <Tag color="geekblue" style={{ fontSize: 11, lineHeight: "18px" }}>
                v{skill.current_version}
              </Tag>
            )}
            {skill.metric_score != null && skill.metric_score > 0 && (
              <Progress
                percent={Math.round(skill.metric_score * 100)}
                size="small"
                strokeColor={skill.metric_score >= 0.7 ? '#52c41a' : skill.metric_score >= 0.4 ? '#faad14' : '#ff4d4f'}
                style={{ width: 80, display: 'inline-flex', verticalAlign: 'middle', marginLeft: 8 }}
              />
            )}
            {skill.last_updated && (
              <span className={styles.listItemTime}>
                {t("skills.lastUpdated")} {dayjs(skill.last_updated).fromNow()}
              </span>
            )}
          </div>
          <p className={styles.listItemDesc}>{skill.description || "-"}</p>
          {!!skill.tags?.length && (
            <div className={styles.listItemTags}>
              {skill.tags.map((tag) => (
                <span key={tag} className={styles.tagChip}>
                  {tag}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
      <div className={styles.listItemRight}>
        <span onClick={(e) => e.stopPropagation()}>
          <Switch
            checked={skill.enabled}
            disabled={batchModeEnabled}
            onChange={onToggleEnabled}
          />
        </span>
        <Button
          danger
          disabled={batchModeEnabled}
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
        >
          {t("common.delete")}
        </Button>
      </div>
    </div>
  );
}
