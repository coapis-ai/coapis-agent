import { useState, useEffect, useCallback } from "react";
import {
  Table,
  Tag,
  Switch,
  Card,
  Collapse,
  Spin,
} from "antd";
import { message } from "antd";
import { ShieldCheck, Bug } from "lucide-react";
import { useTranslation } from "react-i18next";
import { securityApi } from "../../../../api/modules/security";
import type { ShellRule } from "../../../../api/modules/security";
import styles from "../index.module.less";

// ── Types ──

interface AdvancedRulesTabProps {
  shellEvasionChecks: Record<string, boolean>;
  toggleShellEvasionCheck: (name: string, checked: boolean) => void;
}

const SEVERITY_COLORS: Record<string, string> = {
  CRITICAL: "red",
  HIGH: "orange",
  MEDIUM: "gold",
  LOW: "blue",
};

// ── Evasion check display names ──

const EVASION_LABELS: Record<string, { label: string; desc: string }> = {
  command_substitution: { label: "命令替换", desc: "检测 $() 和 `` 命令替换" },
  obfuscated_flags: { label: "混淆参数", desc: "检测拼接/编码的命令参数" },
  backslash_escaped_whitespace: { label: "反斜杠空白", desc: "检测反斜杠转义空白绕过" },
  backslash_escaped_operators: { label: "反斜杠运算符", desc: "检测反斜杠转义运算符" },
  newlines: { label: "换行注入", desc: "检测换行符注入绕过" },
  comment_quote_desync: { label: "注释引号脱同步", desc: "检测注释/引号状态混淆" },
  quoted_newline: { label: "引号内换行", desc: "检测引号内的换行符" },
  TOOL_CMD_OBFUSCATED_EXEC: { label: "Base64执行", desc: "base64解码后管道到bash执行" },
  TOOL_CMD_IFS_INJECTION: { label: "IFS注入", desc: "利用$IFS变量绕过空格检测" },
  TOOL_CMD_CONTROL_CHARS: { label: "控制字符", desc: "利用控制字符混淆命令" },
  TOOL_CMD_UNICODE_WHITESPACE: { label: "Unicode空白", desc: "利用Unicode空白字符绕过" },
};

// ── Component ──

export default function AdvancedRulesTab({
  shellEvasionChecks,
  toggleShellEvasionCheck,
}: AdvancedRulesTabProps) {
  const { t } = useTranslation();
  const [globalRules, setGlobalRules] = useState<ShellRule[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchGlobalRules = useCallback(async () => {
    setLoading(true);
    try {
      const data = await securityApi.getGlobalRules();
      setGlobalRules(data);
    } catch (e: any) {
      message.error(e.message || "Failed to load global rules");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchGlobalRules();
  }, [fetchGlobalRules]);

  // ── Global Rules Table Columns ──
  const ruleColumns = [
    {
      title: t("security.rules.id", "规则ID"),
      dataIndex: "id",
      key: "id",
      width: 260,
      render: (id: string) => (
        <code style={{ fontSize: 12, wordBreak: "break-all" }}>{id}</code>
      ),
    },
    {
      title: t("security.rules.severity", "严重性"),
      dataIndex: "severity",
      key: "severity",
      width: 100,
      render: (sev: string) => (
        <Tag color={SEVERITY_COLORS[sev] || "default"}>{sev}</Tag>
      ),
    },
    {
      title: t("security.rules.description", "描述"),
      dataIndex: "description",
      key: "description",
      ellipsis: true,
    },
    {
      title: t("security.rules.patterns", "匹配模式"),
      dataIndex: "patterns",
      key: "patterns",
      width: 300,
      render: (patterns: string[]) => (
        <div style={{ maxHeight: 60, overflow: "auto" }}>
          {patterns?.map((p, i) => (
            <code
              key={i}
              style={{
                display: "block",
                fontSize: 11,
                color: "#666",
                wordBreak: "break-all",
              }}
            >
              {p}
            </code>
          ))}
        </div>
      ),
    },
  ];

  // ── Split evasion checks into old (7) and new (4) ──
  const OLD_EVASION_KEYS = [
    "command_substitution",
    "obfuscated_flags",
    "backslash_escaped_whitespace",
    "backslash_escaped_operators",
    "newlines",
    "comment_quote_desync",
    "quoted_newline",
  ];
  const NEW_EVASION_KEYS = [
    "TOOL_CMD_OBFUSCATED_EXEC",
    "TOOL_CMD_IFS_INJECTION",
    "TOOL_CMD_CONTROL_CHARS",
    "TOOL_CMD_UNICODE_WHITESPACE",
  ];

  const renderEvasionItem = (key: string) => {
    const info = EVASION_LABELS[key] || { label: key, desc: "" };
    const checked = shellEvasionChecks[key] ?? false;
    return (
      <div key={key} className={styles.evasionItem}>
        <div className={styles.evasionInfo}>
          <span className={styles.evasionName}>{info.label}</span>
          <span className={styles.evasionDesc}>{info.desc}</span>
        </div>
        <Switch
          size="small"
          checked={checked}
          onChange={(val) => toggleShellEvasionCheck(key, val)}
        />
      </div>
    );
  };

  return (
    <div className={styles.tabContent}>
      {/* ── Section 1: 全局危险模式规则 ── */}
      <div className={styles.sectionContainer}>
        <div className={styles.sectionHeader}>
          <h2 className={styles.sectionTitle}>
            <ShieldCheck size={16} style={{ marginRight: 6 }} />
            {t("security.globalRules.title", "全局危险模式规则")}
            <Tag style={{ marginLeft: 8 }}>{globalRules.length}</Tag>
          </h2>
        </div>
        <Card className={styles.tableCard}>
          <Spin spinning={loading}>
            <Table
              dataSource={globalRules}
              columns={ruleColumns}
              rowKey="id"
              pagination={false}
              size="small"
            />
          </Spin>
        </Card>
      </div>

      {/* ── Section 2: 逃逸检测 ── */}
      <div className={styles.sectionContainer}>
        <div className={styles.sectionHeader}>
          <h2 className={styles.sectionTitle}>
            <Bug size={16} style={{ marginRight: 6 }} />
            {t("security.evasion.title", "逃逸检测")}
          </h2>
        </div>
        <Card className={styles.tableCard}>
          <Collapse
            defaultActiveKey={["basic", "advanced"]}
            items={[
              {
                key: "basic",
                label: t("security.evasion.basic", "基础逃逸检测（7项）"),
                children: (
                  <div className={styles.evasionList}>
                    {OLD_EVASION_KEYS.map(renderEvasionItem)}
                  </div>
                ),
              },
              {
                key: "advanced",
                label: t("security.evasion.advanced", "高级逃逸检测（4项）"),
                children: (
                  <div className={styles.evasionList}>
                    {NEW_EVASION_KEYS.map(renderEvasionItem)}
                  </div>
                ),
              },
            ]}
          />
        </Card>
      </div>
    </div>
  );
}
