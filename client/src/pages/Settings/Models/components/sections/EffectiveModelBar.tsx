import React, { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, Button, Space } from "antd";
import api from "@/api";
import { useAppMessage } from "@/hooks/useAppMessage";

/**
 * 生效模型对账条（2026-11-09 小蜜蜂拍板 D2/F5）。
 *
 * 为什么需要它：聊天取模型的规则是「智能体级优先、全局默认兜底」
 * （后端 get_active_models 的 effective 分支），而模型管理页此前只露出
 * 「全局默认」这一层。于是出现过这样的实测事故：admin 工作区 agent.json 里
 * 留着 10 月的 a3/A3（端点已连接拒绝、api_key 为空、require_api_key=true），
 * 页面上把默认模型配得完好无损，聊天却一路走 a3/A3 —— 0 回复、页面全绿。
 *
 * 这个条把三层摊在同一屏：智能体级覆盖 / 全局默认 / 真正生效的那个，
 * 并给出它的端点；覆盖可一键清除（回落全局默认）。
 *
 * 2026-11-09 拍板：这里**不显示 Key 状态**。Key 是提供商层的配置细节，
 * 空 Key 由提供商兜成 "EMPTY" 交给端点裁决，聊天链路不判断 Key——页面上
 * 标一个"无 Key"只会让人以为配置有问题（内网自托管模型本来就没有 Key）。
 */

type Slot = { provider_id?: string; model?: string } | null;

type EffectiveInfo = {
  agent_id?: string | null;
  agent_model?: Slot;
  global_model?: Slot;
  effective_model?: Slot;
  effective_source?: "agent" | "global" | "none";
  provider_label?: string | null;
  base_url?: string;
  api_key_present?: boolean;
};

const fmtSlot = (s?: Slot): string =>
  s && s.model ? `${s.provider_id || "?"} / ${s.model}` : "—";

const labelStyle: React.CSSProperties = {
  fontSize: 12,
  opacity: 0.72,
  marginBottom: 2,
};
const valueStyle: React.CSSProperties = {
  fontSize: 13,
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
};

export const EffectiveModelBar: React.FC = () => {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [info, setInfo] = useState<EffectiveInfo | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = (await api.get("/models/effective")) as EffectiveInfo;
      setInfo(data);
    } catch (error) {
      console.error("Failed to load effective model:", error);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const clearOverride = async () => {
    setBusy(true);
    try {
      // 空 model = 清除智能体级覆盖（后端 set_active_model 的 agent 分支）
      await api.put("/models/active", {
        provider_id: "",
        model: "",
        scope: "agent",
        agent_id: info?.agent_id ?? undefined,
      });
      message.success(t("models.overrideCleared"));
      await load();
    } catch (error) {
      // 后端的中文校验结论必须原样给小蜜蜂看，不能压成"保存失败"
      message.error(
        error instanceof Error && error.message
          ? error.message
          : t("models.failedToSave"),
      );
    } finally {
      setBusy(false);
    }
  };

  if (!info) return null;

  const hasOverride = info.effective_source === "agent" && !!info.agent_model;
  const noModel = info.effective_source === "none" || !info.effective_model;

  return (
    <section
      style={{
        border: "1px solid rgba(0,0,0,0.10)",
        borderRadius: 10,
        padding: "12px 14px",
        marginBottom: 14,
      }}
    >
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 24,
          alignItems: "flex-start",
        }}
      >
        <div style={{ minWidth: 180 }}>
          <div style={labelStyle}>{t("models.effectiveBarAgent")}</div>
          <div style={valueStyle}>{fmtSlot(info.agent_model)}</div>
        </div>
        <div style={{ minWidth: 180 }}>
          <div style={labelStyle}>{t("models.effectiveBarGlobal")}</div>
          <div style={valueStyle}>{fmtSlot(info.global_model)}</div>
        </div>
        <div style={{ minWidth: 180 }}>
          <div style={labelStyle}>{t("models.effectiveBarEffective")}</div>
          <div style={valueStyle}>
            {fmtSlot(info.effective_model)}
            {info.effective_model
              ? `  (${info.effective_source === "agent"
                ? t("models.effectiveBarSourceAgent")
                : t("models.effectiveBarSourceGlobal")})`
              : ""}
          </div>
        </div>
        {info.effective_model && (
          <div style={{ minWidth: 200 }}>
            <div style={labelStyle}>{t("models.effectiveBarEndpoint")}</div>
            <div style={valueStyle}>
              {info.provider_label || "?"} · {info.base_url || "—"}
            </div>
          </div>
        )}
        {hasOverride && (
          <Space style={{ marginLeft: "auto" }}>
            <Button size="small" loading={busy} onClick={clearOverride}>
              {t("models.effectiveBarClear")}
            </Button>
          </Space>
        )}
      </div>

      {hasOverride && (
        <Alert
          style={{ marginTop: 10 }}
          type="info"
          showIcon
          message={t("models.effectiveBarOverrideHint")}
        />
      )}
      {noModel && (
        <Alert
          style={{ marginTop: 10 }}
          type="error"
          showIcon
          message={t("models.effectiveBarNoModelHint")}
        />
      )}
    </section>
  );
};

export default EffectiveModelBar;
