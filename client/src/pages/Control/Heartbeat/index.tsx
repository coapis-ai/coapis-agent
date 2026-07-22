import { useEffect, useState } from "react";
import {
  Button,
  Card,
  Form,
  InputNumber,
  Select,
  Switch,
} from "@agentscope-ai/design";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { PermissionGuard } from "@/components/PermissionGuard";
import { TimePicker } from "antd";
import dayjs from "dayjs";
import customParseFormat from "dayjs/plugin/customParseFormat";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import { useAgentStore } from "../../../stores/agentStore";
import type { HeartbeatConfig } from "../../../api/types/heartbeat";
import { parseInterval, serializeInterval } from "./parseEvery";
import { PageHeader } from "@/components/PageHeader";
import styles from "./index.module.less";

dayjs.extend(customParseFormat);

const TIME_FORMAT = "HH:mm";

/** TimePicker that uses "HH:mm" string as value for Form. */
function TimePickerHHmm({
  value,
  onChange,
}: {
  value?: string | null;
  onChange?: (s: string) => void;
}) {
  const strVal =
    typeof value === "string" ? value : Array.isArray(value) ? value[0] : null;
  return (
    <TimePicker
      format={TIME_FORMAT}
      value={strVal ? dayjs(strVal, TIME_FORMAT) : null}
      onChange={(_, str) => {
        const s = typeof str === "string" ? str : str?.[0];
        if (s) onChange?.(s);
      }}
      minuteStep={15}
      needConfirm={false}
      style={{ width: "100%" }}
    />
  );
}

/** Form values for the heartbeat page. */
interface HeartbeatFormValues {
  enabled: boolean;
  intervalMinutes: number;
  timeoutMinutes: number;
  target: string;
  useActiveHours: boolean;
  activeHoursStart?: string;
  activeHoursEnd?: string;
}

const TARGET_OPTIONS = [
  { value: "main", labelKey: "heartbeat.targetMain" },
  { value: "last", labelKey: "heartbeat.targetLast" },
];

function HeartbeatPage() {
  const { t } = useTranslation();
  const { selectedAgent } = useAgentStore();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<HeartbeatFormValues>();
  const { message } = useAppMessage();

  const fetchConfig = async () => {
    setLoading(true);
    try {
      const data = await api.getHeartbeatConfig();
      const intervalParts = parseInterval(data.interval_seconds);
      const timeoutParts = parseInterval(data.timeout_seconds);
      form.setFieldsValue({
        enabled: data.enabled ?? false,
        intervalMinutes: intervalParts.minutes,
        timeoutMinutes: timeoutParts.minutes,
        target: data.target ?? "main",
        useActiveHours: !!data.active_hours,
        activeHoursStart: data.active_hours?.start ?? "08:00",
        activeHoursEnd: data.active_hours?.end ?? "22:00",
      });
    } catch (e) {
      console.error("Failed to load heartbeat config:", e);
      message.error(t("heartbeat.loadFailed"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchConfig();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedAgent]);

  const onFinish = async (values: HeartbeatFormValues) => {
    const body: HeartbeatConfig = {
      enabled: values.enabled ?? false,
      interval_seconds: serializeInterval(values.intervalMinutes),
      target: values.target ?? "main",
      active_hours:
        values.useActiveHours &&
        values.activeHoursStart &&
        values.activeHoursEnd
          ? {
              start: values.activeHoursStart,
              end: values.activeHoursEnd,
            }
          : null,
      timeout_seconds: serializeInterval(values.timeoutMinutes),
    };
    setSaving(true);
    try {
      await api.updateHeartbeatConfig(body);
      message.success(t("heartbeat.saveSuccess"));
    } catch (e) {
      console.error("Failed to save heartbeat config:", e);
      message.error(t("heartbeat.saveFailed"));
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className={styles.heartbeatPage}>
        <PageHeader
          items={[{ title: "设置" }, { title: t("heartbeat.title") }]}
        />
        <span className={styles.description}>{t("common.loading")}</span>
      </div>
    );
  }

  return (
    <div className={styles.heartbeatPage}>
      <PageHeader
        items={[{ title: "设置" }, { title: t("heartbeat.title") }]}
      />
      <div className={styles.heartbeatContent}>
        <Card className={styles.card}>
          <Form
            form={form}
            layout="vertical"
            onFinish={onFinish}
            initialValues={{
              enabled: false,
              intervalMinutes: 60,
              timeoutMinutes: 5,
              target: "main",
              useActiveHours: false,
              activeHoursStart: "08:00",
              activeHoursEnd: "22:00",
            }}
          >
            <Form.Item
              name="enabled"
              label={t("heartbeat.enabled")}
              valuePropName="checked"
            >
              <Switch />
            </Form.Item>

            <Form.Item
              name="intervalMinutes"
              label={t("heartbeat.every")}
              rules={[
                { required: true, message: t("heartbeat.everyRequired") },
                {
                  type: "number",
                  min: 1,
                  message: t("heartbeat.everyMin"),
                },
              ]}
            >
              <InputNumber
                min={1}
                addonAfter={t("heartbeat.unitMinutes")}
                style={{ width: "100%" }}
              />
            </Form.Item>

            <Form.Item
              name="timeoutMinutes"
              label={t("heartbeat.timeout") || "超时时间"}
              rules={[
                {
                  type: "number",
                  min: 1,
                  message: t("heartbeat.everyMin"),
                },
              ]}
            >
              <InputNumber
                min={1}
                addonAfter={t("heartbeat.unitMinutes")}
                style={{ width: "100%" }}
              />
            </Form.Item>

            <Form.Item
              name="target"
              label={t("heartbeat.target")}
              rules={[{ required: true }]}
            >
              <Select
                options={TARGET_OPTIONS.map((opt) => ({
                  value: opt.value,
                  label: t(opt.labelKey),
                }))}
              />
            </Form.Item>

            <Form.Item
              name="useActiveHours"
              label={t("heartbeat.activeHours")}
              valuePropName="checked"
            >
              <Switch />
            </Form.Item>

            <Form.Item
              noStyle
              shouldUpdate={(prev, cur) =>
                prev.useActiveHours !== cur.useActiveHours
              }
            >
              {({ getFieldValue }) =>
                getFieldValue("useActiveHours") ? (
                  <div className={styles.activeHoursRow}>
                    <Form.Item
                      name="activeHoursStart"
                      label={t("heartbeat.activeStart")}
                    >
                      <TimePickerHHmm />
                    </Form.Item>
                    <Form.Item
                      name="activeHoursEnd"
                      label={t("heartbeat.activeEnd")}
                    >
                      <TimePickerHHmm />
                    </Form.Item>
                  </div>
                ) : null
              }
            </Form.Item>

            <Form.Item className={styles.formActions}>
              <PermissionGuard module="heartbeat" action="write">
                <Button type="primary" htmlType="submit" loading={saving}>
                  {t("common.save")}
                </Button>
              </PermissionGuard>
            </Form.Item>
          </Form>
        </Card>
      </div>
    </div>
  );
}

export default HeartbeatPage;
