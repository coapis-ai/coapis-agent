/**
 * 计划看板契约锁 · ChatPlanBoard（2026-11-19 计划执行能力优化）
 * ---------------------------------------------------------------------------
 * 钉住用户能肉眼看到的四件事（方案 K1/K3/K4）：
 *  1. 计划跑完**不许消失**——completed 状态仍然渲染，并写明"已完成"；
 *  2. 每一步的结果直接摆出来；步骤自称完成却没有可用结果时，显示
 *     「结果待补」而不是绿勾（这是 K4 那把尺子在 UI 上的落点）；
 *  3. 一个会话跑过多次计划时，最新一份当焦点，更早的收进历史里可展开；
 *  4. 没有计划的会话渲染为空，不给用户摆空框。
 *
 * 断言全部对着真实渲染的 DOM 写，不锁 CSS 类名。
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ChatPlanBoard from "../ChatPlanBoard";
import { resolvePlanHistory } from "@/api/modules/plan";
import type {
  PlanQueryResponse,
  PlanStateResponse,
} from "@/api/modules/plan";

const { getCurrentPlanWithScope, subscribePlanUpdates } = vi.hoisted(() => ({
  getCurrentPlanWithScope: vi.fn(),
  subscribePlanUpdates: vi.fn(() => () => {}),
}));

vi.mock("@/api/modules/plan", async () => {
  const actual =
    await vi.importActual<typeof import("@/api/modules/plan")>(
      "@/api/modules/plan",
    );
  return {
    ...actual,
    // 看板的数据通路：真实实现会把后端三种形态归一成 plans 列表，
    // 这里只把网络层换成可控数据，SSE 换成空实现，避免测试去连真实流。
    planApi: { getCurrentPlanWithScope },
    subscribePlanUpdates,
  };
});

function step(over: Partial<import("@/api/modules/plan").SubTaskResponse> = {}) {
  return {
    name: "步骤",
    description: "",
    expected_outcome: "预期产出",
    outcome: "",
    state: "todo" as const,
    created_at: null,
    finished_at: null,
    outcome_pending: false,
    ...over,
  };
}

function plan(over: Partial<PlanStateResponse> = {}): PlanStateResponse {
  return {
    id: "p1",
    name: "生成 lifecycle 说明文档",
    description: "把模块生命周期讲清楚",
    expected_outcome: "一份 md 文档",
    state: "in_progress",
    subtasks: [step({ name: "读源码" })],
    created_at: "2026-11-19T00:00:00",
    finished_at: null,
    finished: false,
    ...over,
  } as PlanStateResponse;
}

function body(plans: PlanStateResponse[]): PlanQueryResponse {
  return {
    plans,
    plan: plans.length ? plans[plans.length - 1] : null,
    session_id: "chat-1",
  };
}

describe("resolvePlanHistory", () => {
  it("三种后端形态都能归一成列表（plans / 只有 plan / 都为空）", () => {
    const p1 = plan({ id: "p1" });
    const p2 = plan({ id: "p2" });
    expect(resolvePlanHistory(body([p1, p2])).map((p) => p.id)).toEqual([
      "p1",
      "p2",
    ]);
    // 老后端只回 plan
    expect(
      resolvePlanHistory({ plan: p2, session_id: "chat-1" }).map((p) => p.id),
    ).toEqual(["p2"]);
    // 两个都给且不重复
    expect(
      resolvePlanHistory(body([p1, p2])).map((p) => p.id),
    ).toEqual(["p1", "p2"]);
    expect(resolvePlanHistory({ plan: null })).toEqual([]);
    expect(resolvePlanHistory(null)).toEqual([]);
    // 单份计划对象（非信封）也要能渲染
    expect(resolvePlanHistory(p1).map((p) => p.id)).toEqual(["p1"]);
  });

  it("plan 与 plans 指向同一份时不重复渲染", () => {
    const p1 = plan({ id: "p1" });
    const merged = resolvePlanHistory({ plans: [p1], plan: p1 });
    expect(merged.map((p) => p.id)).toEqual(["p1"]);
  });
});

describe("ChatPlanBoard", () => {
  it("跑完的计划不消失：已完成仍渲染，并写明已完成与进度", async () => {
    getCurrentPlanWithScope.mockResolvedValue(
      body([
        plan({
          state: "done",
          finished: true,
          subtasks: [
            step({ name: "读源码", state: "done", outcome: "确认 3 个入口" }),
            step({ name: "写文档", state: "done", outcome: "生成 lifecycle.md" }),
          ],
        }),
      ]),
    );

    render(<ChatPlanBoard chatId="chat-1" />);

    expect(await screen.findByText("执行计划")).toBeInTheDocument();
    expect(screen.getByText("已完成")).toBeInTheDocument();
    expect(screen.getByText("2/2")).toBeInTheDocument();
    expect(screen.getByText("生成 lifecycle 说明文档")).toBeInTheDocument();
    // 每步的结果直接摆出来，不用展开
    expect(screen.getByText("确认 3 个入口")).toBeInTheDocument();
    expect(screen.getByText("生成 lifecycle.md")).toBeInTheDocument();
  });

  it("自称完成但没有可用结果 → 显示「结果待补」而不是绿勾", async () => {
    getCurrentPlanWithScope.mockResolvedValue(
      body([
        plan({
          state: "done",
          finished: true,
          subtasks: [
            step({
              name: "有产出的步骤",
              state: "done",
              outcome: "产出 A 文件",
              outcome_pending: false,
            }),
            // outcome_pending 由后端算好下发，前端只认这一把尺子、不再自算
            step({
              name: "空口的步骤",
              state: "done",
              outcome: "done",
              outcome_pending: true,
            }),
          ],
        }),
      ]),
    );

    render(<ChatPlanBoard chatId="chat-1" />);

    await screen.findByText("执行计划");
    expect(screen.getByText("结果待补")).toBeInTheDocument();
    expect(screen.getByText("产出 A 文件")).toBeInTheDocument();
  });

  it("多次计划：最新一份当焦点，更早的收成一行、默认不铺开步骤", async () => {
    getCurrentPlanWithScope.mockResolvedValue(
      body([
        plan({
          id: "p1",
          name: "第一件：梳理依赖",
          finished: true,
          state: "done",
          subtasks: [step({ name: "历史步骤甲", state: "done" })],
        }),
        plan({
          id: "p2",
          name: "第二件：补测试",
          subtasks: [step({ name: "焦点步骤乙", state: "in_progress" })],
        }),
      ]),
    );

    render(<ChatPlanBoard chatId="chat-1" />);

    // 焦点 = 最新一份：它的步骤默认铺开
    await screen.findByText("第二件：补测试");
    expect(screen.getByText("焦点步骤乙")).toBeInTheDocument();
    // 更早的一份只占一行（有名字、有进度），但步骤默认收起
    expect(screen.getByText("第一件：梳理依赖")).toBeInTheDocument();
    expect(screen.queryByText("历史步骤甲")).toBeNull();

    fireEvent.click(screen.getByText("第一件：梳理依赖"));
    await waitFor(() =>
      expect(screen.getByText("历史步骤甲")).toBeInTheDocument(),
    );
  });

  it("没有计划的会话不渲染空框", async () => {
    getCurrentPlanWithScope.mockResolvedValue({ plan: null, plans: [] });
    const { container } = render(<ChatPlanBoard chatId="chat-1" />);
    await waitFor(() => expect(getCurrentPlanWithScope).toHaveBeenCalled());
    expect(container.firstChild).toBeNull();
  });

  it("接口失败时静默（聊天页不许被计划模块拖崩）", async () => {
    getCurrentPlanWithScope.mockRejectedValue(new Error("network down"));
    const { container } = render(<ChatPlanBoard chatId="chat-1" />);
    await waitFor(() => expect(getCurrentPlanWithScope).toHaveBeenCalled());
    expect(container.firstChild).toBeNull();
  });
});
