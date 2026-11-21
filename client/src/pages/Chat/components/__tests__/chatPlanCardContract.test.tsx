/**
 * 执行计划卡契约锁 · ChatPlanCard（2026-11-20 v2.1）
 * ---------------------------------------------------------------------------
 * 这一版把它从「贴在消息区最底部的常驻看板」改成了「画进本轮回答气泡里的计
 * 划卡」，同时按用户拍板改了折叠尺子。钉住四件肉眼可见的事：
 *  1. **只在最后一轮渲染**：历史气泡不插进度条（isLast=false 直接为空）；
 *  2. **执行中展开**：步骤与结果即时铺开，用户能看到做到第几步；
 *  3. **收起靠按钮**：卡片默认摊开，点标题栏的「收起」才压成一行（计划名 +
 *     N/N + 状态），再点「展开」还原——不猜回答状态、不做自动收口；
 *  4. 计划跑完**不许消失**；步骤自称完成却没有可用结果时，显示「结果待补」
 *     而不是绿勾；没有计划的会话渲染为空，不摆空框。
 *
 * 断言全部对着真实渲染的 DOM 写，不锁 CSS 类名。
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ChatPlanCard from "../ChatPlanCard";
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
    // 卡片的数据通路：真实实现会把后端三种形态归一成 plans 列表，
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

describe("ChatPlanCard", () => {
  it("非最后一轮不渲染：回看旧气泡时每张都插进度条是噪声", async () => {
    getCurrentPlanWithScope.mockResolvedValue(
      body([
        plan({
          state: "done",
          finished: true,
          subtasks: [step({ name: "读源码", state: "done", outcome: "A" })],
        }),
      ]),
    );

    const { container } = render(
      <ChatPlanCard chatId="chat-1" isLast={false} />,
    );
    await waitFor(() => expect(getCurrentPlanWithScope).toHaveBeenCalled());
    expect(container.firstChild).toBeNull();
  });

  it("执行中默认展开：步骤铺开、进度与「正在做」看得见", async () => {
    getCurrentPlanWithScope.mockResolvedValue(
      body([
        plan({
          subtasks: [
            step({ name: "读源码", state: "done", outcome: "确认 3 个入口" }),
            step({ name: "写文档", state: "in_progress" }),
          ],
        }),
      ]),
    );

    render(<ChatPlanCard chatId="chat-1" isLast />);

    expect(await screen.findByText("进度")).toBeInTheDocument();
    expect(screen.getByText("正在做")).toBeInTheDocument();
    expect(screen.getByText("1/2 步")).toBeInTheDocument();
    // 执行中：步骤直接铺开，不用点
    expect(screen.getByText("写文档")).toBeInTheDocument();
    expect(screen.getByText("读源码")).toBeInTheDocument();
  });

  it("答完不自动收口：默认仍摊开，点「收起」才收成一行，再点「展开」还原", async () => {
    getCurrentPlanWithScope.mockResolvedValue(
      body([
        plan({
          state: "done",
          finished: true,
          subtasks: [
            step({ name: "读源码", state: "done", outcome: "确认 3 个入口" }),
            step({
              name: "写文档",
              state: "done",
              outcome: "生成 lifecycle.md",
            }),
          ],
        }),
      ]),
    );

    render(
      <ChatPlanCard chatId="chat-1" isLast cardData={{ status: "completed" }} />,
    );

    // 答完也摊着：步骤看得见，按钮写着「收起」。
    expect(await screen.findByText("进度")).toBeInTheDocument();
    expect(screen.getByText("生成 lifecycle 说明文档")).toBeInTheDocument();
    expect(screen.getByText("都办完了")).toBeInTheDocument();
    expect(screen.getByText("2/2 步")).toBeInTheDocument();
    expect(screen.getByText("写文档")).toBeInTheDocument();
    const toggle = screen.getByTestId("plan-toggle");
    expect(toggle).toHaveTextContent("收起");

    // 点收起：只剩一行（计划名、状态、进度仍在），步骤消失。
    fireEvent.click(toggle);
    await waitFor(() => expect(screen.queryByText("写文档")).toBeNull());
    expect(screen.getByText("2/2 步")).toBeInTheDocument();
    expect(toggle).toHaveTextContent("展开");

    // 再点展开：步骤回来。
    fireEvent.click(toggle);
    await waitFor(() => expect(screen.getByText("写文档")).toBeInTheDocument());
    expect(toggle).toHaveTextContent("收起");
  });

  it("步骤一行一条：只渲染步骤名，目标与结果收进悬浮 title", async () => {
    getCurrentPlanWithScope.mockResolvedValue(
      body([
        plan({
          state: "done",
          finished: true,
          subtasks: [
            step({
              name: "读源码",
              state: "done",
              expected_outcome: "摸清计划生命周期",
              outcome: "确认 3 个入口",
            }),
          ],
        }),
      ]),
    );

    render(<ChatPlanCard chatId="chat-1" isLast />);

    await screen.findByText("进度");
    const row = await screen.findByText("读源码");
    const title = row.closest("li")?.getAttribute("title") || "";
    // 一条一行：明细不占行，收在这一步的 title 里。
    expect(title).toContain("确认 3 个入口");
    expect(screen.queryByText("确认 3 个入口")).toBeNull();
    expect(screen.queryByText("摸清计划生命周期")).toBeNull();
  });
  it("后端把跑完的计划仍报成 finished=false 时，卡片以 state 为准显示「都办完了」", async () => {
    // 1e9c20b7 实测：4/4 全 done、finished_at 已落，卡片仍写「正在做」且一直轮询。
    getCurrentPlanWithScope.mockResolvedValue(
      body([
        plan({
          state: "done",
          finished: false,
          finished_at: "2026-11-20T10:29:46",
          subtasks: [
            step({ name: "建目录", state: "done", outcome: "a.txt 1 行" }),
            step({ name: "合并", state: "done", outcome: "c.txt 2 行" }),
          ],
        }),
      ]),
    );

    render(<ChatPlanCard chatId="chat-1" isLast />);

    await waitFor(() => expect(screen.getByText("都办完了")).toBeInTheDocument());
    expect(screen.queryByText("正在做")).toBeNull();

    // 勾完的计划不再轮询：只有挂载那一次取数。
    await new Promise((resolve) => setTimeout(resolve, 3000));
    expect(getCurrentPlanWithScope).toHaveBeenCalledTimes(1);
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

    render(
      <ChatPlanCard chatId="chat-1" isLast cardData={{ status: "in_progress" }} />,
    );
    await screen.findByText("进度");
    // 一行一条之后，明细都收在这一步的 title 里，不再单独占行。
    const rows = document.querySelectorAll("li[data-state]");
    const titles = Array.from(rows).map((el) => el.getAttribute("title") || "");
    expect(titles.some((x) => x.includes("结果还没记"))).toBe(true);
    expect(screen.getByText("空口的步骤")).toBeInTheDocument();
    expect(titles.some((x) => x.includes("产出 A 文件"))).toBe(true);
    expect(screen.getByText("有产出的步骤")).toBeInTheDocument();
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

    render(<ChatPlanCard chatId="chat-1" isLast />);

    // 焦点 = 最新一份：执行中，所以它的步骤默认铺开
    await screen.findByText("第二件：补测试");
    expect(screen.getByText("焦点步骤乙")).toBeInTheDocument();
    // 更早的一份只占一行（有名字、有进度），步骤默认收起
    expect(screen.getByText("第一件：梳理依赖")).toBeInTheDocument();
    expect(screen.queryByText("历史步骤甲")).toBeNull();

    fireEvent.click(screen.getByText("第一件：梳理依赖"));
    await waitFor(() =>
      expect(screen.getByText("历史步骤甲")).toBeInTheDocument(),
    );
  });

  it("没有计划的会话不渲染空框", async () => {
    getCurrentPlanWithScope.mockResolvedValue({ plan: null, plans: [] });
    const { container } = render(<ChatPlanCard chatId="chat-1" isLast />);
    await waitFor(() => expect(getCurrentPlanWithScope).toHaveBeenCalled());
    expect(container.firstChild).toBeNull();
  });

  it("接口失败时静默（聊天页不许被计划模块拖崩）", async () => {
    getCurrentPlanWithScope.mockRejectedValue(new Error("network down"));
    const { container } = render(<ChatPlanCard chatId="chat-1" isLast />);
    await waitFor(() => expect(getCurrentPlanWithScope).toHaveBeenCalled());
    expect(container.firstChild).toBeNull();
  });
});
