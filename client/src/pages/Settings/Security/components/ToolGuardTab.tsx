import { useState, useEffect, useCallback, useMemo } from "react";
import {
  Table,
  Tag,
  Button,
  Select,
  Input,
  Switch,
  Card,
  Tabs,
  Tooltip,
} from "@agentscope-ai/design";
import { message } from "antd";
import {
  RefreshCw,
  ShieldCheck,
  Settings2,
  Search,
  Play,
} from "lucide-react";
import { PlusCircleOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { securityApi } from "../../../../api/modules/security";
import type { MergedRule } from "../useToolGuard";
import { RuleTable } from "./index";
import styles from "../index.module.less";

// ── Types ──

interface CommandEntry {
  level: string;
  desc: string;
  action: string;
}

const LEVEL_COLORS: Record<string, string> = {
  L0: "green",
  L1: "blue",
  L2: "gold",
  L3: "orange",
  L4: "red",
};

const LEVEL_LABELS: Record<string, string> = {
  L0: "只读 · 零风险",
  L1: "文件 · 低风险",
  L2: "执行 · 中风险",
  L3: "破坏 · 高风险",
  L4: "系统 · 极高",
};

const SEVERITY_COLORS: Record<string, string> = {
  CRITICAL: "red",
  HIGH: "orange",
  MEDIUM: "gold",
  LOW: "blue",
};

// ── Props ──

interface ToolDetectionTabProps {
  mergedRules: MergedRule[];
  toggleRule: (ruleId: string, currentlyDisabled: boolean) => void;
  onPreviewRule: (rule: MergedRule) => void;
  onEditRule: (rule: MergedRule) => void;
  onDeleteRule: (ruleId: string) => void;
  openAddRule: () => void;
}

// ── Section 1: Detection Rules (RuleTable) ──

function DetectionRuleSection({
  mergedRules,
  toggleRule,
  onPreviewRule,
  onEditRule,
  onDeleteRule,
  openAddRule,
}: ToolDetectionTabProps) {
  const { t } = useTranslation();

  return (
    <div className={styles.tabContent}>
      <div className={styles.sectionContainer}>
        <div className={styles.sectionHeader}>
          <h2 className={styles.sectionTitle}>{t("security.rules.title")}</h2>
          <Button
            type="primary"
            icon={<PlusCircleOutlined />}
            onClick={openAddRule}
            size="middle"
          >
            {t("security.rules.add")}
          </Button>
        </div>
        <Card className={styles.tableCard}>
          <RuleTable
            rules={mergedRules}
            enabled={true}
            onToggleRule={toggleRule}
            onPreviewRule={onPreviewRule}
            onEditRule={onEditRule}
            onDeleteRule={onDeleteRule}
          />
        </Card>
      </div>
    </div>
  );
}

// ── Section 2: Command Classification (L0-L4) ──

const ACTION_CONFIG: Record<string, { color: string; labelKey: string; tooltipKey: string }> = {
  allow:   { color: "green",  labelKey: "security.toolGuard.actions.allow",   tooltipKey: "security.toolGuard.actions.allowTooltip" },
  audit:   { color: "blue",   labelKey: "security.toolGuard.actions.audit",   tooltipKey: "security.toolGuard.actions.auditTooltip" },
  confirm: { color: "gold",   labelKey: "security.toolGuard.actions.confirm", tooltipKey: "security.toolGuard.actions.confirmTooltip" },
  block:   { color: "red",    labelKey: "security.toolGuard.actions.block",   tooltipKey: "security.toolGuard.actions.blockTooltip" },
};

function CommandClassificationSection() {
  const { t } = useTranslation();
  const [commands, setCommands] = useState<Record<string, CommandEntry>>({});
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [filterLevel, setFilterLevel] = useState<string | null>(null);
  const [testCmd, setTestCmd] = useState("");
  const [testResult, setTestResult] = useState<any>(null);
  const [testing, setTesting] = useState(false);
  const [savingAction, setSavingAction] = useState<string | null>(null);

  const fetchCommands = useCallback(async () => {
    setLoading(true);
    try {
      const data = await securityApi.getUnifiedCommands();
      setCommands(data);
    } catch (e: any) {
      message.error(e.message || "Failed to load commands");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchCommands();
  }, [fetchCommands]);

  const handleTest = async () => {
    if (!testCmd.trim()) return;
    setTesting(true);
    try {
      const result = await securityApi.testUnifiedCommand(testCmd.trim());
      setTestResult(result);
    } catch (e: any) {
      message.error(e.message || "Test failed");
    } finally {
      setTesting(false);
    }
  };

  const handleActionChange = async (cmdName: string, newAction: string) => {
    setSavingAction(cmdName);
    const prev = commands[cmdName]?.action;
    try {
      // Optimistic update
      setCommands((prev) => ({
        ...prev,
        [cmdName]: { ...prev[cmdName], action: newAction },
      }));
      await securityApi.updateSingleCommand(cmdName, { action: newAction });
      message.success(`${cmdName} → ${newAction}`);
    } catch (e: any) {
      // Rollback
      if (prev) {
        setCommands((prevCmds) => ({
          ...prevCmds,
          [cmdName]: { ...prevCmds[cmdName], action: prev },
        }));
      }
      message.error(e.message || t("security.toolGuard.commands.actionSaveFailed"));
    } finally {
      setSavingAction(null);
    }
  };

  // Level counts
  const levelCounts = useMemo(() => {
    const counts: Record<string, number> = { L0: 0, L1: 0, L2: 0, L3: 0, L4: 0 };
    Object.values(commands).forEach((c) => {
      if (counts[c.level] !== undefined) counts[c.level]++;
    });
    return counts;
  }, [commands]);

  const totalCount = Object.keys(commands).length;

  // Build table data with filtering
  const dataSource = useMemo(() => {
    return Object.entries(commands)
      .filter(([name, entry]) => {
        if (filterLevel && entry.level !== filterLevel) return false;
        if (search) {
          const q = search.toLowerCase();
          return (
            name.toLowerCase().includes(q) ||
            entry.desc.toLowerCase().includes(q) ||
            entry.level.toLowerCase().includes(q)
          );
        }
        return true;
      })
      .map(([name, entry]) => ({ key: name, name, ...entry }));
  }, [commands, filterLevel, search]);

  const columns = [
    {
      title: t("security.toolGuard.commands.columnCommand", "命令"),
      dataIndex: "name",
      key: "name",
      width: 140,
      sorter: (a: any, b: any) => a.name.localeCompare(b.name),
      render: (name: string) => (
        <span style={{ fontFamily: "monospace", fontWeight: 600 }}>{name}</span>
      ),
    },
    {
      title: t("security.toolGuard.commands.columnLevel", "级别"),
      dataIndex: "level",
      key: "level",
      width: 160,
      filters: ["L0", "L1", "L2", "L3", "L4"].map((l) => ({
        text: `${l} — ${LEVEL_LABELS[l]}`,
        value: l,
      })),
      onFilter: (value: any, record: any) => record.level === value,
      render: (level: string) => (
        <Tag color={LEVEL_COLORS[level] || "default"}>
          {level} — {LEVEL_LABELS[level] || level}
        </Tag>
      ),
    },
    {
      title: t("security.toolGuard.commands.columnDesc", "描述"),
      dataIndex: "desc",
      key: "desc",
      ellipsis: true,
    },
    {
      title: t("security.toolGuard.commands.columnAction", "动作"),
      dataIndex: "action",
      key: "action",
      width: 280,
      render: (action: string, record: any) => {
        return (
          <Tooltip
            title={
              <div>
                {Object.entries(ACTION_CONFIG).map(([act, c]) => (
                  <div key={act} style={{ marginBottom: 4 }}>
                    <Tag color={c.color} style={{ marginRight: 6 }}>{t(c.labelKey, act)}</Tag>
                    <span style={{ opacity: 0.85 }}>{t(c.tooltipKey)}</span>
                  </div>
                ))}
              </div>
            }
            placement="left"
            overlayStyle={{ maxWidth: 360 }}
          >
            <Select
              value={action}
              size="small"
              style={{ width: 240 }}
              popupMatchSelectWidth={false}
              loading={savingAction === record.name}
              onChange={(val: string) => handleActionChange(record.name, val)}
              options={Object.entries(ACTION_CONFIG).map(([act, c]) => ({
                value: act,
                label: (
                  <span>
                    <Tag color={c.color} style={{ marginRight: 6, fontSize: 11, padding: "0 6px" }}>
                      {t(c.labelKey, act)}
                    </Tag>
                    <span style={{ fontSize: 12, opacity: 0.7 }}>{t(c.tooltipKey)}</span>
                  </span>
                ),
              }))}
            />
          </Tooltip>
        );
      },
    },
  ];

  return (
    <div style={{ padding: "0 4px" }}>
      {/* Level filter tags */}
      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap", alignItems: "center" }}>
        <Tag
          color={filterLevel === null ? "processing" : "default"}
          style={{
            fontSize: 13,
            padding: "4px 14px",
            cursor: "pointer",
            fontWeight: filterLevel === null ? 600 : 400,
            border: filterLevel === null ? "2px solid var(--ant-color-primary)" : undefined,
          }}
          onClick={() => setFilterLevel(null)}
        >
          {t("security.toolGuard.commands.allLevels", "全部")} ({totalCount})
        </Tag>
        {["L0", "L1", "L2", "L3", "L4"].map((level) => {
          const active = filterLevel === level;
          return (
            <Tag
              key={level}
              color={active ? LEVEL_COLORS[level] : "default"}
              style={{
                fontSize: 13,
                padding: "4px 14px",
                cursor: "pointer",
                fontWeight: active ? 600 : 400,
                border: active ? `2px solid var(--ant-color-${LEVEL_COLORS[level] === "green" ? "success" : LEVEL_COLORS[level] === "red" ? "error" : "warning"})` : undefined,
              }}
              onClick={() => setFilterLevel(active ? null : level)}
            >
              {level}: {levelCounts[level]} {t("security.toolGuard.commands.commands", "个命令")}
            </Tag>
          );
        })}
      </div>

      {/* Test command */}
      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <Input
          prefix={<Search size={14} />}
          placeholder={t("security.toolGuard.commands.testPlaceholder", "输入命令测试（如 rm -rf /）")}
          value={testCmd}
          onChange={(e) => setTestCmd(e.target.value)}
          onPressEnter={handleTest}
          style={{ flex: 1 }}
        />
        <Button
          type="primary"
          icon={<Play size={14} />}
          onClick={handleTest}
          loading={testing}
        >
          {t("security.toolGuard.commands.test", "测试")}
        </Button>
      </div>

      {/* Test result */}
      {testResult && (
        <Card
          size="small"
          style={{
            marginBottom: 16,
            borderColor:
              testResult.action === "block"
                ? "#ff4d4f"
                : testResult.action === "confirm"
                  ? "#faad14"
                  : testResult.action === "audit"
                    ? "#1677ff"
                    : "#52c41a",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
            <Tag
              color={
                ACTION_CONFIG[testResult.action]?.color || "default"
              }
              style={{ fontSize: 14, padding: "2px 12px" }}
            >
              {String(t(ACTION_CONFIG[testResult.action]?.labelKey || "security.toolGuard.actions.allow", testResult.action.toUpperCase()))}
            </Tag>
            {testResult.level && (
              <Tag color={LEVEL_COLORS[testResult.level]}>{testResult.level}</Tag>
            )}
            <span style={{ opacity: 0.6, fontSize: 12 }}>
              {testResult.duration_ms.toFixed(2)}ms
            </span>
          </div>
          {testResult.reason && (
            <div style={{ fontSize: 13, marginBottom: 8 }}>{testResult.reason}</div>
          )}
          {testResult.matched_rules?.length > 0 && (
            <div>
              <span style={{ fontSize: 12, opacity: 0.7 }}>{t("security.toolGuard.commands.matchedRules", "匹配规则：")}</span>
              {testResult.matched_rules.map((r: any) => (
                <Tag key={r.id} color={SEVERITY_COLORS[r.severity] || "default"} style={{ margin: "2px 4px" }}>
                  [{r.severity}] {r.id}
                </Tag>
              ))}
            </div>
          )}
          {testResult.evasion_flags?.length > 0 && (
            <div style={{ marginTop: 4 }}>
              <span style={{ fontSize: 12, opacity: 0.7 }}>{t("security.toolGuard.commands.evasionDetection", "逃逸检测：")}</span>
              {testResult.evasion_flags.map((f: any) => (
                <Tag key={f.id} color="volcano" style={{ margin: "2px 4px" }}>
                  {f.id}
                </Tag>
              ))}
            </div>
          )}
        </Card>
      )}

      {/* Search + table */}
      <Input
        prefix={<Search size={14} />}
        placeholder={t("security.toolGuard.commands.searchPlaceholder", "搜索命令名或描述…")}
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        allowClear
        style={{ marginBottom: 12, maxWidth: 360 }}
      />
      <Card>
        <Table
          dataSource={dataSource}
          columns={columns}
          size="small"
          loading={loading}
          pagination={{ pageSize: 30, showSizeChanger: true, showTotal: (total: number) => `${total} ${t("security.toolGuard.commands.commands", "个命令")}` }}
          locale={{ emptyText: t("security.toolGuard.commands.empty", "无命令数据") }}
        />
      </Card>
    </div>
  );
}

// ── Section 3: Evasion Detection ──

function EvasionDetectionSection() {
  const [checks, setChecks] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(false);

  const fetchChecks = useCallback(async () => {
    setLoading(true);
    try {
      const data = await securityApi.getUnifiedEvasionChecks();
      setChecks(data.evasion_checks || {});
    } catch (e: any) {
      message.error(e.message || "Failed to load evasion checks");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchChecks();
  }, [fetchChecks]);

  const handleToggle = async (key: string, val: boolean) => {
    const updated = { ...checks, [key]: val };
    setChecks(updated);
    try {
      await securityApi.updateUnifiedEvasionChecks(updated);
      message.success(`${key}: ${val ? "开启" : "关闭"}`);
    } catch (e: any) {
      setChecks(checks);
      message.error(e.message || "更新失败");
    }
  };

  const CHECK_LABELS: Record<string, string> = {
    command_substitution: "命令替换 ($(), ``)",
    obfuscated_flags: "混淆标志 (ANSI-C, locale quoting)",
    backslash_escaped_whitespace: "反斜杠转义空白符",
    backslash_escaped_operators: "反斜杠转义操作符 (;|&<>)",
    newlines: "换行符/回车分割",
    comment_quote_desync: "注释-引号失同步攻击",
    quoted_newline: "引号内换行 + 注释行剥离",
  };

  return (
    <div style={{ padding: "0 4px" }}>
      <p style={{ marginBottom: 16, opacity: 0.7 }}>
        逃逸检测用于识别攻击者通过混淆/编码手法绕过规则检测的行为。
        每个检测项独立开关，修改后即时生效。
      </p>
      <Card loading={loading}>
        {Object.entries(checks).map(([key, val]) => (
          <div
            key={key}
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              padding: "10px 0",
              borderBottom: "1px solid var(--color-border-secondary, #f0f0f0)",
            }}
          >
            <div>
              <div style={{ fontWeight: 500, fontSize: 14 }}>
                {CHECK_LABELS[key] || key}
              </div>
              <div style={{ fontSize: 12, opacity: 0.5, fontFamily: "monospace" }}>
                {key}
              </div>
            </div>
            <Switch checked={val} onChange={(v) => handleToggle(key, v)} />
          </div>
        ))}
      </Card>
    </div>
  );
}

// ── Main: Unified ToolGuardTab ──

export function ToolGuardTab(props: ToolDetectionTabProps) {
  const { t } = useTranslation();

  return (
    <Tabs
      defaultActiveKey="detectionRules"
      type="card"
      items={[
        {
          key: "detectionRules",
          label: (
            <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <ShieldCheck size={14} />
              {t("security.toolGuard.tabs.detectionRules", "检测规则")}
            </span>
          ),
          children: <DetectionRuleSection {...props} />,
        },
        {
          key: "commands",
          label: (
            <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <Settings2 size={14} />
              {t("security.toolGuard.tabs.commands", "命令分级")}
            </span>
          ),
          children: <CommandClassificationSection />,
        },
        {
          key: "evasion",
          label: (
            <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <RefreshCw size={14} />
              {t("security.toolGuard.tabs.evasion", "逃逸检测")}
            </span>
          ),
          children: <EvasionDetectionSection />,
        },
      ]}
    />
  );
}
