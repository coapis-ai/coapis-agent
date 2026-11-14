// 聊天资源展示尺子的契约测试。
//
// 钉四件事（liuliangxu 2026-11-13 拍板：图标按类别出、来源分四类做、
// 左栏与聊天同一形态做成一个资源卡片、写入渠道列不做=后端零改动）：
//   1) 图标按类别出：同类别必取到图标组件，Word / Excel / PDF / 网页 / 知识库
//      形状互不相同（不再整屏一个文件图标）；
//   2) 来源四类判定：产出 / 知识库 / 网页 / 引用，只看台账 role + kind；
//   3) 聊天里的本轮资源条、左栏的整会话卡片、资源抽屉三处同源：
//      同一条资源在三处的图标形状与来源标签一致；
//   4) 左栏不再分「生成 / 引用」两个下拉：一个卡片平铺整会话，没有折叠开关。
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
    getChatResourcesShared: (...args: unknown[]) => getChatResourcesShared(...args),
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
  item({ resource_key: "f1", kind: "file", role: "producer", path: "out/report.docx" }),
  item({ resource_key: "f2", kind: "file", role: "reference", path: "in/data.xlsx" }),
  item({ resource_key: "f3", kind: "file", role: "reference", path: "in/plan.pptx" }),
  item({ resource_key: "f4", kind: "file", role: "reference", path: "in/spec.pdf" }),
  item({ resource_key: "w1", kind: "web", role: "reference", path: "https://example.com/a" }),
  item({ resource_key: "k1", kind: "kb", role: "reference", path: "kb/doc1.md" }),
  item({ resource_key: "m1", kind: "mcp", role: "reference", path: "mcp/tool" }),
  item({ resource_key: "d1", kind: "db", role: "reference", path: "db/table" }),
  item({ resource_key: "x1", kind: "file", role: "export", path: "out/export.zip" }),
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
    const shapes = [SAMPLES[0], SAMPLES[1], SAMPLES[2], SAMPLES[3], SAMPLES[4], SAMPLES[5]].map(shapeOf);
    expect(new Set(shapes).size, `六类应有六种形状，实际：${shapes.join(" | ")}`).toBe(6);
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
      expect(container.querySelector(cls), `应出现图标 ${cls}`).toBeInTheDocument();
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
    expect(container.querySelector("[data-testid='interrupted-chip']")).toBeNull();
    renderBar(SAMPLES, false);
    expect(container.querySelector("[data-testid='interrupted-chip']")).toBeNull();
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

describe("左栏整会话资源：一个卡片，与聊天同形态", () => {
  const renderInline = async () => {
    getChatResourcesShared.mockReset();
    getChatResourcesShared.mockResolvedValue(payload(SAMPLES));
    const { container } = render(
      <ChatSessionResourcesInline chatId="c1" onPreview={vi.fn()} onShowAll={vi.fn()} />,
    );
    await waitFor(() => expect(screen.getByText("report")).toBeInTheDocument());
    return container;
  };

  it("没有折叠开关（组头不再是展开/收起按钮）", async () => {
    const container = await renderInline();
    expect(container.querySelectorAll("[aria-expanded]")).toHaveLength(0);
  });

  it("一个卡片平铺：产出与引用同屏出现，只有一个列表", async () => {
    const container = await renderInline();
    expect(container.querySelectorAll("ul")).toHaveLength(1);
    // 产出（report.docx）与引用（表格 / PDF / 知识库文档）同屏
    for (const name of ["report", "data", "spec", "doc1"]) {
      expect(screen.getByText(name)).toBeInTheDocument();
    }
  });

  it("每行带类别图标与来源标签，判定与聊天同源", async () => {
    const container = await renderInline();
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
