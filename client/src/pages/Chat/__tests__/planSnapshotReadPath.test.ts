/**
 * 计划快照读取路径 · 契约测试
 * ---------------------------------------------------------------------------
 * 钉住两件事：
 *  1. 快照要从「本轮最后一条正式回复」的 metadata.metadata.plan_snapshot 读，
 *     插槽给的 data 本身没有 metadata；
 *  2. 页面代码不许再回到 data.metadata 这条读不到的老路。
 *
 * 背景：2026-11-25 实测——后端快照确实落进了聊天记录（会话 JSON 里查得到），
 * 但刷新后计划卡片一张都不出，根因就是前端读的是 data.metadata（恒 undefined）。
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { planSnapshotFromResponse } from "../planSnapshot";

const SNAP = {
  plan_id: "plan-1",
  title: "列出并统计根目录文件",
  state: "completed",
  steps: [
    { name: "列文件", status: "done" },
    { name: "统计", status: "done" },
  ],
};

/** 按 SDK 真实形状造一轮应答：data 没有 metadata，快照挂在正式回复上。 */
function response(messages: any[]) {
  return {
    id: "resp-1",
    object: "response",
    status: "completed",
    output: messages,
  };
}

function assistantMessage(meta: any) {
  return {
    id: "msg-1",
    type: "message",
    role: "assistant",
    content: [{ type: "text", text: "都办完了" }],
    metadata: { original_id: "o1", original_name: "小蜜蜂", metadata: meta },
  };
}

describe("planSnapshotFromResponse", () => {
  it("从本轮最后一条正式回复里取到快照", () => {
    const data = response([
      { id: "t1", type: "plugin_call", role: "assistant" },
      assistantMessage({ plan_snapshot: SNAP }),
    ]);
    expect(planSnapshotFromResponse(data)).toEqual(SNAP);
  });

  it("取最后一条带快照的正式回复，不被前面的消息干扰", () => {
    const data = response([
      assistantMessage({ plan_snapshot: { ...SNAP, plan_id: "old" } }),
      { id: "t2", type: "plugin_call_output", role: "system" },
      assistantMessage({ plan_snapshot: SNAP }),
    ]);
    expect(planSnapshotFromResponse(data)?.plan_id).toBe("plan-1");
  });

  it("思考消息和工具消息上的快照不算数（只认正式回复）", () => {
    const data = response([
      {
        id: "r1",
        type: "reasoning",
        role: "assistant",
        metadata: { metadata: { plan_snapshot: SNAP } },
      },
      {
        id: "t1",
        type: "plugin_call",
        role: "assistant",
        metadata: { metadata: { plan_snapshot: SNAP } },
      },
    ]);
    expect(planSnapshotFromResponse(data)).toBeUndefined();
  });

  it("老会话没有快照时返回 undefined，卡片就不显示", () => {
    const data = response([assistantMessage({ original_id: "o1" })]);
    expect(planSnapshotFromResponse(data)).toBeUndefined();
  });

  it("应答缺 output 或非数组时不炸", () => {
    expect(planSnapshotFromResponse(undefined)).toBeUndefined();
    expect(planSnapshotFromResponse({})).toBeUndefined();
    expect(planSnapshotFromResponse({ output: "not-array" })).toBeUndefined();
  });
});

describe("页面读取路径不回退", () => {
  const source = readFileSync(
    resolve(process.cwd(), "src/pages/Chat/index.tsx"),
    "utf8",
  );

  it("计划卡片的快照来自 planSnapshotFromResponse，不是 data.metadata", () => {
    expect(source).toContain("snapshot={planSnapshotFromResponse(data)}");
    expect(source).not.toContain("data?.metadata?.metadata?.plan_snapshot");
  });
});
