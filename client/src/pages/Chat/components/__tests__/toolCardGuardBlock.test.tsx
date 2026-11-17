/**
 * 拦截态契约锁 · 被安全规则拦下的工具卡
 * ---------------------------------------------------------------------------
 * 钉住小蜜蜂 2026-11-17 的两条要求：
 *  1) 尾巴1：动作被拦下时**没有执行**，界面不许再显示绿色✅；
 *  2) 尾巴2：拦下之后用户必须看得见"为什么没执行"，不能只剩一个思考块。
 *
 * 实现契约：后端在工具输出首行下发哨兵
 *   [[coapis:tool-blocked]] kind=<plan_scope_pending|guard_denied>
 * 前端 parseGuardBlock 认首行 → 剥掉哨兵行 → 卡片渲染成 ⛔ 已拦下 + 原因，
 * 并且默认展开（用户不必点）。只有首行算数，正文里偶然出现同样字样不误判。
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import EnhancedToolCallCard, {
  GUARD_BLOCK_SENTINEL,
  coerceToolOutput,
  computeCardActiveKey,
  guardBlockReason,
  parseGuardBlock,
} from "../EnhancedToolCallCard";

const SENTINEL = GUARD_BLOCK_SENTINEL;
const REASON_BODY = "方案「清理临时目录」还没得到用户确认，因此这个动作被拦下了。";

type ToolData = Parameters<typeof EnhancedToolCallCard>[0]["data"];

function toolData(opts: { status?: string; name?: string; output?: string }): ToolData {
  return {
    status: opts.status,
    content: [
      { data: { name: opts.name ?? "read_file", arguments: '{"path":"/tmp/x"}' } },
      { data: { output: opts.output } },
    ],
  };
}

describe("coerceToolOutput —— 输出形状归一（实测：卡片常收到块数组的 JSON 串）", () => {
  const blockJson = JSON.stringify([
    { type: "text", text: `${SENTINEL} kind=guard_denied\n${REASON_BODY}` },
  ]);

  it("块数组的 JSON 串 → 归一成纯文本，哨兵回到首行", () => {
    const text = coerceToolOutput(blockJson);
    expect(text.startsWith(`${SENTINEL} kind=guard_denied`)).toBe(true);
    expect(parseGuardBlock(text)?.kind).toBe("guard_denied");
  });

  it("真的块数组 → 归一成纯文本", () => {
    const text = coerceToolOutput([
      { type: "text", text: "第一段" },
      { type: "text", text: "第二段" },
    ]);
    expect(text).toBe("第一段\n第二段");
  });

  it("工具真的返回 JSON 数据 → 原样保留，不吞内容", () => {
    const payload = '{"total": 3, "items": ["a","b"]}';
    expect(coerceToolOutput(payload)).toBe(payload);
  });

  it("普通字符串 → 原样", () => {
    expect(coerceToolOutput("命令执行完成")).toBe("命令执行完成");
    expect(coerceToolOutput(undefined)).toBe("");
  });
});

// ---------------------------------------------------------------------------
// 纯函数尺子
// ---------------------------------------------------------------------------

describe("parseGuardBlock —— 哨兵尺子", () => {
  it("首行哨兵 → 认出 kind 并剥掉哨兵行", () => {
    const parsed = parseGuardBlock(`${SENTINEL} kind=plan_scope_pending\n${REASON_BODY}`);
    expect(parsed).not.toBeNull();
    expect(parsed!.kind).toBe("plan_scope_pending");
    expect(parsed!.text).toBe(REASON_BODY);
    expect(parsed!.text).not.toContain("coapis:tool-blocked");
  });

  it("kind 缺失 → 回退 guard_denied", () => {
    const parsed = parseGuardBlock(`${SENTINEL}\n${REASON_BODY}`);
    expect(parsed!.kind).toBe("guard_denied");
  });

  it("普通成功输出 → 不算拦下", () => {
    expect(parseGuardBlock("文件已读取完成，共 12 行。")).toBeNull();
    expect(parseGuardBlock(undefined)).toBeNull();
    expect(parseGuardBlock("")).toBeNull();
  });

  it("哨兵出现在正文中间 → 不误判（只认首行）", () => {
    expect(parseGuardBlock(`正常输出\n${SENTINEL} kind=guard_denied`)).toBeNull();
  });
});

describe("guardBlockReason —— 原因文案尺子", () => {
  const t = (_key: string, def: string) => def;
  it("方案未确认给出人话原因", () => {
    expect(guardBlockReason("plan_scope_pending", t)).toContain("方案");
  });
  it("未知 kind 回退到通用拦截原因", () => {
    expect(guardBlockReason("who_knows", t)).toContain("安全规则");
  });
});

describe("computeCardActiveKey —— 被拦下要默认展开", () => {
  it("运行结束但被拦下 → 仍展开（用户得看到原因）", () => {
    expect(
      computeCardActiveKey({ hasDetails: true, loading: false, manualOpen: null, blocked: true }),
    ).toEqual(["1"]);
  });
  it("用户手动收起后不再抢状态", () => {
    expect(
      computeCardActiveKey({ hasDetails: true, loading: false, manualOpen: false, blocked: true }),
    ).toEqual([]);
  });
  it("不传 blocked → 老行为不变（完成即收起）", () => {
    expect(computeCardActiveKey({ hasDetails: true, loading: false, manualOpen: null })).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// 组件渲染
// ---------------------------------------------------------------------------

describe("EnhancedToolCallCard —— 拦截态渲染", () => {
  it("被拦下：显示已拦下 + 原因，且不出现哨兵", () => {
    render(
      <EnhancedToolCallCard
        data={toolData({
          status: "completed",
          output: `${SENTINEL} kind=plan_scope_pending\n${REASON_BODY}`,
        })}
      />,
    );
    expect(screen.getByText("已拦下")).toBeTruthy();
    expect(screen.getByText("方案还没确认，这个动作已拦下")).toBeTruthy();
    // 展开体里能看到原因原文，且机器标记不泄漏到界面
    expect(document.body.textContent).toContain("还没得到用户确认");
    expect(document.body.textContent).not.toContain("coapis:tool-blocked");
  });

  it("真实形状（块数组 JSON 串）也要认出拦截，且不把 JSON 吐给界面", () => {
    const wire = JSON.stringify([
      { type: "text", text: `${SENTINEL} kind=guard_denied\n此工具已被安全规则拦截` },
    ]);
    render(<EnhancedToolCallCard data={toolData({ status: "completed", output: wire })} />);
    expect(screen.getByText("已拦下")).toBeTruthy();
    expect(screen.getByText("安全规则拦下了这个动作")).toBeTruthy();
    expect(document.body.textContent).toContain("此工具已被安全规则拦截");
    expect(document.body.textContent).not.toContain('"type":"text"');
    expect(document.body.textContent).not.toContain("coapis:tool-blocked");
  });

  it("正常完成：不许出现拦截标记", () => {
    render(
      <EnhancedToolCallCard
        data={toolData({ status: "completed", output: "命令执行完成，退出码 0。" })}
      />,
    );
    expect(screen.queryByText("已拦下")).toBeNull();
    expect(screen.queryByText("拦下原因")).toBeNull();
    // 正常完成仍按老规矩收起，标题照常
    expect(document.body.textContent).toContain("读取文件");
  });
});
