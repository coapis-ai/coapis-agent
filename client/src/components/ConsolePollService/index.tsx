import { useEffect, useRef, useState } from "react";
import { MessageCircle, X } from "lucide-react";
import { consoleApi, type PushMessage } from "../../api/modules/console";
import { getApiToken } from "../../api/config";
import { useApprovalContext } from "../../contexts/ApprovalContext";
import styles from "./index.module.less";

// ── 自适应轮询节奏（O1）─────────────────────────────────────────────
// 固定 2.5s 轮询占全站请求 91.8%，且出错时反而加速。改为按状态自调度：
//   有审批 2s / 刚收到消息 3s / 连续空转逐级退避至 15s 封顶
//   出错退避 5s→10s→20s→30s 封顶（原来是 1s，越错越快 = 自我 DDoS）
//   后台标签（document.hidden）完全停轮询，切回前台立即补一次
const BASE_POLL_MS = Number(localStorage.getItem("coapis_poll_interval_ms")) || 2500;
const APPROVAL_POLL_MS = 2000;
const MESSAGE_POLL_MS = 3000;
const NO_TOKEN_POLL_MS = 5000;
const IDLE_MAX_MS = 15000;
// 索引 = 连续空转次数；前 3 次保持基线，之后逐级退避，封顶 15s
const IDLE_STEPS = [BASE_POLL_MS, BASE_POLL_MS, BASE_POLL_MS, 5000, 9000, IDLE_MAX_MS];
const ERROR_START_MS = 5000;
const ERROR_MAX_MS = 30000;

const AUTO_DISMISS_MS = 8000;
const MAX_SEEN_IDS = 500;
const MAX_VISIBLE_BUBBLES = 4;
const MAX_NEW_PER_POLL = 2;
const TITLE_BLINK_PREFIX = "\u2022 ";

interface BubbleItem extends PushMessage {
  dismissAt: number;
}

export default function ConsolePollService() {
  const [items, setItems] = useState<BubbleItem[]>([]);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const emptyStreakRef = useRef(0);
  const errorDelayRef = useRef(0);
  const seenIdsRef = useRef<Set<string>>(new Set());
  const originalTitleRef = useRef(document.title);
  const blinkRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const { setApprovals } = useApprovalContext();

  // Cache previous approvals to avoid unnecessary state updates
  const prevApprovalsRef = useRef<string>(""); // Store sorted request_ids as string

  const dismiss = (id: string) => {
    setItems((prev) => prev.filter((i) => i.id !== id));
  };

  useEffect(() => {
    originalTitleRef.current = document.title;
  }, []);

  // ── 轮询主循环：自调度 setTimeout 链（取代固定 setInterval）──
  useEffect(() => {
    let cancelled = false;

    const schedule = (delay: number) => {
      if (cancelled) return;
      // 后台标签：彻底停轮询，由 visibilitychange 唤醒
      if (document.hidden) {
        timerRef.current = null;
        return;
      }
      timerRef.current = setTimeout(tick, delay);
    };

    function tick() {
      timerRef.current = null;
      if (cancelled || document.hidden) return;
      // Skip while unauthenticated: a token-less request yields 401, and the
      // global 401 handler would wipe a freshly stored token and redirect to
      // /login right after login (observed race on main-layout mount).
      if (!getApiToken()) {
        schedule(NO_TOKEN_POLL_MS);
        return;
      }
      // Pass current session_id for session-level isolation
      const sessionId = window.currentSessionId || "";
      consoleApi
        .getPushMessages(sessionId || undefined)
        .then((res) => {
          errorDelayRef.current = 0;

          // Update pending approvals (global, will be filtered by Chat component)
          // ✅ Optimization: Only update when approvals actually changed
          const approvals = res?.pending_approvals ?? [];
          if (approvals.length) {
            // Compare approval request IDs (sorted, joined as string)
            const nextIds = approvals
              .map((a) => a.request_id)
              .sort()
              .join(",");

            if (prevApprovalsRef.current !== nextIds) {
              // Approvals changed, update state
              console.log(
                "[ConsolePollService] Approvals changed:",
                nextIds.length,
                "items",
              );
              prevApprovalsRef.current = nextIds;
              setApprovals(approvals);
            }
            // else: approvals unchanged, skip update to prevent flickering
          }

          // Update message bubbles
          let added = 0;
          if (res?.messages?.length) {
            const seen = seenIdsRef.current;
            if (seen.size > MAX_SEEN_IDS) seen.clear();
            const newItems: BubbleItem[] = [];
            const now = Date.now();
            for (const m of res.messages) {
              if (seen.has(m.id)) continue;
              seen.add(m.id);
              newItems.push({ ...m, dismissAt: now + AUTO_DISMISS_MS });
            }
            if (newItems.length) {
              const toAdd = newItems.slice(-MAX_NEW_PER_POLL);
              added = toAdd.length;
              setItems((prev) => {
                const merged = [...prev, ...toAdd];
                return merged.slice(-MAX_VISIBLE_BUBBLES);
              });
            }
          }

          // ── 决定下一次间隔 ──
          let next: number;
          if (approvals.length > 0) {
            emptyStreakRef.current = 0;
            next = APPROVAL_POLL_MS; // 审批卡片要来得快
          } else if (added > 0) {
            emptyStreakRef.current = 0;
            next = MESSAGE_POLL_MS; // 有推送，保持灵敏
          } else {
            emptyStreakRef.current += 1;
            next =
              emptyStreakRef.current >= IDLE_STEPS.length
                ? IDLE_MAX_MS
                : IDLE_STEPS[emptyStreakRef.current];
          }
          schedule(next);
        })
        .catch(() => {
          // 后端不可用时退避（原实现 1s 一次 = 越错越快）
          const prev = errorDelayRef.current;
          errorDelayRef.current = Math.min(
            ERROR_MAX_MS,
            prev > 0 ? prev * 2 : ERROR_START_MS,
          );
          emptyStreakRef.current = 0;
          schedule(errorDelayRef.current);
        });
    }

    tick(); // 首次立即

    const resume = () => {
      if (document.visibilityState !== "visible") return;
      if (cancelled || timerRef.current) return;
      emptyStreakRef.current = 0;
      errorDelayRef.current = 0;
      tick();
    };
    document.addEventListener("visibilitychange", resume);

    return () => {
      cancelled = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = null;
      document.removeEventListener("visibilitychange", resume);
    };
  }, []);

  useEffect(() => {
    if (items.length === 0) return;
    const t = setInterval(() => {
      const now = Date.now();
      setItems((prev) => {
        const next = prev.filter((i) => i.dismissAt > now);
        return next.length === prev.length ? prev : next;
      });
    }, 500);
    return () => clearInterval(t);
  }, [items.length]);

  useEffect(() => {
    if (items.length === 0 || !document.hidden || blinkRef.current) return;
    const original = originalTitleRef.current;
    let showPrefix = true;
    blinkRef.current = setInterval(() => {
      document.title = showPrefix
        ? `${TITLE_BLINK_PREFIX}${original}`
        : original;
      showPrefix = !showPrefix;
    }, 800);
    return () => {
      if (blinkRef.current) {
        clearInterval(blinkRef.current);
        blinkRef.current = null;
      }
      document.title = original;
    };
  }, [items.length]);

  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState === "visible") {
        if (blinkRef.current) {
          clearInterval(blinkRef.current);
          blinkRef.current = null;
        }
        document.title = originalTitleRef.current;
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  if (items.length === 0) return null;

  return (
    <div className={styles.wrap} role="region" aria-label="Cron messages">
      {items.map((item) => (
        <div key={item.id} className={styles.bubble}>
          <MessageCircle size={18} className={styles.icon} aria-hidden />
          <p className={styles.text} title={item.text}>
            {item.text}
          </p>
          <button
            type="button"
            className={styles.close}
            onClick={() => dismiss(item.id)}
            aria-label="Close"
          >
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}
