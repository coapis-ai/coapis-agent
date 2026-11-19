import React, { useCallback, useEffect, useState } from "react";
import { Card, Tag, Button, Space, Tooltip } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import api from "@/api";

/**
 * 判官健康只读卡（B3 · 收尾方案 v1 §6.1）。
 *
 * 为什么这张卡存在：判官的问题从来不是"判了几次"，而是"为什么没判"。
 * 以前管理员只能看到判断条目，看不到"槽位里是谁、它凭什么能判、沉默都
 * 为什么沉默"——于是"判官沉默 81%"这种事实只能靠人跑 SQL 发现。
 *
 * 只读。配置改动仍走决策中枢配置接口，这张卡不写任何状态。
 */

type AbstainBucket = { code: string; text: string; count: number };

type JudgeHealth = {
  days: number;
  supply: {
    slot_provider_id: string;
    slot_model: string;
    availability_key: string;
    capability_dispatch: boolean;
    probe_enabled: boolean;
    min_prompt_tokens: number;
    capable: boolean | null;
    capability_reason?: string;
    capability?: Record<string, unknown>;
  };
  abstain: AbstainBucket[];
  judged: number;
  rows: number;
  untagged: number;
  coded_ratio: number;
  error?: string;
};

const CODE_COLORS: Record<string, string> = {
  no_slot: "orange",
  slot_model_incapable: "volcano",
  breaker_open: "red",
  rate_limited: "red",
  budget_exhausted: "gold",
  rule_decided: "green",
  timeout_soft: "purple",
  timeout_hard: "purple",
  transport: "red",
  parse_fail: "magenta",
  untagged: "default",
};

export const JudgeHealthCard: React.FC = () => {
  const { t } = useTranslation();
  const [data, setData] = useState<JudgeHealth | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get("/decisions/judge-health?days=7");
      setData(res as unknown as JudgeHealth);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const supply = data?.supply;
  const capable = supply?.capable;

  return (
    <Card
      size="small"
      loading={loading && !data}
      title={t("judgeHealth.title", "决策模型健康")}
      extra={
        <Space size="small">
          <span style={{ color: "#888", fontSize: 12 }}>
            {t("judgeHealth.scope", "近 7 天台账")}
          </span>
          <Tooltip title={t("judgeHealth.refresh", "刷新")}>
            <Button
              size="small"
              type="text"
              icon={<ReloadOutlined />}
              onClick={load}
              aria-label="refresh"
            />
          </Tooltip>
        </Space>
      }
    >
      {!data ? (
        <span style={{ color: "#999" }}>
          {t("judgeHealth.unavailable", "暂不可读")}
        </span>
      ) : (
        <Space direction="vertical" size={6} style={{ width: "100%" }}>
          <Space size={4} wrap>
            <Tag>{t("judgeHealth.slot", "决策模型槽位")}</Tag>
            <span style={{ fontFamily: "monospace", fontSize: 12 }}>
              {supply?.slot_provider_id || "-"} / {supply?.slot_model || "-"}
            </span>
            {capable === true && (
              <Tag color="green">{t("judgeHealth.capable", "能力闸：胜任")}</Tag>
            )}
            {capable === false && (
              <Tag color="red">
                {t("judgeHealth.incapable", "能力闸：不胜任")}
                {supply?.capability_reason ? ` · ${supply.capability_reason}` : ""}
              </Tag>
            )}
            {capable === null && (
              <Tag>{t("judgeHealth.noSlot", "槽位为空")}</Tag>
            )}
            {supply?.capability_dispatch ? (
              <Tag color="blue">{t("judgeHealth.dispatchOn", "能力闸已生效")}</Tag>
            ) : (
              <Tag>{t("judgeHealth.dispatchOff", "能力闸只观测")}</Tag>
            )}
            {supply?.probe_enabled ? (
              <Tag color="blue">{t("judgeHealth.probeOn", "探针已开")}</Tag>
            ) : (
              <Tag>{t("judgeHealth.probeOff", "探针未开")}</Tag>
            )}
          </Space>

          <Space size={4} wrap>
            <span style={{ color: "#666", fontSize: 12 }}>
              {t("judgeHealth.rows", "事件")} {data.rows} ·{" "}
              {t("judgeHealth.judged", "判成")} {data.judged} ·{" "}
              {t("judgeHealth.codedRatio", "弃权带码率")}{" "}
              {(data.coded_ratio * 100).toFixed(0)}%
              {data.untagged > 0 ? ` · ${data.untagged}` : ""}
            </span>
          </Space>

          <div>
            {data.abstain.length === 0 ? (
              <span style={{ color: "#999", fontSize: 12 }}>
                {t("judgeHealth.noAbstain", "窗口内无弃权记录")}
              </span>
            ) : (
              data.abstain.slice(0, 8).map((b) => (
                <Tag
                  key={b.code}
                  color={CODE_COLORS[b.code] || "blue"}
                  style={{ marginBottom: 4 }}
                >
                  {b.code} · {b.count}
                </Tag>
              ))
            )}
          </div>
        </Space>
      )}
    </Card>
  );
};

export default JudgeHealthCard;
