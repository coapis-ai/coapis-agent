import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import {
  Alert,
  Button,
  Card,
  Space,
  Tag,
  Typography,
} from "antd";
import { Check, Clock, Copy, Shield, X } from "lucide-react";
import styles from "./ApprovalCard.module.less";

const { Text } = Typography;

export interface ApprovalCardProps {
  requestId: string;
  toolName: string;
  severity: string;
  findingsCount: number;
  findingsSummary: string;
  toolParams: Record<string, unknown>;
  createdAt: number;
  timeoutSeconds: number;
  sessionId?: string;
  rootSessionId?: string;
  /**
   * Server-authoritative countdown in seconds. Preferred over the
   * ``createdAt``/``timeoutSeconds`` arithmetic, which mixed the browser
   * clock with the server clock: a browser running a few seconds ahead made
   * every card expire the instant it mounted (``remainingMs`` went negative
   * on the first render) and the card self-destructed in ~0 ms.
   */
  remainingSeconds?: number;
  onApprove: (requestId: string) => Promise<void>;
  onDeny: (requestId: string) => Promise<void>;
  /** Fired once when the countdown reaches zero. */
  onTimeout?: (requestId: string) => void;
  onCancel?: () => void;
  /**
   * Terminal (dead) card. Rendered when the approval expired, or when the
   * backend refused to resolve it because the waiting agent had already
   * given up. Terminal cards never auto-dismiss: the user must be able to
   * see *why* nothing ran, and close it deliberately.
   */
  terminal?: { title: string; message: string };
  onClose?: () => void;
}

/** Milliseconds left before the approval dies; server clock preferred. */
function initialRemainingMs(
  remainingSeconds: number | undefined,
  timeoutSeconds: number,
  createdAt: number,
): number {
  if (typeof remainingSeconds === "number" && Number.isFinite(remainingSeconds)) {
    return Math.max(0, remainingSeconds * 1000);
  }
  // Legacy payload without a server countdown: derive it, clamped at 0.
  const elapsedMs = Date.now() - createdAt * 1000;
  return Math.max(0, timeoutSeconds * 1000 - elapsedMs);
}

export function ApprovalCard(props: ApprovalCardProps) {
  const {
    requestId,
    toolName,
    severity,
    findingsCount,
    findingsSummary,
    toolParams,
    createdAt,
    timeoutSeconds,
    sessionId,
    rootSessionId,
    remainingSeconds,
    onApprove,
    onDeny,
    onTimeout,
    onCancel,
    terminal,
    onClose,
  } = props;
  const { t } = useTranslation();
  const [copiedField, setCopiedField] = useState<string | null>(null);
  const [loading, setLoading] = useState<"approve" | "deny" | null>(null);
  const [selfExpired, setSelfExpired] = useState(
    () => initialRemainingMs(remainingSeconds, timeoutSeconds, createdAt) <= 0,
  );
  const [remainingMs, setRemainingMs] = useState(() =>
    initialRemainingMs(remainingSeconds, timeoutSeconds, createdAt),
  );
  const deadlineRef = useRef<number>(Date.now() + remainingMs);
  const timeoutFiredRef = useRef<boolean>(false);

  const isCrossSession = sessionId && rootSessionId && sessionId !== rootSessionId;

  const handleCopy = (text: string, field: string) => {
    navigator.clipboard.writeText(text);
    setCopiedField(field);
    setTimeout(() => setCopiedField(null), 2000);
  };

  const getSeverityColor = (sev: string) => {
    const colors: Record<string, string> = {
      LOW: "green",
      MEDIUM: "orange",
      HIGH: "red",
      CRITICAL: "red",
    };
    return colors[sev] || "orange";
  };

  const handleApprove = async () => {
    setLoading("approve");
    try {
      await onApprove(requestId);
    } catch (error) {
      console.error("Approve failed:", error);
    } finally {
      setLoading(null);
    }
  };

  const handleDeny = async () => {
    setLoading("deny");
    try {
      await onDeny(requestId);
    } catch (error) {
      console.error("Deny failed:", error);
    } finally {
      setLoading(null);
    }
  };

  // Countdown, anchored to the mount instant plus the server's remaining
  // time. Reaching zero flips the card into its terminal state instead of
  // unmounting it.
  useEffect(() => {
    if (terminal || selfExpired) return undefined;
    const timer = setInterval(() => {
      const left = deadlineRef.current - Date.now();
      if (left <= 0) {
        setRemainingMs(0);
        setSelfExpired(true);
        if (!timeoutFiredRef.current) {
          timeoutFiredRef.current = true;
          onTimeout?.(requestId);
        }
        return;
      }
      setRemainingMs(left);
    }, 100);
    return () => clearInterval(timer);
  }, [requestId, onTimeout, selfExpired, terminal]);

  // A card that is already dead when it mounts must say so. Previously
  // ``if (remainingMs <= 0) return null`` made the card vanish silently —
  // which is exactly what "提示要审批，但没有审批窗口" looked like.
  useEffect(() => {
    if (terminal || selfExpired) return;
    if (remainingMs > 0) return;
    if (timeoutFiredRef.current) return;
    timeoutFiredRef.current = true;
    setSelfExpired(true);
    onTimeout?.(requestId);
  }, [remainingMs, selfExpired, terminal, requestId, onTimeout]);

  const remaining = Math.max(0, Math.ceil(remainingMs / 1000));
  const isTerminal = Boolean(terminal) || selfExpired;

  // Terminal state: expired / refused by the backend. Kept on screen until
  // the user closes it.
  if (isTerminal) {
    return (
      <Card
        className={`${styles.approvalCard} ${styles.cardExpired}`}
        id={`approval-card-${requestId}`}
      >
        <div className={styles.header}>
          <Space size={8} align="center">
            <Clock size={16} className={styles.icon} />
            <Text className={styles.title}>
              {terminal?.title || t("approval.expiredTitle", "Approval expired")}
            </Text>
          </Space>
        </div>
        <div className={styles.content}>
          <div className={styles.infoRow}>
            <Text className={styles.label}>{t("approval.tool", "Tool")}:</Text>
            <Text className={styles.value} code>
              {toolName}
            </Text>
          </div>
          <Alert
            type="warning"
            showIcon
            message={
              terminal?.message ||
              t(
                "approval.expiredHint",
                "This approval timed out. The tool was not executed.",
              )
            }
            description={t(
              "approval.expiredDesc",
              "Ask the same operation again and approve the new card right away.",
            )}
          />
        </div>
        <div className={styles.actions}>
          <Button type="primary" onClick={() => onClose?.()}>
            {t("approval.close", "Close")}
          </Button>
        </div>
      </Card>
    );
  }

  return (
    <Card
      className={`${styles.approvalCard} ${
        styles[severity.toLowerCase()] || ""
      }`}
      id={`approval-card-${requestId}`}
    >
      <div className={styles.header}>
        <Space size={8} align="center">
          <Shield size={16} className={styles.icon} />
          <Text className={styles.title}>
            {t("approval.title", "Security Approval Required")}
          </Text>
        </Space>
        <Space size={6} align="center" className={styles.timer}>
          <Clock size={14} className={styles.timerIcon} />
          <Text className={styles.timerText}>
            {Math.floor(remaining / 60)}:
            {String(remaining % 60).padStart(2, "0")}
          </Text>
        </Space>
      </div>

      <div className={styles.content}>
        <div className={styles.infoRow}>
          <Text className={styles.label}>{t("approval.tool", "Tool")}:</Text>
          <Text className={styles.value} code>
            {toolName}
          </Text>
        </div>

        <div className={styles.infoRow}>
          <Text className={styles.label}>
            {t("approval.severity", "Severity")}:
          </Text>
          <Tag
            color={getSeverityColor(severity)}
            className={styles.severityTag}
          >
            {severity.toUpperCase()}
          </Tag>
        </div>

        <div className={styles.infoRow}>
          <Text className={styles.label}>
            {t("approval.findings", "Findings")}:
          </Text>
          <Text className={styles.value}>{findingsCount}</Text>
        </div>

        {isCrossSession && (
          <div className={styles.infoRow}>
            <Text className={styles.label}>
              {t("approval.source", "Source")}:
            </Text>
            <Tag color="blue" className={styles.crossSessionTag}>
              {t("approval.subSession", "Sub-Agent")} ({sessionId?.slice(0, 8)})
            </Tag>
          </div>
        )}

        {findingsSummary && (
          <div className={styles.summaryBox}>
            <div className={styles.summaryText}>
              <ReactMarkdown>{findingsSummary}</ReactMarkdown>
            </div>
            <button
              className={`${styles.copyButton} ${
                copiedField === "summary" ? styles.copied : ""
              }`}
              onClick={() => handleCopy(findingsSummary, "summary")}
              title={t("common.copy", "Copy")}
            >
              <Copy size={12} />
            </button>
          </div>
        )}

        {toolParams && Object.keys(toolParams).length > 0 && (
          <details className={styles.paramsDetails}>
            <summary className={styles.paramsSummary}>
              {t("approval.parameters", "Parameters")}
            </summary>
            <div className={styles.paramsCodeWrapper}>
              <pre className={styles.paramsCode}>
                {JSON.stringify(toolParams, null, 2)}
              </pre>
              <button
                className={`${styles.copyButton} ${
                  copiedField === "params" ? styles.copied : ""
                }`}
                onClick={() =>
                  handleCopy(JSON.stringify(toolParams, null, 2), "params")
                }
                title={t("common.copy", "Copy")}
              >
                <Copy size={12} />
              </button>
            </div>
          </details>
        )}
      </div>

      <div className={styles.actions}>
        {onCancel && (
          <Button
            type="default"
            onClick={() => {
              console.log("[ApprovalCard] Cancel task button clicked");
              onCancel();
            }}
            disabled={loading !== null}
          >
            {t("approval.cancelTask", "Cancel Task")}
          </Button>
        )}
        <Button
          danger
          icon={<X size={14} />}
          onClick={handleDeny}
          loading={loading === "deny"}
          disabled={loading !== null}
        >
          {t("approval.deny", "Deny")}
        </Button>
        <Button
          type="primary"
          icon={<Check size={14} />}
          onClick={handleApprove}
          loading={loading === "approve"}
          disabled={loading !== null}
        >
          {t("approval.approve", "Approve")}
        </Button>
      </div>
    </Card>
  );
}
