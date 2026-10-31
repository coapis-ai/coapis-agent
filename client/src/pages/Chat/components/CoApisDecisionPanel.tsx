/**
 * 判断中枢浮窗 —— 判官的台账与开关（v14 §5.2 / U 批）。
 *
 * 存在的理由：判官过去判完就沉进库里，用户在聊天里看不到"它判没判、
 * 判成什么、有没有真跑模型、花了多少钱"，于是"判官没有发生作用"变成
 * 一个无法用证据回答的问题。这个浮窗把台账摊开在本会话旁边，并把开关
 * 交到人手里（判官开关/事中建议/完成验收三项即时生效）。
 *
 * 外观与交互共用聊天区唯一浮窗骨架（FloatingWindow），与预览窗、会话
 * 资源抽屉同构：可拖移、八向缩放、铺满还原、Esc/点外关闭、几何记忆。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Alert, Button, Empty, Segmented, Switch, Table, Tag, Tooltip } from "antd";
import type { ColumnsType } from "antd/es/table";
import { Scale } from "lucide-react";
import { useTranslation } from "react-i18next";
import { decisionsApi } from "../../../api/modules/decisions";
import type {
  DecisionEventResponse,
  DecisionStatsResponse,
} from "../../../api/modules/decisions";
import FloatingWindow from "./FloatingWindow";

export type CoApisDecisionPanelProps = {
  open: boolean;
  onClose: () => void;
  /** 当前会话 id；为空时看全量台账 */
  chatId?: string;
  /** 宿主容器（聊天主内容区），与其它浮窗一致 */
  getContainer?: () => HTMLElement | null;
};

/** hit_layer → 颜色：一眼看出这一判是"真判断"还是"降级/没判断" */
const LAYER_COLORS: Record<string, string> = {
  llm: "green",
  cached: "cyan",
  rule: "blue",
  gate: "geekblue",
  budget: "purple",
  breaker: "orange",
  no_model: "volcano",
  timeout: "red",
  malformed: "red",
  error: "red",
};

const SOURCE_LABELS: Record<string, string> = {
  plan_gate: "判档",
  outcome: "难度复核",
  skill_trigger: "技能匹配",
  advisor: "事中改道",
  acceptance: "完成验收",
  cache: "缓存",
  hub: "中枢",
};

export default function CoApisDecisionPanel({
  open,
  onClose,
  chatId,
  getContainer,
}: CoApisDecisionPanelProps) {
  const { t } = useTranslation();
  const [items, setItems] = useState<DecisionEventResponse[]>([]);
  const [stats, setStats] = useState<DecisionStatsResponse | null>(null);
  const [config, setConfig] = useState<Record<string, unknown> | null>(null);
  const [judge, setJudge] = useState<{ provider_id: string; model: string }>({
    provider_id: "",
    model: "",
  });
  const [source, setSource] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [list, st, cfg] = await Promise.all([
        decisionsApi.list({ chatId: chatId || undefined, source: source || undefined, limit: 100 }),
        decisionsApi.stats(7, chatId || undefined),
        decisionsApi.getConfig(),
      ]);
      setItems(list.items || []);
      setStats(st);
      setConfig(cfg.config || null);
      setJudge(cfg.judge || { provider_id: "", model: "" });
      if (list.error || st.error) setError(list.error || st.error || "");
    } catch (e) {
      setError(String((e as Error)?.message || e));
    } finally {
      setLoading(false);
    }
  }, [chatId, source]);

  useEffect(() => {
    if (open) void refresh();
  }, [open, refresh]);

  const setFlag = useCallback(
    async (key: string, value: boolean) => {
      try {
        const res = await decisionsApi.putConfig({ [key]: value });
        setConfig(res.decision_hub || { [key]: value });
      } catch (e) {
        setError(String((e as Error)?.message || e));
      }
    },
    [],
  );

  const rate = useCallback(
    async (eventId: string, rating: number) => {
      try {
        await decisionsApi.rate(eventId, rating);
        setItems((prev) =>
          prev.map((it) =>
            it.event_id === eventId
              ? { ...it, rating: rating === it.rating ? null : rating }
              : it,
          ),
        );
      } catch (e) {
        setError(String((e as Error)?.message || e));
      }
    },
    [],
  );

  const columns = useMemo<ColumnsType<DecisionEventResponse>>(
    () => [
      {
        title: t("decision.col.time", "时间"),
        dataIndex: "ts",
        width: 96,
        render: (v: string) => (
          <span style={{ fontSize: 12 }}>{(v || "").slice(11, 19) || "-"}</span>
        ),
      },
      {
        title: t("decision.col.post", "岗位"),
        dataIndex: "source",
        width: 92,
        render: (v: string) => (
          <span style={{ fontSize: 12 }}>{SOURCE_LABELS[v] || v}</span>
        ),
      },
      {
        title: t("decision.col.judgment", "判断"),
        dataIndex: "judgment",
        render: (v: string, row) => (
          <span style={{ fontSize: 12 }}>
            <b>{v || row.action || "-"}</b>
            {row.fallback_reason ? (
              <span style={{ color: "#999", marginLeft: 6 }}>
                {row.fallback_reason}
              </span>
            ) : null}
          </span>
        ),
      },
      {
        title: t("decision.col.layer", "怎么来的"),
        dataIndex: "hit_layer",
        width: 88,
        render: (v: string) =>
          v ? <Tag color={LAYER_COLORS[v] || "default"}>{v}</Tag> : "-",
      },
      {
        title: t("decision.col.cost", "耗时/花费"),
        dataIndex: "latency_ms",
        width: 104,
        render: (v: number, row) => (
          <span style={{ fontSize: 12 }}>
            {v != null ? `${Math.round(v)}ms` : "-"}
            {row.cost ? ` · $${Number(row.cost).toFixed(4)}` : ""}
          </span>
        ),
      },
      {
        title: t("decision.col.rate", "打分"),
        dataIndex: "rating",
        width: 78,
        render: (v: number, row) => (
          <span>
            <Tooltip title={t("decision.rateGood", "判得准")}>
              <Button
                size="small"
                type={v === 1 ? "primary" : "text"}
                onClick={() => void rate(row.event_id, 1)}
              >
                ✓
              </Button>
            </Tooltip>
            <Tooltip title={t("decision.rateBad", "判得不准")}>
              <Button
                size="small"
                type={v === 0 ? "primary" : "text"}
                onClick={() => void rate(row.event_id, 0)}
              >
                ✗
              </Button>
            </Tooltip>
          </span>
        ),
      },
    ],
    [rate, t],
  );

  const switches = (
    <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
      <span style={{ fontSize: 12 }}>
        {t("decision.enabled", "判官")}{" "}
        <Switch
          size="small"
          checked={!!config?.enabled}
          onChange={(v) => void setFlag("enabled", v)}
        />
      </span>
      <span style={{ fontSize: 12 }}>
        {t("decision.advisor", "事中改道")}{" "}
        <Switch
          size="small"
          checked={!!config?.advisor_enabled}
          onChange={(v) => void setFlag("advisor_enabled", v)}
        />
      </span>
      <span style={{ fontSize: 12 }}>
        {t("decision.acceptance", "完成验收")}{" "}
        <Switch
          size="small"
          checked={!!config?.acceptance_enabled}
          onChange={(v) => void setFlag("acceptance_enabled", v)}
        />
      </span>
      <span style={{ fontSize: 12, color: "#666" }}>
        {t("decision.judgeModel", "判官模型")}：
        {judge.model
          ? `${judge.provider_id || "?"} / ${judge.model}`
          : t("decision.noJudge", "未配置（走规则）")}
      </span>
    </div>
  );

  return (
    <FloatingWindow
      open={open}
      onClose={onClose}
      storageKey="decisions"
      getContainer={getContainer}
      label={t("decision.title", "判断中枢")}
      closeTip={t("decision.close", "关闭判断面板")}
      defaultWidth={760}
      defaultHeight={520}
      title={
        <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Scale size={15} />
          <span style={{ fontSize: 13, fontWeight: 600 }}>
            {t("decision.title", "判断中枢")}
          </span>
        </span>
      }
      extra={
        <Button size="small" onClick={() => void refresh()} loading={loading}>
          {t("decision.refresh", "刷新")}
        </Button>
      }
      footer={switches}
    >
      <div style={{ padding: 10, display: "flex", flexDirection: "column", gap: 8 }}>
        {error ? (
          <Alert type="warning" showIcon message={error} closable />
        ) : null}
        <Segmented
          size="small"
          value={source}
          onChange={(v) => setSource(String(v))}
          options={[
            { label: t("decision.all", "全部"), value: "" },
            { label: SOURCE_LABELS.plan_gate, value: "plan_gate" },
            { label: SOURCE_LABELS.outcome, value: "outcome" },
            { label: SOURCE_LABELS.skill_trigger, value: "skill_trigger" },
            { label: SOURCE_LABELS.advisor, value: "advisor" },
            { label: SOURCE_LABELS.acceptance, value: "acceptance" },
          ]}
        />
        {stats && stats.total > 0 ? (
          <div style={{ fontSize: 12, color: "#555" }}>
            {t("decision.stats", "近 7 天")}：
            {stats.by_source
              .map(
                (s) =>
                  `${SOURCE_LABELS[s.source] || s.source} ${s.n}（真判 ${s.llm}` +
                  `，降级 ${s.degraded}，均 ${Math.round(Number(s.avg_ms) || 0)}ms）`,
              )
              .join(" ｜ ")}
            {stats.cost ? ` ｜ $${Number(stats.cost).toFixed(4)}` : ""}
          </div>
        ) : null}
        {items.length === 0 && !loading ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={t("decision.empty", "还没有判断记录")}
          />
        ) : (
          <Table
            size="small"
            rowKey={(r) => r.event_id}
            loading={loading}
            columns={columns}
            dataSource={items}
            pagination={false}
            scroll={{ y: "calc(100% - 60px)" }}
          />
        )}
      </div>
    </FloatingWindow>
  );
}
