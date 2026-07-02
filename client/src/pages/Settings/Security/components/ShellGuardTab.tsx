import { useState, useEffect, useCallback } from "react";
import {
  Table,
  Tag,
  Button,
  Tabs,
} from "@agentscope-ai/design";
import { message, Spin } from "antd";
import {
  RefreshCw,
  ShieldCheck,
  AlertTriangle,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { securityApi } from "../../../../api/modules/security";
import { ShellEvasionSection } from "./ShellEvasionSection";

// ── Types ──

interface ShellRule {
  id: string;
  tools?: string[];
  params?: string[];
  category: string;
  severity: string;
  patterns: string[];
  exclude_patterns?: string[];
  description: string;
  remediation?: string;
}

const SEVERITY_COLORS: Record<string, string> = {
  CRITICAL: "red",
  critical: "red",
  HIGH: "orange",
  high: "orange",
  MEDIUM: "gold",
  medium: "gold",
  LOW: "blue",
  low: "blue",
};

// ── Section 1: Shell Rules Table ──

function ShellRulesSection() {
  const { t } = useTranslation();
  const [rules, setRules] = useState<ShellRule[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchRules = useCallback(async () => {
    setLoading(true);
    try {
      const data = await securityApi.getShellGuardRules();
      setRules(data);
    } catch (e: any) {
      message.error(e.message || "Failed to load shell rules");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchRules(); }, [fetchRules]);

  const columns = [
    {
      title: "ID",
      dataIndex: "id",
      key: "id",
      width: 220,
      render: (id: string) => (
        <span style={{ fontFamily: "monospace", fontSize: 12 }}>{id}</span>
      ),
    },
    {
      title: t("security.inputGuard.severity"),
      dataIndex: "severity",
      key: "severity",
      width: 100,
      render: (sev: string) => (
        <Tag color={SEVERITY_COLORS[sev] || "default"}>{sev.toUpperCase()}</Tag>
      ),
    },
    {
      title: t("security.inputGuard.category"),
      dataIndex: "category",
      key: "category",
      width: 160,
      render: (cat: string) => <Tag color="blue">{cat}</Tag>,
    },
    {
      title: t("security.inputGuard.description"),
      dataIndex: "description",
      key: "description",
      ellipsis: true,
    },
    {
      title: t("security.inputGuard.patterns"),
      dataIndex: "patterns",
      key: "patterns",
      width: 100,
      render: (p: string[]) => <span style={{ fontSize: 12, opacity: 0.7 }}>{p.length} pattern(s)</span>,
    },
  ];

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
        <span style={{ fontSize: 13, opacity: 0.7 }}>
          {t("security.shellGuard.rulesDesc", { defaultValue: "来自 dangerous_shell_commands.yaml，检测已知危险 Shell 命令模式" })}
        </span>
        <Button
          size="small"
          icon={<RefreshCw size={14} />}
          onClick={fetchRules}
          loading={loading}
        >
          {t("security.inputGuard.reload")}
        </Button>
      </div>
      <Table
        dataSource={rules}
        columns={columns}
        rowKey="id"
        loading={loading}
        pagination={false}
        size="small"
        scroll={{ y: 360 }}
        expandable={{
          expandedRowRender: (record) => (
            <div style={{ padding: "4px 0", fontSize: 13 }}>
              <div style={{ marginBottom: 4 }}>
                <strong>Patterns:</strong>{" "}
                {record.patterns.map((p, i) => (
                  <code key={i} style={{ background: "#f5f5f5", padding: "1px 4px", borderRadius: 3, marginRight: 4, fontSize: 12 }}>{p}</code>
                ))}
              </div>
              {record.exclude_patterns && record.exclude_patterns.length > 0 && (
                <div style={{ marginBottom: 4 }}>
                  <strong>Exclude:</strong>{" "}
                  {record.exclude_patterns.map((p, i) => (
                    <code key={i} style={{ background: "#fff0f0", padding: "1px 4px", borderRadius: 3, marginRight: 4, fontSize: 12 }}>{p}</code>
                  ))}
                </div>
              )}
              {record.remediation && (
                <div><strong>Remediation:</strong> {record.remediation}</div>
              )}
            </div>
          ),
        }}
      />
    </div>
  );
}

// ── Section 2: Evasion Checks ──

function EvasionChecksSection() {
  const { t } = useTranslation();
  const [checks, setChecks] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(false);

  const fetchChecks = useCallback(async () => {
    setLoading(true);
    try {
      const data = await securityApi.getShellEvasionChecks();
      setChecks(data.evasion_checks || {});
    } catch (e: any) {
      message.error(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchChecks(); }, [fetchChecks]);

  const handleToggle = useCallback(async (key: string, val: boolean) => {
    const newChecks = { ...checks, [key]: val };
    setChecks(newChecks);
    try {
      await securityApi.updateShellEvasionChecks(newChecks);
    } catch (e: any) {
      message.error(e.message);
      setChecks(checks); // rollback
    }
  }, [checks]);

  if (loading) return <Spin size="small" />;

  return (
    <div>
      <p style={{ fontSize: 13, opacity: 0.7, marginBottom: 12 }}>
        {t("security.shellGuard.evasionDesc", { defaultValue: "检测混淆/逃逸手法，防止攻击者绕过命令规则。每个检测项独立开关。" })}
      </p>
      <ShellEvasionSection
        checks={checks}
        onToggle={handleToggle}
      />
    </div>
  );
}

// ── Main Tab ──

export default function ShellGuardTab() {
  const { t } = useTranslation();
  const [activeSection, setActiveSection] = useState("rules");

  return (
    <div>
      <Tabs
        activeKey={activeSection}
        onChange={setActiveSection}
        size="small"
        items={[
          {
            key: "rules",
            label: (
              <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <AlertTriangle size={14} />
                {t("security.shellGuard.dangerRules", { defaultValue: "危险命令规则" })}
              </span>
            ),
            children: <ShellRulesSection />,
          },
          {
            key: "evasion",
            label: (
              <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <ShieldCheck size={14} />
                {t("security.shellGuard.evasionDetection", { defaultValue: "逃逸检测" })}
              </span>
            ),
            children: <EvasionChecksSection />,
          },
        ]}
      />
    </div>
  );
}
