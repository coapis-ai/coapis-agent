import { useCallback, useEffect, useState } from "react";
import { Badge, Button, Modal, Tooltip, Typography } from "antd";
import { RocketOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { updateApi, type UpdateStatus } from "../../api/modules/update";
import {
  getSeenVersion,
  isNoticeEnabled,
  isSilenced,
  markSeenVersion,
  silenceFor,
} from "../../lib/updateNotice";

const { Text, Paragraph } = Typography;

const SILENCE_MS = 72 * 3600 * 1000;

/**
 * 版本更新通知（铃铛 + 自动弹窗）
 *
 * 后端只回答「有无最新版」（/api/updates，永不阻断）；已读/免打扰状态在
 * 浏览器本地（lib/updateNotice），开关收纳在「个人中心 → 个人设置」抽屉，
 * 不另设独立设置入口。
 *
 * 规则：
 * - 无更新 / 查询失败 / 离线 → 什么都不显示，一次弹窗都没有；
 * - 有更新且未静音且开关开启且该版本没弹过 → 自动弹一次（之后标记已读）；
 * - 铃铛常驻红点供主动回看，详情里可「72 小时免打扰」「不再自动弹窗」。
 */
export function UpdateNotice() {
  const { t } = useTranslation();
  const [data, setData] = useState<UpdateStatus | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [popupVersion, setPopupVersion] = useState<string | null>(null);

  const show = data?.status === "ok" && data.has_update && !!data.latest?.version;

  const refresh = useCallback(() => {
    // 静默降级：更新提示是锦上添花，任何失败都不打扰主流程
    updateApi
      .getLatest()
      .then((res) => setData(res))
      .catch(() => setData(null));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // 自动弹窗：每个版本只弹一次；免打扰期内与开关关闭时不弹
  useEffect(() => {
    if (!show || !data?.latest?.version) return;
    const version = data.latest.version;
    if (getSeenVersion() === version) return;
    if (!isNoticeEnabled() || isSilenced()) return;
    markSeenVersion(version);
    setPopupVersion(version);
  }, [show, data]);

  if (!show || !data?.latest) return null;

  const latest = data.latest;
  const openRelease = () => {
    if (latest.url) window.open(latest.url, "_blank", "noopener,noreferrer");
  };

  const renderBody = () => (
    <div style={{ marginTop: 4 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 8 }}>
        <span style={{ fontSize: 18, fontWeight: 600 }}>
          {t("header.updateNotice.newVersion", {
            defaultValue: "发现新版本",
          })}
        </span>
        <Text type="success" style={{ fontSize: 16 }}>
          v{latest.version}
        </Text>
        {latest.release_date && (
          <Text type="secondary" style={{ fontSize: 12 }}>
            {latest.release_date}
          </Text>
        )}
      </div>
      {latest.notes && latest.notes.length > 0 && (
        <ul style={{ margin: "0 0 8px", paddingLeft: 20 }}>
          {latest.notes.map((note: string, i: number) => (
            <li key={i}>{note}</li>
          ))}
        </ul>
      )}
      <Paragraph
        type="secondary"
        style={{ fontSize: 12, marginBottom: 0 }}
        ellipsis={{ rows: 3, expandable: true }}
      >
        {latest.title}
      </Paragraph>
    </div>
  );

  return (
    <>
      <Tooltip
        title={t("header.updateNotice.tooltip", {
          defaultValue: "版本更新：v{{version}}",
          version: latest.version,
        })}
      >
        <button
          type="button"
          onClick={() => setDetailOpen(true)}
          aria-label="版本更新"
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            width: 32,
            height: 32,
            padding: 0,
            border: "none",
            borderRadius: 6,
            background: "transparent",
            color: "#595959",
            fontSize: 16,
            cursor: "pointer",
          }}
        >
          <Badge dot offset={[2, -2]}>
            <RocketOutlined style={{ fontSize: 17 }} />
          </Badge>
        </button>
      </Tooltip>

      {/* 详情铃铛弹窗：可反复打开，含免打扰操作 */}
      <Modal
        open={detailOpen}
        title={t("header.updateNotice.detailTitle", {
          defaultValue: "版本更新详情",
        })}
        onCancel={() => setDetailOpen(false)}
        footer={
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", flexWrap: "wrap" }}>
            <Button
              onClick={() => {
                silenceFor(SILENCE_MS);
                setDetailOpen(false);
              }}
            >
              {t("header.updateNotice.silence72", {
                defaultValue: "72 小时内不提醒",
              })}
            </Button>
            <Button type="primary" onClick={openRelease}>
              {t("header.updateNotice.view", { defaultValue: "查看更新" })}
            </Button>
          </div>
        }
      >
        {renderBody()}
      </Modal>

      {/* 自动弹窗：每版本仅一次 */}
      <Modal
        open={popupVersion !== null}
        title={t("header.updateNotice.title", { defaultValue: "版本更新提示" })}
        onCancel={() => setPopupVersion(null)}
        footer={
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", flexWrap: "wrap" }}>
            <Button onClick={() => setPopupVersion(null)}>
              {t("common.close", { defaultValue: "关闭" })}
            </Button>
            <Button type="primary" onClick={openRelease}>
              {t("header.updateNotice.view", { defaultValue: "查看更新" })}
            </Button>
          </div>
        }
      >
        {renderBody()}
      </Modal>
    </>
  );
}

export default UpdateNotice;
