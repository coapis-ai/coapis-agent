// 聊天资源展示尺子的契约测试。
//
// 钉四件事（liuliangxu 2026-11-13 拍板：图标按类别出、来源分四类做、
// 左栏与聊天同一形态做成一个资源卡片、写入渠道列不做=后端零改动）：
//   1) 图标按类别出：同类别必取到图标组件，Word / Excel / PDF / 网页 / 知识库
//      形状互不相同（不再整屏一个文件图标）；
//   2) 来源四类判定：产出 / 知识库 / 网页 / 引用，只看台账 role + kind；
//   3) 聊天里的本轮资源条、左栏的整会话卡片、资源抽屉三处同源：
//      同一条资源在三处的图标形状与来源标签一致；
//   4) 左栏「会话资源」**一行控制条**（2026-11-21 用户第 2 次纠正定稿）：
//      「会话资源 N · 引用 N ▾ · 产出 N ▾ · 查看全部」同一行，引用/产出是行上
//      两枚下拉开关，可分别展开、分别收起；底部「会话全部资源」大按钮判废、
//      「引用」「产出」另起一行的组头形态同样不许回流。
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CATEGORY_ICON } from "../resourceCategory";
import type { ResourceCategory } from "../resourceCategory";
import {
  ICON_KEYS,
  SOURCE_COLOR,
  SOURCE_LABEL_KEY,
  categoryIconOf,
  sourceOf,
} from "../resourceDisplay";
import CoApisChatResourceBar from "../CoApisChatResourceBar";
import { ChatSessionResourcesInline } from "../ChatSessionResources/Inline";
import type { ChatResourceItem } from "../../../../api/modules/chat";

const listChatResources = vi.fn();
const getChatResourcesShared = vi.fn();

vi.mock("../../../../api", () => ({
  apiClient: {
    listChatResources: (...args: unknown[]) => listChatResources(...args),
  },
  DEFAULT_RESOURCE_LIMIT: 50,
  DEFAULT_PAGE_SIZE: 50,
}));

vi.mock("../../../../stores", () => ({
  useChatResourceLedger: () => ({ resources: [], loading: false }),
  usePreviewResource: () => vi.fn(),
}));

// 预览/下载是网络动作，测试里只留签名
vi.mock("../../../../utils/webPreview", () => ({
  toLedgerRelPath: (path: string) => path,
  getPreviewKind: () => "md",
  convertTargetsFor: () => [],
  canInlinePreview: () => true,
  downloadFile: vi.fn(),
  previewFile: vi.fn(),
}));

// 左栏取数走共享缓存（同一会话只拉一次）；其余工具用真实实现
vi.mock("../useChatResourceLedger", async () => {
  const actual = await import("../useChatResourceLedger");
  return {
    ...actual,
    getChatResourcesShared: (...args: unknown[]) =>
      getChatResourcesShared(...args),
    invalidateChatResourcesShared: vi.fn(),
  };
});

const payload = (items: ChatResourceItem[]) => ({
  items,
  total: items.length,
  limit: 50,
  offset: 0,
  has_more: false,
});

function item(
  over: Partial<ChatResourceItem> &
    Pick<ChatResourceItem, "kind" | "role" | "path">,
): ChatResourceItem {
  return {
    chat_id: "c1",
    turn_id: "t1",
    source: "test",
    name: over.path.split("/").pop(),
    size_bytes: 1024,
    produced_at: 1,
    mime: "text/plain",
    status: "present",
    ...over,
  } as ChatResourceItem;
}

// 九条覆盖：文档/表格/幻灯片/PDF/网页/知识库/工具/数据源/导出件
const SAMPLES = [
  item({
    resource_key: "f1",
    kind: "file",
    role: "producer",
    path: "out/report.docx",
  }),
  item({
    resource_key: "f2",
    kind: "file",
    role: "reference",
    path: "in/data.xlsx",
  }),
  item({
    resource_key: "f3",
    kind: "file",
    role: "reference",
    path: "in/plan.pptx",
  }),
  item({
    resource_key: "f4",
    kind: "file",
    role: "reference",
    path: "in/spec.pdf",
  }),
  item({
    resource_key: "w1",
    kind: "web",
    role: "reference",
    path: "https://example.com/a",
  }),
  item({
    resource_key: "k1",
    kind: "kb",
    role: "reference",
    path: "kb/doc1.md",
  }),
  item({
    resource_key: "m1",
    kind: "mcp",
    role: "reference",
    path: "mcp/tool",
  }),
  item({ resource_key: "d1", kind: "db", role: "reference", path: "db/table" }),
  item({
    resource_key: "x1",
    kind: "file",
    role: "export",
    path: "out/export.zip",
  }),
];

describe("图标尺子：类别 → 形状", () => {
  it("每个类别都取得到图标组件（将来新增类别不会静默掉图标）", () => {
    const categories = Object.keys(CATEGORY_ICON) as ResourceCategory[];
    for (const category of categories) {
      const key = CATEGORY_ICON[category];
      expect(ICON_KEYS, `类别 ${category} 的图标 key=${key}`).toContain(key);
    }
  });

  it("Word / Excel / PPT / PDF / 网页 / 知识库 形状互不相同", () => {
    const shapeOf = (it: ChatResourceItem) => {
      const { container } = render(<>{categoryIconOf(it)}</>);
      const anticon = container.querySelector(".anticon");
      return anticon ? Array.from(anticon.classList).join(" ") : "";
    };
    const shapes = [
      SAMPLES[0],
      SAMPLES[1],
      SAMPLES[2],
      SAMPLES[3],
      SAMPLES[4],
      SAMPLES[5],
    ].map(shapeOf);
    expect(
      new Set(shapes).size,
      `六类应有六种形状，实际：${shapes.join(" | ")}`,
    ).toBe(6);
  });

  it("文档类同色，知识库与网页不同色", () => {
    const colorOf = (it: ChatResourceItem) => {
      const { container } = render(<>{categoryIconOf(it)}</>);
      return (container.firstChild as HTMLElement).style.color;
    };
    expect(colorOf(SAMPLES[0])).toEqual(colorOf(SAMPLES[1]));
    expect(colorOf(SAMPLES[5])).not.toEqual(colorOf(SAMPLES[4]));
    expect(colorOf(SAMPLES[5])).not.toEqual(colorOf(SAMPLES[0]));
  });
});

describe("来源尺子：产出 / 知识库 / 网页 / 引用", () => {
  it("台账角色是产出、导出件 → 产出", () => {
    expect(sourceOf(SAMPLES[0])).toBe("produced");
    expect(sourceOf(SAMPLES[8])).toBe("produced");
  });

  it("引用件按类型分：知识库 / 网页 / 其余算引用", () => {
    expect(sourceOf(SAMPLES[5])).toBe("kb");
    expect(sourceOf(SAMPLES[4])).toBe("web");
    expect(sourceOf(SAMPLES[1])).toBe("reference");
    expect(sourceOf(SAMPLES[6])).toBe("reference");
    expect(sourceOf(SAMPLES[7])).toBe("reference");
  });

  it("四类都有独立词条 key 与独立配色", () => {
    expect(new Set(Object.values(SOURCE_LABEL_KEY)).size).toBe(4);
    expect(new Set(Object.values(SOURCE_COLOR)).size).toBe(4);
  });
});

describe("聊天里的本轮资源条：图标按类别、来源四类", () => {
  // 资源条默认收起（产品 2026-11-07 定稿），测试先把两组点开再看行
  const renderExpandedBar = () => {
    const view = render(<CoApisChatResourceBar items={SAMPLES} />);
    for (const label of ["产出", "引用"]) {
      fireEvent.click(screen.getByText(label, { selector: "[role='button']" }));
    }
    return view.container;
  };

  it("图标按细类出：表格 / 网页 / 知识库 各有各的形（不再整屏一个文件图标）", () => {
    const container = renderExpandedBar();
    for (const cls of [
      ".anticon-file-excel",
      ".anticon-global",
      ".anticon-book",
    ]) {
      expect(
        container.querySelector(cls),
        `应出现图标 ${cls}`,
      ).toBeInTheDocument();
    }
    // 本轮条里不该再有「所有文件共用一个文件图标」的情况
    expect(container.querySelectorAll(".anticon-file-text").length).toBe(0);
  });

  it("来源标签四类都出现（引用组里能分出知识库 / 网页）", () => {
    renderExpandedBar();
    for (const label of ["产出", "知识库", "网页", "引用"]) {
      expect(
        screen.getAllByText(label).length,
        `应有来源标签「${label}」`,
      ).toBeGreaterThan(0);
    }
  });
});

describe("本轮中断徽标（B1）", () => {
  const renderBar = (items: ChatResourceItem[], interrupted?: boolean) =>
    render(
      <CoApisChatResourceBar
        items={items}
        chatId="c1"
        onPreview={vi.fn()}
        interrupted={interrupted}
      />,
    );

  it("未中断时不留键：前端按「有徽标=中断」读，不猜", () => {
    const { container } = renderBar(SAMPLES, undefined);
    expect(
      container.querySelector("[data-testid='interrupted-chip']"),
    ).toBeNull();
    renderBar(SAMPLES, false);
    expect(
      container.querySelector("[data-testid='interrupted-chip']"),
    ).toBeNull();
  });

  it("中断且本轮没有产出时，徽标照样出现", () => {
    // 中断轮经常一个资源都没登记；若挂分组里会随空面板一起消失，
    // 所以实现把提示放在头部 —— 这条锁钉的就是这个选择。
    const { container } = renderBar([], true);
    const chip = container.querySelector("[data-testid='interrupted-chip']");
    expect(chip).not.toBeNull();
    expect(chip?.textContent).toContain("本轮已中断");
  });
});

describe("左栏「会话资源」一行控制条 + 引用/产出分别展开（2026-11-21 拍板）", () => {
  const renderInline = async () => {
    getChatResourcesShared.mockReset();
    getChatResourcesShared.mockResolvedValue(payload(SAMPLES));
    const onShowAll = vi.fn();
    const { container } = render(
      <ChatSessionResourcesInline
        chatId="c1"
        onPreview={vi.fn()}
        onShowAll={onShowAll}
      />,
    );
    await waitFor(() => expect(screen.getByText("report")).toBeInTheDocument());
    return { container, onShowAll };
  };

  const headsOf = (container: HTMLElement) =>
    Array.from(container.querySelectorAll("[aria-expanded]"));

  it("「会话资源」这一行同时装下 引用 / 产出 / 查看全部（用户第 2 次纠正）", async () => {
    const { container } = await renderInline();
    const bar = container.querySelector("[data-coapis-res-bar]");
    expect(bar, "应有一行控制条 [data-coapis-res-bar]").not.toBeNull();
    expect(bar!.textContent).toContain("会话资源");
    // 行内恰好三枚按钮：引用开关、产出开关、查看全部
    const buttons = bar!.querySelectorAll("button");
    expect(buttons).toHaveLength(3);
    const chips = bar!.querySelectorAll("[data-group]");
    expect(chips).toHaveLength(2);
    expect(chips[0].getAttribute("data-group")).toBe("referenced");
    expect(chips[1].getAttribute("data-group")).toBe("produced");
    expect(bar!.textContent).toContain("查看全部");
    // 列表不在控制条内部（行内只放开关，条目在下面展开）
    expect(bar!.querySelector("ul")).toBeNull();
    // 底部「会话全部资源」大按钮、以及"引用/产出另起一行"的组头都不许回流
    expect(screen.queryByText(/会话全部资源/)).toBeNull();
    expect(container.querySelector("button.showAll")).toBeNull();
    expect(
      container.querySelectorAll("[data-coapis-res-group-head]"),
    ).toHaveLength(0);
  });

  it("「查看全部」打开 L3 抽屉并把 chatId 传过去", async () => {
    const { onShowAll } = await renderInline();
    fireEvent.click(screen.getByText("查看全部"));
    expect(onShowAll).toHaveBeenCalledWith("c1");
  });

  it("恰好两个下拉开关：引用在前、产出在后，计数跟在开关上", async () => {
    const { container } = await renderInline();
    const heads = headsOf(container);
    expect(heads).toHaveLength(2);
    // SAMPLES 九条：producer + export 两条进「产出」，其余七条进「引用」
    expect(heads[0].textContent).toContain("引用");
    expect(heads[0].textContent).toContain("7");
    expect(heads[1].textContent).toContain("产出");
    expect(heads[1].textContent).toContain("2");
  });

  it("默认展开，点开关收起、再点展开（'展开后无法收缩' 的反例锁）", async () => {
    const { container } = await renderInline();
    const heads = headsOf(container);
    expect(heads[0].getAttribute("aria-expanded")).toBe("true");
    // 收起「引用」：组内七行消失，「产出」组（report/export）不受影响
    fireEvent.click(heads[0]);
    expect(heads[0].getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText("spec")).toBeNull();
    expect(screen.queryByText("doc1")).toBeNull();
    expect(screen.getByText("report")).toBeInTheDocument();
    // 再点一下恢复
    fireEvent.click(heads[0]);
    expect(heads[0].getAttribute("aria-expanded")).toBe("true");
    await waitFor(() => expect(screen.getByText("spec")).toBeInTheDocument());
  });

  it("每行带类别图标与来源标签，判定与聊天同源", async () => {
    const { container } = await renderInline();
    const tags = Array.from(container.querySelectorAll("[data-src]"));
    const got = tags.map((el) => el.getAttribute("data-src"));
    for (const want of ["produced", "kb", "web", "reference"]) {
      expect(got, `左栏应有来源标签 ${want}`).toContain(want);
    }
    expect(tags.length).toBeGreaterThanOrEqual(SAMPLES.length);
    expect(container.querySelector(".anticon-file-excel")).toBeInTheDocument();
    expect(container.querySelector(".anticon-book")).toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────
// 2026-11-21 用户拍板：单个会话的某组资源默认只渲染最近 10 条（按时间倒序），
// 列表尾部给「更多」按钮，点一次再放 10 条，以此类推 —— 不一次性铺满左栏。
// ─────────────────────────────────────────────────────────────

const many = (n: number, role: "reference" | "producer") =>
  Array.from({ length: n }, (_, i) =>
    item({
      resource_key: `${role}-${i}`,
      kind: "file" as const,
      role,
      path: `${role === "reference" ? "in" : "out"}/d${String(i).padStart(
        3,
        "0",
      )}.md`,
      // 更新时间随序号递增：倒序后最新的（d0NN 最大的）排在最上面。
      updated_at: 1000 + i,
    }),
  );

const rowsOf = (container: HTMLElement) =>
  container.querySelectorAll("[data-coapis-res-row]").length;

const moreBtn = (container: HTMLElement, key?: string) =>
  (key
    ? container.querySelector(`[data-coapis-more="${key}"]`)
    : container.querySelector(
        "[data-coapis-more]",
      )) as HTMLButtonElement | null;

describe("左栏资源：每组先给最近 10 条，点「更多」再 +10", () => {
  it("默认只渲染 10 条，其余走「更多」（25 条 → 10 条 + 还有 15 条）", async () => {
    getChatResourcesShared.mockResolvedValue(payload(many(25, "reference")));
    const { container } = render(<ChatSessionResourcesInline chatId="c1" />);
    await waitFor(() => expect(rowsOf(container)).toBe(10));
    const btn = moreBtn(container);
    expect(btn).not.toBeNull();
    // 「更多」旁边要写出还剩几条：数字在按钮的兄弟节点里。
    expect(btn?.parentElement?.textContent).toContain("15");
    // 切片取的是倒序后的前 10 条：第一行必须是最新那条。
    expect(
      (container.querySelector("[data-coapis-res-row]") as HTMLElement)
        .textContent,
    ).toContain("d024.md");
  });

  it("点「更多」逐页放：10 → 20 → 25，放完按钮消失", async () => {
    getChatResourcesShared.mockResolvedValue(payload(many(25, "reference")));
    const { container } = render(<ChatSessionResourcesInline chatId="c1" />);
    await waitFor(() => expect(rowsOf(container)).toBe(10));

    fireEvent.click(moreBtn(container) as HTMLButtonElement);
    await waitFor(() => expect(rowsOf(container)).toBe(20));
    expect(moreBtn(container)?.parentElement?.textContent).toContain("5");

    fireEvent.click(moreBtn(container) as HTMLButtonElement);
    await waitFor(() => expect(rowsOf(container)).toBe(25));
    expect(moreBtn(container)).toBeNull();
  });

  it("引用与产出各记各的页数：产出组不受引用组「更多」影响", async () => {
    getChatResourcesShared.mockResolvedValue(
      payload([...many(15, "reference"), ...many(3, "producer")]),
    );
    const { container } = render(<ChatSessionResourcesInline chatId="c1" />);
    // 只有引用组超限 → 只有一个「更多」。
    await waitFor(() =>
      expect(container.querySelectorAll("[data-coapis-more]")).toHaveLength(1),
    );
    expect(rowsOf(container)).toBe(13); // 引用 10 + 产出 3

    fireEvent.click(moreBtn(container, "referenced") as HTMLButtonElement);
    await waitFor(() => expect(rowsOf(container)).toBe(18)); // 引用 15 + 产出 3
  });
});
