/**
 * ChatPlanCard — 挂在回答气泡里的执行计划卡
 *
 * 2026-11-20 v2.1（上一版是挂在消息区最底部的常驻看板，已撤）
 *
 * 参照 Claude Code / Codex 的取舍：工具调用细节可以折叠，但"接下来做哪几件
 * 事、现在做到第几步、每件事的结果是什么"必须看得见，而且要看在这轮对话里——
 * 之前它贴在整页底部，与总结区隔开几百像素，读起来像另一场对话的进度条。
 *
 * 三条行为尺子（2026-11-20 用户拍板）：
 *   - **只在最后一轮显示**：历史轮次里它曾出现，但用户回看不需要每张气泡都插
 *     一块进度条，所以 isLast=false 时直接不渲染；
 *   - **执行中摊开、答完自动收口**（2026-11-20 用户拍板修订）：跑的时候
 *     步骤全铺开，看得到做到第几步；这一轮答完自动收成一行（计划名 + 进度
 *     + 状态），想复盘点标题再展开——长会话回看不想满屏都是进度条。
 *   - 手动点开/收起过就听用户的（openKeys 里有值就不再自动决定）；卡里只
 *     展示当前这一份计划，历史轮次的计划一份都不列，避免一屏全是进度条。
 *
 * 数据通路沿用上一版（已实测可用，不另起一套）：
 *   - GET /plan/current 按会话作用域取本会话全部计划（刷新、切会话后仍在）；
 *   - subscribePlanUpdates 接实时推进，SSE 先乐观合并再防抖取权威列表；
 *   - 有步骤在跑时轮询兜底（焦点计划未完成就 2.5s 一次），SSE 断线也不停更；
 *   - 结果缺失的步骤明确标「结果待补」，不拿绿勾糊弄用户。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, message } from "antd";
import {
  planApi,
  subscribePlanUpdates,
  type PlanScopeView,
  type PlanStateResponse,
  type SubTaskResponse,
} from "@/api/modules/plan";
import styles from "./ChatPlanCard.module.less";

interface ChatPlanCardProps {
  /** 当前聊天 id；后端计划作用域以它为第一把尺子。 */
  chatId?: string;
  /**
   * 这条回答是不是会话里的最后一轮。SDK 的 append 槽位会把它传进来
   * （core/AgentScopeRuntime/Response/Card.js 里 render({data, isLast})）。
   * 计划是**这一轮**的进度，历史轮次不需要再插一块进度条，所以非最后一轮不渲染。
   */
  /**
   * SDK 塞给槽位的 data。注意它不是消息，而是消息里那张 response card 的
   * data（实测 id 形如 response_1795162772036-tr2ve2ive，而消息 id 是
   * 1795162772036-ate0molp2，两者对不上号），所以只能按对象引用比。
   */
  cardData?: unknown;
  /** 消息流快照：由页面层的 SDK 桥提供，用来判断本轮是不是最新一轮 */
  getMessages?: () => Array<{ id?: string; role?: string }> | undefined;

  isLast?: boolean;
  /**
   * 本轮消息 metadata 里存落的计划快照（后端 turn_plan_snapshot 写入）。
   * 有它就不必再去问 /plan/current —— 那问的是「现在」，不是「那一轮」。
   */
  snapshot?: unknown;
}

type StepState = SubTaskResponse["state"];

const DONE_STATES: StepState[] = ["done", "abandoned"];

function planKey(plan: PlanStateResponse, index: number): string {
  return plan.id || `${plan.name || "plan"}-${index}`;
}

/**
 * 「跑完了」的唯一尺子，与后端 plan.lifecycle.plan_really_done 一一对应：
 * state 是 done，**且每一步都真打上了勾**。
 *
 * 为什么不能只看 finished：runner 只在新开一份计划时才清 current，后端过去
 * 把「本会话最后一份」无条件兜底成 finished=false，于是 4/4 全 done 的计划
 * 也显示「进行中」且永远轮询（1e9c20b7 实测）。
 */
function isReallyDone(plan: PlanStateResponse): boolean {
  if (plan.state !== "done") return false;
  const states = (plan.subtasks || []).map((s) => s.state);
  return states.length > 0 && states.every((st) => st === "done");
}

const TERMINAL_PLAN_STATES = ["done", "abandoned"];

function isLive(plan: PlanStateResponse): boolean {
  // 终点态优先：勾完的计划、后端已标完成/已放弃的计划，不再算「在跑」。
  if (isReallyDone(plan) || plan.finished) return false;
  if (TERMINAL_PLAN_STATES.includes(plan.state)) return false;
  // 其余一律继续刷：todo 是「刚建好还没开跑」，in_progress 是正在跑；
  // 过去只认 in_progress，于是 todo 状态的新计划被判成跑完、进度永远出不来。
  return true;
}

/**
 * metadata 里的计划快照 → 卡片认识的计划对象。
 *
 * 字段尺子与后端 coapis.plan.lifecycle.plan_to_dict 一致（也就是
 * /api/plan/updates 推的那份）。这里只做防御式收敛，不重新发明字段：
 * 老消息没有这个键时返回 null，卡片就不显示，绝不编造一个计划。
 */
function fromSnapshot(raw: unknown): PlanStateResponse | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  if (!r.id && !r.name) return null;
  const subtasks: SubTaskResponse[] = Array.isArray(r.subtasks)
    ? r.subtasks
        .filter((s) => s && typeof s === "object")
        .map((s) => {
          const x = s as Record<string, unknown>;
          return {
            name: String(x.name ?? ""),
            description: String(x.description ?? ""),
            expected_outcome: String(x.expected_outcome ?? ""),
            outcome: (x.outcome ?? null) as string | null,
            state: (x.state ?? "todo") as SubTaskResponse["state"],
            created_at: (x.created_at ?? null) as string | null,
            finished_at: (x.finished_at ?? null) as string | null,
            outcome_pending: Boolean(x.outcome_pending),
          };
        })
    : [];
  return {
    id: String(r.id ?? ""),
    name: String(r.name ?? ""),
    description: String(r.description ?? ""),
    expected_outcome: String(r.expected_outcome ?? ""),
    state: (r.state ?? "todo") as PlanStateResponse["state"],
    subtasks,
    created_at: (r.created_at ?? null) as string | null,
    finished_at: (r.finished_at ?? null) as string | null,
    outcome: (r.outcome ?? null) as string | null,
    finished: Boolean(r.finished),
  };
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

export default function ChatPlanCard({
  chatId,
  isLast,
  cardData,
  getMessages,
  snapshot,
}: ChatPlanCardProps) {
  const { t } = useTranslation();
  // 本轮自带快照 → 静态渲染：不拉 /plan/current、不订阅 SSE、不轮询。
  // 那三样问的都是「现在」，会把别的轮次的计划串进这一轮。
  const snapshotPlan = useMemo(() => fromSnapshot(snapshot), [snapshot]);
  const [plans, setPlans] = useState<PlanStateResponse[]>([]);
  const [openKeys, setOpenKeys] = useState<Record<string, boolean>>({});

  // 作用域：计划是否还在等用户确认（pending_confirmation）。不接这个字段，
  // 卡片会把「等你点确认」显示成「进行中」，用户只能干看着 0/N 不动。
  const [scope, setScope] = useState<PlanScopeView | null>(null);
  const [confirming, setConfirming] = useState(false);
  // 本组件挂载期间（≈本轮）由 SSE 推过的计划 id。切换会话即清空，因此
  // 历史上的计划不会因为"它是最近的一份"就被当作当前计划显示。
  const pushedRef = useRef<Set<string>>(new Set());

  // 同一会话可能有多条 plan。两道闸：先只留下「仍在运行」或「本轮 SSE 推过」
  // 的（历史台账不参与"当前计划"的争夺），再在其中挑「最有进度的一条」——
  // 实测一轮里会留下两份同名计划（规则骨架 + 模型自建房），后一份常常全是
  // todo 的僵尸计划，按最后一条显示会写成「0/3 步」，而且它永远 unfinished，
  // 兜底轮询据此判断「还在跑」，一个空闲页面 3 分钟能打出 64 次接口。
  let focusPlan: PlanStateResponse | null = snapshotPlan;
  if (!focusPlan && plans.length > 0) {
    // 面板只认「仍在运行」或「本轮由 SSE 推过」的计划。历史计划留在台账
    // 里供查看，但不许顶替本轮的计划显示——这正是「问热点却弹出三天前那份
    // 已完成任务」的来源：接口会拿历史最新一份当兜底喂回来。
    const eligible = plans.filter((p) => {
      // 本轮 SSE 推过来过：一定是本轮的计划，直接放行。
      if (p.id && pushedRef.current.has(p.id)) return true;
      // 没推过的必须"真的动过"（有步骤已开始或已完成）才允许显示。
      // 纯 todo 的僵尸计划一律不上榜——它就是「还没开始 0/3 步」
      // 那位不速之客的来源，而且它永远 unfinished，会把兜底轮询吊着跑。
      return isLive(p) && (p.subtasks || []).some((s) => s.state !== "todo");
    });
    if (eligible.length > 0) {
      const newestFirst = eligible.slice().reverse();
      focusPlan =
        newestFirst.find(isLive) ??
        newestFirst.find(
          (p) =>
            p.subtasks?.some((s) => s.state === "in_progress") ||
            (p.subtasks && p.subtasks.every((s) => s.state === "done")),
        ) ??
        newestFirst.find((p) => p.subtasks && p.subtasks.length > 0) ??
        newestFirst[newestFirst.length - 1] ??
        null;
    }
  }

  // 「这一轮是不是最新一轮」自己判：SDK 在 prepend 槽位给的 isLast 实测拿不到
  // 真值（计划接口已返回 2 条、组件也确实挂载并在轮询，卡片却整轮 0 命中），
  // 所以改成取消息流里最后一条非用户消息的 id 与本轮 turnId 比对。turnId 拿不
  // 到时退回 isLast；两头都拿不到就默认显示——宁可多显示，也不要整轮空白。
  const pendingConfirm = scope?.status === "pending_confirmation";

  const handleConfirm = async () => {
    const title = scope?.plan_title;
    if (!chatId || !title) return;
    setConfirming(true);
    try {
      await planApi.confirmPlan({ session_id: chatId, plan_title: title });
      message.success(t("plan.confirmSuccess", "方案已确认，开始执行"));
      void refresh();
    } catch {
      message.error(t("plan.confirmFailed", "确认失败"));
    } finally {
      setConfirming(false);
    }
  };

  const ownsTurn = (() => {
    if (!cardData) return isLast !== false;
    const list = (getMessages?.() || []) as Array<{
      role?: string;
      cards?: Array<{ data?: unknown }>;
    }>;
    let lastAssistant = null;
    for (let i = list.length - 1; i >= 0; i -= 1) {
      const m = list[i];
      if (m && m.role !== "user") {
        lastAssistant = m;
        break;
      }
    }
    const mine = lastAssistant?.cards?.[0]?.data;
    // 桥没挂上、消息流还没建起来时别拿它当依据，退回 isLast。
    if (!mine) return isLast !== false;
    return mine === cardData;
  })();
  // 自带快照的轮次永远可见（含刷新后的历史轮）；没有快照又不在当前轮，
  // 就不显示——老会话没存落计划，宁可空着也不编一个。
  const visible = snapshotPlan ? true : ownsTurn && plans.length > 0;
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
        setScope(res.scope || null);
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
    if (snapshotPlan) return;
    keyRef.current = "";
    pushedRef.current = new Set();
    setPlans([]);
    void refresh();
  }, [refresh, snapshotPlan]);

  // 实时推进：SSE 事件先乐观合并，再防抖取一次权威列表。
  useEffect(() => {
    if (snapshotPlan) return () => {};
    const off = subscribePlanUpdates(
      (plan: PlanStateResponse | null) => {
        if (plan) {
          if (plan.id) pushedRef.current.add(plan.id);
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

  // 有步骤在跑时轮询兜底（SSE 断线也不至于停更）；跑完就停。
  // 停之前补刷两次（2.5s / 8s）：最后一步的落账偶尔比 state=done 晚到，
  // 2026-11-20 实测过面板停在「3/5」不动，就是收尾那一下之后再没刷过。
  const prevLive = useRef<boolean | null>(null);
  const graceTimers = useRef<number[]>([]);
  useEffect(() => {
    const busy =
      !snapshotPlan && visible && !!focusPlan && isLive(focusPlan);
    const was = prevLive.current;
    prevLive.current = busy;
    if (busy) {
      const timer = setInterval(() => {
        void refresh();
      }, 2500);
      return () => clearInterval(timer);
    }
    if (was && visible) {
      graceTimers.current = [2500, 8000].map((ms) =>
        window.setTimeout(() => {
          void refresh();
        }, ms),
      );
    }
    return undefined;
  }, [plans, visible, focusPlan, refresh]);

  useEffect(
    () => () => {
      graceTimers.current.forEach((t) => clearTimeout(t));
    },
    [],
  );

  if (!visible || !focusPlan) return null;

  const focus = focusPlan as PlanStateResponse;
  // 快照卡片代表的是「已经结束的那一轮」，计划本身不再算在跑。
  const live = snapshotPlan ? false : isLive(focus);
  const focusKey = planKey(focus, plans.length - 1);
  // 折叠尺子（2026-11-21 用户拍板修订：不做自动收口，**默认摊开，收不收由用户点按钮**）：
  //   卡里一行一条、只有「做哪件事 + 状态点」，头部带 x/y 进度，本身已经够短，
  //   不需要按回答状态去猜该不该藏。用户点过收起/展开就听用户的（openKeys 里有
  //   值就不再自动决定）；没点过一律摊开——宁可多占一行，也不把进度藏起来。

  const focusOpen = openKeys[focusKey] !== undefined ? openKeys[focusKey] : true;
  const progress = countProgress(focus);
  const steps = focus.subtasks || [];

  // 每一步都打上勾了就叫「都办完了」：后端偶尔来不及把 state 收成 done（例如轮次被
  // 调用上限截断），这时还写「正在做」是在骗人——勾全绿了却显示在跑（实测 dev 会话 d6404ec3）。
  const allStepsDone = (plan: PlanStateResponse) => {
    const p = countProgress(plan);
    return p.total > 0 && p.done === p.total;
  };

  const stateLabel = (plan: PlanStateResponse, isNowLive: boolean) => {
    if (plan.state === "abandoned") {
      return t("planBoard.abandoned", "已取消");
    }
    if (allStepsDone(plan)) {
      return t("planBoard.completed", "都办完了");
    }
    if (!isNowLive) {
      // 收尾态得分开说（2026-11-25 用户要求用语准确）：
      // 一步没迈=还没开始（多半卡在确认门被晾下），走了一半停下=停在半路。
      // 勾没走完却说「都办完了」是撒谎，所以这里绝不返回 completed。
      const moved = (plan.subtasks || []).some((st) => st.state !== "todo");
      return moved
        ? t("planBoard.paused", "停在半路")
        : t("planBoard.notStarted", "还没开始");
    }
    // 一步都没动过就别写「进行中」：确认门关掉后计划会被晾在那里，0/N 一直挂着
    // 「进行中」看着像在跑，其实什么都没发生（实测 dev 会话 4ca25e52）。
    const moving = (plan.subtasks || []).some((st) => st.state !== "todo");
    return moving
      ? t("planBoard.inProgress", "正在做")
      : t("planBoard.notStarted", "还没开始");
  };

  return (
    <div className={styles.board} data-testid="chat-plan-card">
      <div className={`${styles.header} ${focusOpen ? styles.headerOpen : ""}`}>
        <span className={styles.title}>
          {t("planBoard.title", "进度")}
        </span>
        <span className={styles.planName} title={focus.name}>
          {focus.name || t("planBoard.unnamed", "未命名计划")}
        </span>
        <span
            className={
              (live && !allStepsDone(focus)) || pendingConfirm
                ? styles.chipLive
                : styles.chipDone
            }
        >
          {pendingConfirm
            ? t("planBoard.pendingBadge", "等你确认")
            : stateLabel(focus, live)}
        </span>
        <span className={styles.progress}>
          {t("planBoard.stepProgress", "{{done}}/{{total}} 步", {
            done: progress.done,
            total: progress.total,
          })}
        </span>
        <button
          type="button"
          className={styles.caret}
          onClick={() =>
            setOpenKeys((prev) => ({ ...prev, [focusKey]: !focusOpen }))
          }
          aria-expanded={focusOpen}
          aria-label={
            focusOpen
              ? t("planBoard.collapseAria", "收起计划")
              : t("planBoard.expandAria", "展开计划")
          }
          title={
            focusOpen
              ? t("planBoard.collapseAria", "收起计划")
              : t("planBoard.expandAria", "展开计划")
          }
          data-testid="plan-toggle"
        >
          <span className={styles.caretGlyph} />
        </button>
      </div>

      {focusOpen && pendingConfirm && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 8,
            padding: "6px 10px",
            marginBottom: 6,
            borderRadius: 6,
            background: "rgba(250, 173, 20, 0.10)",
            fontSize: 12,
          }}
        >
          <span>
            {t("plan.confirmTitle", { defaultValue: "这一步需要你点个头：{{title}}", title: scope?.plan_title || "" })}
            {" · "}
            {t("plan.confirmHint", "这一步要动到外部系统，确认后才开工")}
          </span>
          <Button size="small" type="primary" loading={confirming} onClick={handleConfirm}>
            {t("plan.confirmAction", "可以，继续")}
          </Button>
        </div>
      )}
      {focusOpen && (
        <div className={styles.body}>
          <ul className={styles.steps}>
            {steps.map((step, idx) => (
              <StepRow key={`${planKey(focus, plans.length - 1)}-${idx}`} step={step} />
            ))}
          </ul>
        </div>
      )}

    </div>
  );
}

function StepRow({ step }: { step: SubTaskResponse }) {
  const { t } = useTranslation();
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

  // 一行一条（2026-11-21 用户拍板：不必太多，只要知道做了什么、完成进度）：
  // 卡里只留「这一步做什么」加状态点。目标、结果、结果待补这类细节收进
  // title 悬浮，不再各占一行——这块的作用是「做到哪了」，不是复盘报告。
  const detail = [
    goal ? t("planBoard.goal", "目标") + ": " + goal : "",
    result ? t("planBoard.result", "结果") + ": " + result : "",
    step.outcome_pending ? t("planBoard.resultMissing", "结果还没记") : "",
  ]
    .filter(Boolean)
    .join(" / ");

  return (
    <li
      className={styles.step}
      data-state={step.state}
      title={detail || step.name}
    >
      <span className={styles.markerSlot}>{marker}</span>
      <span
        className={
          step.state === "in_progress" ? styles.stepNameRun : styles.stepName
        }
      >
        {step.name}
      </span>
    </li>
  );
}