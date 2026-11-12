import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button, Popover, Progress, Tooltip } from "antd";
import { useTranslation } from "react-i18next";
import {
  planApi,
  subscribePlanUpdates,
  type PlanStateResponse,
} from "../../../api/modules/plan";
import { useAgentStore } from "../../../stores/agentStore";
// 复用计划面板的样式表（只读引用，不改 PlanPanel），保证顶栏展开的计划与
// 面板视觉一致，避免两套排版各自漂移。
import planStyles from "../../../components/PlanPanel/index.module.less";
// 复用顶栏按钮样式，保证与「历史 / 新聊天」按钮同一个视觉语言。
import headerStyles from "./ChatSessionHeader/index.module.less";

/**
 * ChatPlanEntry —— 聊天顶栏的「任务计划」入口（自包含）
 *
 * 为什么自包含：本组件挂在 ChatSessionHeader 里，而 ChatSessionHeader 位于
 * @agentscope-ai/chat 的 SessionsContext.Provider 之外（读不到
 * useChatAnywhereSessionsState），所以会话 id 只能取 sessionApi 同步的
 * `window.currentSessionId`（后端真实 session_id），与 PlanPanel 同一口径。
 *
 * 三件事：
 *  1. 挂载时 GET /plan/config 判断当前智能体是否开启计划功能；未开启 → 返回
 *     null，顶栏不占位，也不会建立任何 SSE 连接。
 *  2. 开启后订阅 GET /plan/stream（SSE）拿计划增量更新，卸载/切换智能体时
 *     取消订阅；订阅异常只 console.warn，绝不让聊天页崩溃。
 *  3. 头部按钮显示徽标：无计划=灰色「计划」；进行中=蓝色「第 i/n 步」；
 *     完成=绿色「✓ n/n」；点击用 Popover（右下锚定，宽 420）展开计划详情。
 *
 * 注意（真值校正）：components/PlanPanel 的 Props 是 `{ open, onClose }`，
 * 它自带 GET + SSE + 轮询、渲染在 antd Drawer 里，不能被 Popover 内嵌。
 * 因此这里的浮层内容由本组件渲染（复用 PlanPanel 的 CSS Module 类名），
 * 计划数据的渲染逻辑若要与 PlanPanel 合并，需要给 PlanPanel 增加
 * 「受控/内嵌」模式，属后续重构，本组件不改动它。
 */

type Lang = "zh" | "en" | "ja" | "ru";

type PlanState = PlanStateResponse["state"];

interface EntryDict {
  /** 顶栏按钮文字（无计划时） */
  entry: string;
  /** 顶栏按钮 tooltip */
  tooltip: string;
  /** 徽标：第 i/n 步 */
  step: (i: number, n: number) => string;
  /** 已完成 tooltip */
  doneTip: string;
  /** 已放弃 tooltip */
  abandonedTip: string;
  /** 浮层标题 */
  title: string;
  /** 空态主提示 */
  emptyTitle: string;
  /** 空态副提示 */
  emptyHint: string;
  /** 进度标签 */
  progress: string;
  /** 最终结果标签 */
  outcome: string;
  /** 计划状态标签 */
  state: Record<PlanState, string>;
}

const DICT: Record<Lang, EntryDict> = {
  zh: {
    entry: "计划",
    tooltip: "查看当前会话的任务计划",
    step: (i, n) => `第 ${i}/${n} 步`,
    doneTip: "计划已完成",
    abandonedTip: "计划已放弃",
    title: "任务计划",
    emptyTitle: "还没有任务计划。",
    emptyHint: "复杂任务可先让 AI 拆解步骤。",
    progress: "进度",
    outcome: "结果",
    state: { todo: "待办", in_progress: "进行中", done: "已完成", abandoned: "已放弃" },
  },
  en: {
    entry: "Plan",
    tooltip: "Show the task plan of this conversation",
    step: (i, n) => `Step ${i}/${n}`,
    doneTip: "Plan completed",
    abandonedTip: "Plan abandoned",
    title: "Task plan",
    emptyTitle: "No task plan yet.",
    emptyHint: "For a complex task, ask the AI to break it into steps first.",
    progress: "Progress",
    outcome: "Outcome",
    state: { todo: "To do", in_progress: "In progress", done: "Done", abandoned: "Abandoned" },
  },
  ja: {
    entry: "計画",
    tooltip: "この会話のタスク計画を表示",
    step: (i, n) => `ステップ ${i}/${n}`,
    doneTip: "計画は完了しました",
    abandonedTip: "計画は中止されました",
    title: "タスク計画",
    emptyTitle: "タスク計画はまだありません。",
    emptyHint: "複雑なタスクは、まず AI に手順を分解させましょう。",
    progress: "進捗",
    outcome: "結果",
    state: { todo: "未着手", in_progress: "進行中", done: "完了", abandoned: "中止" },
  },
  ru: {
    entry: "План",
    tooltip: "Показать план задач этого диалога",
    step: (i, n) => `Шаг ${i}/${n}`,
    doneTip: "План выполнен",
    abandonedTip: "План отменён",
    title: "План задач",
    emptyTitle: "План задач пока нет.",
    emptyHint: "Сложную задачу сначала попросите ИИ разбить на шаги.",
    progress: "Прогресс",
    outcome: "Результат",
    state: {
      todo: "Не начато",
      in_progress: "В работе",
      done: "Готово",
      abandoned: "Отменён",
    },
  },
};

const STATE_ICONS: Record<string, string> = {
  done: "✅",
  in_progress: "🔄",
  abandoned: "⛔",
  todo: "⬜",
};

const STATE_CLASS: Record<string, string> = {
  todo: planStyles.stateTodo,
  in_progress: planStyles.stateInProgress,
  done: planStyles.stateDone,
  abandoned: planStyles.stateAbandoned,
};

/**
 * 后端真实 session_id（ChatSpec 的 UUID 与库内 currentSessionId 不同源，
 * 计划接口认的是 sessionApi 同步到 window 的这一个）。
 */
function getBackendSessionId(): string {
  return window.currentSessionId || "";
}

/** 计划入口图标：与顶栏其他图标按钮同为 1em 线性图标（继承 currentColor）。 */
const PlanIcon = () => (
  <svg
    width="1em"
    height="1em"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d="M9 11l3 3L22 4" />
    <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
  </svg>
);

const ChatPlanEntry: React.FC = () => {
  const { i18n } = useTranslation();
  const { selectedAgent } = useAgentStore();
  const agentId = selectedAgent || undefined;

  const [enabled, setEnabled] = useState(false);
  const [plan, setPlan] = useState<PlanStateResponse | null>(null);
  const [open, setOpen] = useState(false);
  // 订阅回调在闭包里运行，读不到最新 state，故会话判定一律实时读 window。
  const sidRef = useRef<string>(getBackendSessionId());
  const unsubRef = useRef<(() => void) | null>(null);

  const lang: Lang = useMemo(() => {
    // 与仓库既有惯例一致（layouts/Header.tsx、MobileNavMenu.tsx）：优先
    // resolvedLanguage，i18next 检测出的 "zh-CN"/"en-US" 都落到前缀判断上。
    const l = (i18n.resolvedLanguage || i18n.language || "en").toLowerCase();
    if (l.startsWith("zh")) return "zh";
    if (l.startsWith("ja")) return "ja";
    if (l.startsWith("ru")) return "ru";
    return "en";
  }, [i18n.language, i18n.resolvedLanguage]);
  const L = DICT[lang];

  const fetchPlan = useCallback(async () => {
    const sid = getBackendSessionId();
    // 新会话还没拿到 session_id 时不要请求：GET /plan/current 不带 session_id
    // 时后端会返回该智能体「任意」缓存计划，徽标会凭空亮起来。
    if (!sid) {
      setPlan(null);
      return;
    }
    try {
      const data = await planApi.getCurrentPlan(sid || undefined, agentId);
      // 切会话期间的迟到响应直接丢弃，否则徽标会串会话。
      if (getBackendSessionId() !== sid) return;
      setPlan(data ?? null);
    } catch (err) {
      // 计划是锦上添花，读不到就安静地不显示，不能影响聊天。
      console.warn("[ChatPlanEntry] 读取任务计划失败（忽略）:", err);
    }
  }, [agentId]);

  // 1) 是否启用：跟随当前智能体的计划开关（与 Chat 页 /plan 命令同源判断）
  useEffect(() => {
    let cancelled = false;
    setEnabled(false);
    setPlan(null);
    planApi
      .getPlanConfig(agentId)
      .then((cfg) => {
        if (!cancelled) setEnabled(!!cfg?.enabled);
      })
      .catch((err) => {
        if (!cancelled) console.warn("[ChatPlanEntry] 读取计划配置失败（视为未启用）:", err);
      });
    return () => {
      cancelled = true;
    };
  }, [agentId]);

  // 2) SSE 订阅：只在启用后建立，卸载/切智能体时取消。
  //    注意：不在订阅参数里传 sessionId —— 它在订阅那一刻就固化了，切会话后
  //    会把新会话的事件全过滤掉；会话过滤放在回调里实时读 window。
  useEffect(() => {
    if (!enabled) return;
    const unsub = subscribePlanUpdates(
      (updatedPlan: PlanStateResponse | null, eventSessionId?: string) => {
        const mySid = getBackendSessionId();
        // 服务端 /plan/stream 按 agent 广播（同一智能体下所有会话共用一条流），
        // 会话归属必须在前端自己判：
        //  - 我有会话 id：只收同一会话的事件；
        //  - 我还没有会话 id（新会话页）：任何带会话 id 的事件都不属于我。
        if (mySid) {
          if (eventSessionId && eventSessionId !== mySid) return;
        } else if (eventSessionId) {
          return;
        }
        setPlan(updatedPlan ?? null);
      },
      (err: unknown) => {
        console.warn("[ChatPlanEntry] 计划订阅异常（不影响聊天）:", err);
      },
      { agentId },
    );
    unsubRef.current = unsub;
    return () => {
      unsub();
      unsubRef.current = null;
    };
  }, [enabled, agentId]);

  // 3) 首次拉取 + 会话切换检测（纯本地比较，不消耗请求）+ 回到前台补一次
  useEffect(() => {
    if (!enabled) return;
    sidRef.current = getBackendSessionId();
    fetchPlan();

    const tick = window.setInterval(() => {
      const sid = getBackendSessionId();
      if (sid === sidRef.current) return;
      sidRef.current = sid;
      setPlan(null); // 先清掉上一个会话的计划，避免徽标串会话
      fetchPlan();
    }, 3000);

    const onVisible = () => {
      if (document.visibilityState === "visible") fetchPlan();
    };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      window.clearInterval(tick);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [enabled, fetchPlan]);

  // 浮层展开时补一次，保证点开就是当前会话的最新计划
  useEffect(() => {
    if (!open || !enabled) return;
    fetchPlan();
  }, [open, enabled, fetchPlan]);

  if (!enabled) return null;

  const subtasks = plan?.subtasks ?? [];
  const totalCount = subtasks.length;
  const doneCount = subtasks.filter(
    (s) => s.state === "done" || s.state === "abandoned",
  ).length;
  const runningIdx = subtasks.findIndex((s) => s.state === "in_progress");
  const currentStep =
    runningIdx >= 0 ? runningIdx + 1 : Math.min(doneCount + 1, Math.max(totalCount, 1));
  const percent = totalCount > 0 ? Math.round((doneCount / totalCount) * 100) : 0;
  const isDone =
    !!plan && (plan.state === "done" || (totalCount > 0 && doneCount >= totalCount));
  const isAbandoned = !!plan && plan.state === "abandoned";

  // 徽标：无计划=灰标签；进行中/待办=蓝色「第 i/n 步」；完成=绿色「✓ n/n」
  let badgeText = L.entry;
  if (isDone) badgeText = `✓ ${doneCount}/${totalCount}`;
  else if (isAbandoned) badgeText = L.entry;
  else if (totalCount > 0) badgeText = L.step(currentStep, totalCount);

  const badgeColor = isDone
    ? "var(--colorSuccessText, #52c41a)"
    : plan
      ? "var(--colorPrimaryText, #1677ff)"
      : undefined;

  const tooltipText = isDone
    ? L.doneTip
    : isAbandoned
      ? L.abandonedTip
      : L.tooltip;

  const panelContent = (
    <div
      className={planStyles.content}
      style={{ padding: "4px 16px 12px", maxHeight: 400, overflowY: "auto" }}
    >
      {!plan ? (
        <div className={planStyles.emptyState} style={{ padding: "28px 12px" }}>
          <div className={planStyles.emptyIcon} style={{ fontSize: 34, marginBottom: 10 }}>
            📋
          </div>
          <div>{L.emptyTitle}</div>
          <div style={{ fontSize: 12, marginTop: 8 }}>{L.emptyHint}</div>
        </div>
      ) : (
        <>
          <div className={planStyles.planInfo}>
            <div className={planStyles.planName}>
              {plan.name}
              <span
                className={`${planStyles.planState} ${STATE_CLASS[plan.state] || ""}`}
              >
                {L.state[plan.state]}
              </span>
            </div>
            {plan.description && <div className={planStyles.planDesc}>{plan.description}</div>}
          </div>

          <div className={planStyles.progressSection}>
            <div className={planStyles.progressLabel}>
              {L.progress} — {doneCount}/{totalCount}
            </div>
            <Progress
              percent={percent}
              size="small"
              status={plan.state === "abandoned" ? "exception" : "active"}
              showInfo={false}
            />
          </div>

          <ul className={planStyles.subtaskList}>
            {subtasks.map((subtask, idx) => (
              <li key={idx} className={planStyles.subtaskItem}>
                <span className={planStyles.subtaskIcon}>
                  {STATE_ICONS[subtask.state] || "⬜"}
                </span>
                <div className={planStyles.subtaskBody}>
                  <div className={planStyles.subtaskName}>{subtask.name}</div>
                  {subtask.description && (
                    <div className={planStyles.subtaskDesc}>{subtask.description}</div>
                  )}
                  {subtask.outcome && (
                    <div className={planStyles.subtaskOutcome}>✓ {subtask.outcome}</div>
                  )}
                </div>
              </li>
            ))}
          </ul>

          {plan.outcome && (
            <div style={{ marginTop: 12, fontSize: 13 }}>
              <strong>{L.outcome}:</strong> {plan.outcome}
            </div>
          )}
        </>
      )}
    </div>
  );

  return (
    <Popover
      trigger="click"
      open={open}
      onOpenChange={setOpen}
      placement="bottomRight"
      arrow
      title={L.title}
      content={panelContent}
      styles={{
        body: {
          width: 420,
          // 浮窗（FloatingWindow）最窄 340px，窄屏同理：宽度做上限钳制，
          // 避免 420 固定宽在小窗口里溢出/遮挡输入框。
          maxWidth: "min(420px, calc(100vw - 24px))",
        },
        root: { zIndex: 1200 },
      }}
    >
      <Tooltip title={tooltipText} mouseEnterDelay={0.5}>
        <Button
          type="text"
          size="small"
          icon={<PlanIcon />}
          onClick={() => setOpen((v) => !v)}
          className={
            plan
              ? `${headerStyles.headerActionBtn} ${headerStyles.headerActionBtnActive}`
              : headerStyles.headerActionBtn
          }
        >
          <span style={{ fontSize: 12, color: badgeColor }}>{badgeText}</span>
        </Button>
      </Tooltip>
    </Popover>
  );
};

export default ChatPlanEntry;
