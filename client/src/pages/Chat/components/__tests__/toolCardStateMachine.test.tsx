/**
 * B0 契约锁 · 工具卡片状态机
 * ---------------------------------------------------------------------------
 * 钉住小蜜蜂 2026-11-12 的拍板：**卡片默认收起，只有运行中临时展开，完成即收起；
 * 用户手动开合之后，机器不再抢状态。**
 *
 * 为什么锁这条：这条规则此前只靠肉眼验收，同一个组件先后出现过「默认全展开」
 * 「完成不收」「用户点开又被抢回」三种行为，修了三轮都没有测试兜底。
 *
 * 数据形状按 SDK 约定：content[0].data 是调用信息（name/arguments），
 * content[1].data 是执行结果（output）—— 写错下标会静默测不到内容。
 *
 * 两层尺子分开测：
 *  - computeCardActiveKey（纯函数）：规则本体。
 *  - 组件渲染：证明组件确实走这条尺子，而不是在组件里又写了一份等价表达式。
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import EnhancedToolCallCard, {
  computeCardActiveKey,
} from "../EnhancedToolCallCard";
import {
  TOOL_RUNNING_LABELS_ZH,
  toolRunningLabel,
  toolStepLabel,
} from "../toolLabels";
import { ChatDisplayConfigContext } from "../SimplifiedResponseCard";
import {
  DEFAULT_CHAT_DISPLAY_CONFIG,
  type ChatDisplayConfig,
} from "../../types";

const OUTPUT_MARK = "OUTPUT-PAYLOAD-SHALL-STAY-COLLAPSED";

type ToolData = Parameters<typeof EnhancedToolCallCard>[0]["data"];

function toolData(opts: {
  status?: string;
  name?: string;
  args?: string | null;
  output?: string | null;
}): ToolData {
  return {
    status: opts.status,
    content: [
      {
        data: {
          name: opts.name ?? "read_file",
          arguments: opts.args ?? '{"path":"a.txt"}',
        },
      },
      { data: { output: opts.output ?? OUTPUT_MARK } },
    ],
  };
}

// ---------------------------------------------------------------------------
// 纯函数尺子
// ---------------------------------------------------------------------------

describe("computeCardActiveKey —— 展开态尺子", () => {
  it("运行中 + 有明细 → 展开", () => {
    expect(
      computeCardActiveKey({ hasDetails: true, loading: true, manualOpen: null }),
    ).toEqual(["1"]);
  });

  it("完成 + 有明细 → 收起（运行结束必须收）", () => {
    expect(
      computeCardActiveKey({ hasDetails: true, loading: false, manualOpen: null }),
    ).toEqual([]);
  });

  it("运行中但没有明细 → 收起（没东西可展开）", () => {
    expect(
      computeCardActiveKey({ hasDetails: false, loading: true, manualOpen: null }),
    ).toEqual([]);
  });

  it("用户手动展开过 → 完成后仍尊重用户选择", () => {
    expect(
      computeCardActiveKey({ hasDetails: true, loading: false, manualOpen: true }),
    ).toEqual(["1"]);
  });

  it("用户手动收起过 → 运行中也不给他弹开", () => {
    expect(
      computeCardActiveKey({ hasDetails: true, loading: true, manualOpen: false }),
    ).toEqual([]);
  });

  it("manualOpen 优先于 loading（短路方向写反就要红）", () => {
    expect(
      computeCardActiveKey({ hasDetails: true, loading: true, manualOpen: false }),
    ).toEqual([]);
    expect(
      computeCardActiveKey({ hasDetails: true, loading: false, manualOpen: true }),
    ).toEqual(["1"]);
  });

  it("无明细时用户的展开意图无效（不渲染空面板）", () => {
    expect(
      computeCardActiveKey({ hasDetails: false, loading: false, manualOpen: true }),
    ).toEqual([]);
  });

  it("manualOpen=null 表示用户从没动过，此时完全跟随运行状态", () => {
    expect(computeCardActiveKey({ hasDetails: true, loading: true, manualOpen: null })).toEqual(["1"]);
    expect(computeCardActiveKey({ hasDetails: true, loading: false, manualOpen: null })).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// 组件渲染
// ---------------------------------------------------------------------------

function renderCard(data: ToolData, config?: Partial<ChatDisplayConfig>) {
  const value: ChatDisplayConfig = { ...DEFAULT_CHAT_DISPLAY_CONFIG, ...config };
  return render(
    <ChatDisplayConfigContext.Provider value={value}>
      <EnhancedToolCallCard data={data} />
    </ChatDisplayConfigContext.Provider>,
  );
}

/**
 * 收起判据（探针实测 2026-11-13）：
 * antd v5 Collapse 收起时内容节点**留在 DOM**，带 `ant-collapse-content-inactive`；
 * 从未展开过则整段内容不存在。jsdom 里动画不会自然结束，所以不能用
 * "内容不在 DOM" 判收起 —— 那是「从未展开」的判据，两者必须分开。
 */
function collapseState(container: HTMLElement): "none" | "open" | "closed" {
  const el = container.querySelector(".ant-collapse-content");
  if (!el) return "none";
  return el.className.includes("ant-collapse-content-inactive")
    ? "closed"
    : "open";
}

describe("EnhancedToolCallCard —— 状态机落到渲染", () => {
  it("运行中：明细展开可见", () => {
    const { container } = renderCard(toolData({ status: "in_progress" }));
    expect(collapseState(container)).toBe("open");
    expect(screen.getByText(OUTPUT_MARK)).toBeInTheDocument();
  });

  it("完成：明细从未展开过 → 内容根本不进 DOM", () => {
    const { container } = renderCard(toolData({ status: "completed" }));
    expect(collapseState(container)).toBe("none");
    expect(screen.queryByText(OUTPUT_MARK)).not.toBeInTheDocument();
  });

  it("失败：收起，不因报错自动展开吓人", () => {
    const { container } = renderCard(toolData({ status: "failed" }));
    expect(collapseState(container)).toBe("none");
    expect(screen.queryByText(OUTPUT_MARK)).not.toBeInTheDocument();
    expect(screen.getByText("失败")).toBeInTheDocument();
  });

  it("取消：收起", () => {
    const { container } = renderCard(toolData({ status: "canceled" }));
    expect(collapseState(container)).toBe("none");
    expect(screen.queryByText(OUTPUT_MARK)).not.toBeInTheDocument();
    expect(screen.getByText("已中止")).toBeInTheDocument();
  });

  it("无输入无输出：只剩一条标题，明细区不存在（空壳卡不给展开入口）", () => {
    const { container } = renderCard(
      toolData({ status: "completed", args: null, output: null }),
    );
    expect(collapseState(container)).toBe("none");
    expect(screen.getByText("读取文件")).toBeInTheDocument();
  });

  it("收起态点击标题可展开；再点一次收起（用户能夺回控制权）", () => {
    const { container } = renderCard(toolData({ status: "completed" }));
    expect(collapseState(container)).toBe("none");
    fireEvent.click(screen.getByText("读取文件"));
    expect(collapseState(container)).toBe("open");
    fireEvent.click(screen.getByText("读取文件"));
    expect(collapseState(container)).toBe("closed");
  });

  it("运行中展开 → 运行结束自动收起（不留永远张开的卡）", () => {
    const { container, rerender } = renderCard(toolData({ status: "in_progress" }));
    expect(collapseState(container)).toBe("open");
    rerender(
      <ChatDisplayConfigContext.Provider value={DEFAULT_CHAT_DISPLAY_CONFIG}>
        <EnhancedToolCallCard data={toolData({ status: "completed" })} />
      </ChatDisplayConfigContext.Provider>,
    );
    expect(collapseState(container)).toBe("closed");
  });

  it("标题跟随语言：zh 用中文动词，不吐 read_file 原文", () => {
    renderCard(toolData({ status: "completed" }));
    expect(screen.getByText("读取文件")).toBeInTheDocument();
    expect(screen.queryByText("read_file")).not.toBeInTheDocument();
  });

  it("「隐藏细节」开关开启时，运行中也不展开明细", () => {
    const { container } = renderCard(toolData({ status: "in_progress" }), {
      hideDetails: true,
    });
    expect(collapseState(container)).toBe("none");
    expect(screen.queryByText(OUTPUT_MARK)).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// 工具名中文动词映射
// ---------------------------------------------------------------------------

describe("toolLabels —— 工具名中文动词（单一映射表）", () => {
  it("已登记的工具给出中文动词", () => {
    expect(toolStepLabel("read_file", "zh")).toBe("读取文件");
    expect(toolStepLabel("execute_shell_command", "zh")).toBe("执行命令");
  });

  it("未登记的工具走「工具 · 原名」兜底（不编造动词，也不吐空串）", () => {
    expect(toolStepLabel("brand_new_tool", "zh")).toBe("工具 · brand_new_tool");
  });

  it("空工具名返回空串，不抛异常", () => {
    expect(toolStepLabel("", "zh")).toBe("");
  });

  it("非中文环境不做硬译（交回 SDK 原文，避免中英混搭）", () => {
    expect(toolStepLabel("read_file", "en")).toBe("read_file");
    expect(toolRunningLabel("read_file", "en")).toBe("");
  });

  it("进行态文案只给已登记工具，未登记退回空串由调用方兜底", () => {
    expect(toolRunningLabel("read_file", "zh")).toBe("读取中");
    expect(toolRunningLabel("brand_new_tool", "zh")).toBe("");
  });

  it("两张表同源：进行态里的每个工具都能取到完成态中文动词", () => {
    // 不同源会出现「进行态有中文、完成态吐英文」的割裂显示
    for (const name of Object.keys(TOOL_RUNNING_LABELS_ZH)) {
      const label = toolStepLabel(name, "zh");
      expect(label).not.toBe("");
      expect(label).not.toBe(name);
    }
  });
});
