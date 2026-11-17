/**
 * B0 契约锁 · 计划数据在 wire 上的形状
 * ---------------------------------------------------------------------------
 * 钉住两个曾经真实发生过的前端缺陷：
 *
 *  1. `GET /plan/current` 返回的是信封 `{plan, session_id, usage}`，而旧代码
 *     把整个信封当计划用，于是 `subtasks` 恒为 undefined —— 计划面板永远显示
 *     0/0，且因为对象非空，UI 还一直以为"有计划"。
 *  2. 后端一份计划同时挂在通道会话 id（`console:admin`）和聊天 UUID 下，
 *     SSE 事件里两个键都在 `session_ids` 中；旧过滤只比 `session_id`，
 *     用 UUID 寻址的前端会把**每一条**计划事件丢掉。
 *
 * 两条都在 API 层收口（unwrapPlan / planEventMatchesSession），所以这里测的
 * 就是产品真实走的函数，不是复制一份等价表达式。
 */
import { describe, expect, it } from "vitest";
import {
  planEventMatchesSession,
  unwrapPlan,
} from "../plan";

const PLAN = {
  id: "p1",
  name: "三步文件演练",
  description: "d",
  expected_outcome: "eo",
  state: "in_progress" as const,
  subtasks: [
    {
      name: "s1",
      description: "d",
      expected_outcome: "e",
      outcome: null,
      state: "done" as const,
      created_at: null,
      finished_at: null,
    },
  ],
  created_at: null,
  finished_at: null,
  outcome: null,
};

describe("unwrapPlan — 信封必须解包", () => {
  it("解出信封里的计划", () => {
    const got = unwrapPlan({
      plan: PLAN,
      session_id: "console:admin",
      usage: {},
    });
    expect(got?.name).toBe("三步文件演练");
    expect(got?.subtasks).toHaveLength(1);
  });

  it("信封里 plan=null 时返回 null，而不是把信封当计划", () => {
    expect(unwrapPlan({ plan: null, session_id: "s" })).toBeNull();
  });

  it("兼容裸计划对象", () => {
    expect(unwrapPlan(PLAN)?.id).toBe("p1");
  });

  it("空值一律 null", () => {
    expect(unwrapPlan(null)).toBeNull();
    expect(unwrapPlan(undefined)).toBeNull();
    expect(unwrapPlan({} as never)).toBeNull();
  });
});

describe("planEventMatchesSession — 别名必须能命中", () => {
  it("事件 session_id 与本地 id 相同：通过", () => {
    expect(
      planEventMatchesSession({ session_id: "console:admin" }, "console:admin"),
    ).toBe(true);
  });

  it("本地是聊天 UUID、事件主键是通道 id，但别名里有 UUID：通过", () => {
    expect(
      planEventMatchesSession(
        {
          session_id: "console:admin",
          session_ids: ["console:admin", "a089b560-uuid"],
        },
        "a089b560-uuid",
      ),
    ).toBe(true);
  });

  it("别名里没有本地 id：仍然拦掉，避免串会话", () => {
    expect(
      planEventMatchesSession(
        { session_id: "console:admin", session_ids: ["console:admin"] },
        "other-chat-uuid",
      ),
    ).toBe(false);
  });

  it("事件没有会话信息：不拦（后端旧版本兼容）", () => {
    expect(planEventMatchesSession({}, "any")).toBe(true);
    expect(planEventMatchesSession({ session_id: "" }, "any")).toBe(true);
  });

  it("本地没有 id：全部放行", () => {
    expect(planEventMatchesSession({ session_id: "x" }, undefined)).toBe(true);
  });
});
