/**
 * ChatPlanBoard — 对话内的执行计划看板
 *
 * 2026-11-19 (计划执行能力优化)
 *
 * 参照 Claude Code / Codex 的取舍：工具调用细节可以折叠、可以不重要，但
 * "接下来做哪几件事、现在做到第几步、每件事的结果是什么" 必须一直看得见。
 *
 * 这块之前是断的：`PlanPanel` 与 `ChatPlanEntry` 都没有被任何页面引用，
 * 聊天里唯一的计划痕迹是 `create_plan` 的工具卡，用户根本看不出执行主线。
 * 本组件把数据通路真正接上：
 *   - GET /plan/current 取本会话**全部**计划（刷新、切会话后仍在）；
 *   - subscribePlanUpdates 接实时推进（步骤状态、结果即时更新）；
 *   - 结果缺失的步骤明确标「结果待补」，不拿绿勾糊弄用户。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  planApi,
  subscribePlanUpdates,
  type PlanStateResponse,
  type SubTaskResponse,
} from "@/api/modules/plan";
import styles from "./ChatPlanBoard.module.less";

interface ChatPlanBoardProps {
  /** 当前聊天 id；后端计划作用域以它为第一把尺子。 */
  chatId?: string;
}

type StepState = SubTaskResponse["state"];

const DONE_STATES: StepState[] = ["done", "abandoned"];

function planKey(plan: PlanStateResponse, index: number): string {
  return plan.id || `${plan.name || "plan"}-${index}`;
}

function isLive(plan: PlanStateResponse): boolean {
  if (plan.finished === false) return true;
  if (plan.state === "in_progress") return true;
  return (plan.subtasks || []).some((s) => s.state === "in_progress");
}

function countProgress(plan: PlanStateResponse): { done: number; total: number } {
  const steps = plan.subtasks || [];
  return {
    done: steps.filter((s) => DONE_STATES.indexOf(s.state) >= 0).length,
    total: steps.length,
  };
}

function readWindowSessionId(): string {
  const w = window as unknown as Record<string, unknown>;
  const direct = w.currentSessionId;
  if (typeof direct === "string" && direct) return direct;
  const alt = w.__coapis_current_session_id;
  if (typeof alt === "string" && alt) return alt;
  return "";
}

export default function ChatPlanBoard({ chatId }: ChatPlanBoardProps) {
  const { t } = useTranslation();
  const [plans, setPlans] = useState<PlanStateResponse[]>([]);
  const [openKeys, setOpenKeys] = useState<Record<string, boolean>>({});
  // 记住哪个 session key 真的取到了数据：作用域键错时计划会静默为空，
  // 这正是"面板恒 0/0"的老毛病，这里用候选键自愈而不是猜一个。
  const keyRef = useRef<string>("");
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const candidateKeys = useCallback((): string[] => {
    const out: string[] = [];
    if (keyRef.current) out.push(keyRef.current);
    if (chatId && out.indexOf(chatId) < 0) out.push(chatId);
    // 只有拿不到会话 id 时才用全局兜底：Web 控制台的所有会话共用
    // ``console:<user>`` 这个运行时键，指定会话查不到还去查它，
    // 就会把别的会话的计划显示进来。
    if (!chatId) {
      const wid = readWindowSessionId();
      if (wid && out.indexOf(wid) < 0) out.push(wid);
    }
    return out;
  }, [chatId]);

  const refresh = useCallback(async () => {
    const keys = candidateKeys();
    if (keys.length === 0) {
      setPlans([]);
      return;
    }
    for (const key of keys) {
      try {
        const res = await planApi.getCurrentPlanWithScope(key);
        const list = res.plans || [];
        if (list.length > 0) {
          keyRef.current = key;
          setPlans(list);
          return;
        }
      } catch {
        // 某个键不通就换下一个，全都不通时保留上一次的结果。
      }
    }
  }, [candidateKeys]);

  const scheduleRefresh = useCallback(() => {
    if (refreshTimer.current) clearTimeout(refreshTimer.current);
    refreshTimer.current = setTimeout(() => {
      refreshTimer.current = null;
      void refresh();
    }, 250);
  }, [refresh]);

  // 首屏 + 会话切换时拉全量。
  useEffect(() => {
    keyRef.current = "";
    setPlans([]);
    void refresh();
  }, [refresh]);

  // 实时推进：SSE 事件先乐观合并，再防抖取一次权威列表。
  useEffect(() => {
    const off = subscribePlanUpdates(
      (plan: PlanStateResponse | null) => {
        if (plan) {
          setPlans((prev) => {
            const idx = prev.findIndex((p) => p.id === plan.id);
            if (idx >= 0) {
              const next = [...prev];
              next[idx] = { ...next[idx], ...plan };
              return next;
            }
            return [...prev, plan];
          });
        }
        scheduleRefresh();
      },
      undefined,
      { sessionId: chatId || readWindowSessionId() || undefined },
    );
    return () => {
      off();
      if (refreshTimer.current) clearTimeout(refreshTimer.current);
    };
  }, [chatId, scheduleRefresh]);

  // 有步骤在跑时轮询兜底（SSE 断线也不至于停更）；全部结束就停轮询。
  useEffect(() => {
    const busy = plans.some(isLive);
    if (!busy) return undefined;
    const timer = setInterval(() => {
      void refresh();
    }, 4000);
    return () => clearInterval(timer);
  }, [plans, refresh]);

  if (plans.length === 0) return null;

  const focus = plans[plans.length - 1];
  const history = plans.slice(0, -1).reverse();
  const focusKey = planKey(focus, plans.length - 1);
  const focusOpen = openKeys[focusKey] !== false; // 主线默认展开
  const progress = countProgress(focus);
  const steps = focus.subtasks || [];

  const stateLabel = (plan: PlanStateResponse) => {
    if (!isLive(plan)) {
      return plan.state === "abandoned"
        ? t("planBoard.abandoned", "已放弃")
        : t("planBoard.completed", "已完成");
    }
    return t("planBoard.inProgress", "进行中");
  };

  return (
    <div className={styles.board} data-testid="chat-plan-board">
      <button
        type="button"
        className={styles.header}
        onClick={() =>
          setOpenKeys((prev) => ({ ...prev, [focusKey]: !focusOpen }))
        }
        aria-expanded={focusOpen}
      >
        <span className={styles.title}>
          {t("planBoard.title", "执行计划")}
        </span>
        <span className={styles.planName} title={focus.name}>
          {focus.name || t("planBoard.unnamed", "未命名计划")}
        </span>
        <span className={isLive(focus) ? styles.chipLive : styles.chipDone}>
          {stateLabel(focus)}
        </span>
        <span className={styles.progress}>
          {t("planBoard.stepProgress", "{{done}}/{{total}}", {
            done: progress.done,
            total: progress.total,
          })}
        </span>
        <span className={focusOpen ? styles.caretUp : styles.caretDown} />
      </button>

      {focusOpen && (
        <div className={styles.body}>
          <div className={styles.bar}>
            <span
              className={styles.barFill}
              style={{
                width: `${
                  progress.total
                    ? Math.round((progress.done / progress.total) * 100)
                    : 0
                }%`,
              }}
            />
          </div>
          <ul className={styles.steps}>
            {steps.map((step, idx) => (
              <StepRow key={`${planKey(focus, plans.length - 1)}-${idx}`} step={step} />
            ))}
          </ul>
        </div>
      )}

      {history.length > 0 && (
        <div className={styles.history}>
          {history.map((plan, idx) => {
            const key = planKey(plan, idx);
            const open = !!openKeys[key];
            const p = countProgress(plan);
            return (
              <div key={key} className={styles.historyItem}>
                <button
                  type="button"
                  className={styles.historyHead}
                  onClick={() =>
                    setOpenKeys((prev) => ({ ...prev, [key]: !open }))
                  }
                  aria-expanded={open}
                >
                  <span className={styles.historyCaret} />
                  <span className={styles.historyName} title={plan.name}>
                    {plan.name || t("planBoard.unnamed", "未命名计划")}
                  </span>
                  <span className={styles.historyMeta}>
                    {t("planBoard.stepProgress", "{{done}}/{{total}}", {
                      done: p.done,
                      total: p.total,
                    })}
                    {" · "}
                    {stateLabel(plan)}
                  </span>
                </button>
                {open && (
                  <ul className={styles.steps}>
                    {(plan.subtasks || []).map((step, sIdx) => (
                      <StepRow key={`${key}-${sIdx}`} step={step} />
                    ))}
                  </ul>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function StepRow({ step }: { step: SubTaskResponse }) {
  const { t } = useTranslation();
  const ended = DONE_STATES.indexOf(step.state) >= 0;
  const goal = (step.expected_outcome || "").trim();
  const result = (step.outcome || "").trim();

  const marker = (() => {
    if (step.state === "done") {
      return step.outcome_pending ? (
        <span className={styles.markerWarn}>!</span>
      ) : (
        <span className={styles.markerDone}>✓</span>
      );
    }
    if (step.state === "abandoned") {
      return <span className={styles.markerSkip}>—</span>;
    }
    if (step.state === "in_progress") {
      return <span className={styles.markerRun} />;
    }
    return <span className={styles.markerTodo} />;
  })();

  return (
    <li className={styles.step}>
      <span className={styles.markerSlot}>{marker}</span>
      <div className={styles.stepBody}>
        <div className={styles.stepName}>{step.name}</div>
        {ended && result && (
          <div className={styles.stepResult}>
            <span className={styles.stepLabel}>
              {t("planBoard.result", "结果")}
            </span>
            {result}
          </div>
        )}
        {ended && step.outcome_pending && (
          <div className={styles.stepMissing}>
            {t("planBoard.resultMissing", "结果待补")}
          </div>
        )}
        {!ended && goal && (
          <div className={styles.stepGoal}>
            <span className={styles.stepLabel}>
              {t("planBoard.goal", "目标")}
            </span>
            {goal}
          </div>
        )}
      </div>
    </li>
  );
}
