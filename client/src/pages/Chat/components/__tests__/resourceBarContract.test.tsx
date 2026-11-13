/**
 * B0 契约锁 · 会话资源条
 * ---------------------------------------------------------------------------
 * 钉住三把尺子与三条交互红线。断言全部对着**真实渲染出来的 DOM**写
 * （先跑探针把 DOM 打出来看，再写断言），不猜类名、不猜文案：
 *  - resourceStatusOf：已删除/已失效必须赢过一切（软删行点了就是 404）
 *  - splitResourcesByRole：chip 筛的是「产出/引用」两段，不是整页
 *  - visibleRowsFor：收起态每段 GROUP_CAP 行，「其余 N 项」的 N 是真数
 *  - 红线：默认收起不铺行；死行点名字不许触发预览；无定位能力不许给定位控件
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import CoApisChatResourceBar, {
  GROUP_CAP,
  resourceStatusOf,
  splitResourcesByRole,
  TAGGED_STATUSES,
  visibleRowsFor,
} from "../CoApisChatResourceBar";
import type { ChatResourceItem } from "../../../../api/modules/chat";

let seq = 0;
function item(over: Partial<ChatResourceItem> = {}): ChatResourceItem {
  seq += 1;
  return {
    kind: "file",
    path: over.path ?? `files/文件-${seq}.txt`,
    title: over.title ?? "",
    role: over.role ?? "reference",
    exists: over.exists ?? true,
    deleted: over.deleted ?? false,
    status: over.status,
    messageId: over.messageId,
    ...over,
  };
}

function many(n: number, role: ChatResourceItem["role"]): ChatResourceItem[] {
  return Array.from({ length: n }, (_, i) =>
    item({
      path: `files/${role}-${i}.txt`,
      title: `${role}-${i}.txt`,
      role,
    }),
  );
}

function chips(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll('[role="button"]')) as HTMLElement[];
}

function chipByText(container: HTMLElement, label: string): HTMLElement {
  const el = chips(container).find((c) =>
    (c.textContent ?? "").startsWith(label),
  );
  if (!el) throw new Error(`chip 不存在: ${label}`);
  return el;
}

function openGroup(container: HTMLElement, label: string) {
  fireEvent.click(chipByText(container, label));
}

// ---------------------------------------------------------------------------
// 尺子 1：状态
// ---------------------------------------------------------------------------

describe("resourceStatusOf —— 状态尺子", () => {
  it("已删除赢过一切：软删行不许显示成可预览", () => {
    expect(resourceStatusOf({ deleted: true, exists: true, status: "active" } as ChatResourceItem)).toBe(
      "deleted",
    );
  });

  it("status=deleted 也算已删除（后端两条口径都得认）", () => {
    expect(resourceStatusOf({ deleted: false, status: "deleted" } as ChatResourceItem)).toBe(
      "deleted",
    );
  });

  it("file 且 exists=false → missing（盘上没文件）", () => {
    expect(resourceStatusOf({ kind: "file", exists: false } as ChatResourceItem)).toBe(
      "missing",
    );
  });

  it("非 file 的缺失行不判 missing（URL/KB 没有「盘上缺失」这回事）", () => {
    expect(
      resourceStatusOf({ kind: "web", exists: false, status: "active" } as ChatResourceItem),
    ).toBe("active");
  });

  it("其余状态透传", () => {
    expect(resourceStatusOf({ status: "active" } as ChatResourceItem)).toBe("active");
    expect(resourceStatusOf({ status: "archived" } as ChatResourceItem)).toBe("archived");
  });

  it("无状态默认 draft（登记了还没产出的中间态）", () => {
    expect(resourceStatusOf({} as ChatResourceItem)).toBe("draft");
  });

  it("失效状态集合锁死为 archived/deleted/missing（新状态要显式进表）", () => {
    expect([...TAGGED_STATUSES].sort()).toEqual(["archived", "deleted", "missing"]);
  });

  it("优先级链条：deleted > missing > 透传", () => {
    expect(
      resourceStatusOf({ deleted: true, exists: false, kind: "file" } as ChatResourceItem),
    ).toBe("deleted");
    expect(resourceStatusOf({ deleted: false, exists: false, kind: "file" } as ChatResourceItem)).toBe(
      "missing",
    );
    expect(resourceStatusOf({ deleted: false, exists: true } as ChatResourceItem)).toBe("draft");
  });
});

// ---------------------------------------------------------------------------
// 尺子 2：产出/引用二分
// ---------------------------------------------------------------------------

describe("splitResourcesByRole —— 产出/引用二分", () => {
  it("producer 与 export 都算产出", () => {
    const { produced } = splitResourcesByRole([
      item({ path: "files/a.txt", title: "a.txt", role: "producer" }),
      item({ path: "files/b.txt", title: "b.txt", role: "export" }),
    ]);
    expect(produced.map((i) => i.title)).toEqual(["a.txt", "b.txt"]);
  });

  it("reference / attachment 算引用", () => {
    const { referenced } = splitResourcesByRole([
      item({ path: "files/r.txt", title: "r.txt", role: "reference" }),
      item({ path: "files/a.png", title: "a.png", role: "attachment" }),
    ]);
    expect(referenced.map((i) => i.title)).toEqual(["r.txt", "a.png"]);
  });

  it("未标 role 的行落引用侧（不许凭空消失）", () => {
    const { produced, referenced } = splitResourcesByRole([
      item({ path: "files/x.txt", title: "x.txt", role: undefined }),
    ]);
    expect(produced).toHaveLength(0);
    expect(referenced).toHaveLength(1);
  });

  it("二分不吞行：产出 + 引用 = 总数", () => {
    const items = [
      item({ role: "producer" }),
      item({ role: "export" }),
      item({ role: "reference" }),
      item({ role: undefined }),
    ];
    const { produced, referenced } = splitResourcesByRole(items);
    expect(produced.length + referenced.length).toBe(items.length);
  });
});

// ---------------------------------------------------------------------------
// 尺子 3：分组上限
// ---------------------------------------------------------------------------

describe("visibleRowsFor —— 分组上限", () => {
  it("收起态最多 GROUP_CAP 行", () => {
    expect(visibleRowsFor(many(30, "producer"), false)).toHaveLength(GROUP_CAP);
  });

  it("放开态显示全部行", () => {
    expect(visibleRowsFor(many(30, "producer"), true)).toHaveLength(30);
  });

  it("不足上限原样返回（不出现「其余 0 项」这种空控件）", () => {
    expect(visibleRowsFor(many(3, "producer"), false)).toHaveLength(3);
  });

  it("空段返回空（渲染侧据此不渲染该段）", () => {
    expect(visibleRowsFor([], false)).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// 渲染与交互
// ---------------------------------------------------------------------------

describe("CoApisChatResourceBar —— 折叠与筛选", () => {
  it("默认收起：只出标题与 chip，不铺资源行", () => {
    const { container } = render(<CoApisChatResourceBar items={many(5, "reference")} />);
    expect(screen.getByText("本轮资源")).toBeInTheDocument();
    expect(container.querySelectorAll("[class*=row]").length).toBe(0);
  });

  it("chip 上带计数", () => {
    const { container } = render(
      <CoApisChatResourceBar items={[...many(3, "reference"), ...many(2, "producer")]} />,
    );
    expect(chipByText(container, "引用").textContent).toContain("3");
    expect(chipByText(container, "产出").textContent).toContain("2");
  });

  it("点「引用」只展开引用段，产出段仍收起", () => {
    const { container } = render(
      <CoApisChatResourceBar
        items={[
          item({ path: "files/ref-keep.txt", title: "ref-keep.txt", role: "reference" }),
          item({ path: "files/prod-hidden.txt", title: "prod-hidden.txt", role: "producer" }),
        ]}
      />,
    );
    openGroup(container, "引用");
    expect(screen.getByText("ref-keep.txt")).toBeInTheDocument();
    expect(screen.queryByText("prod-hidden.txt")).not.toBeInTheDocument();
  });

  it("点「产出」只展开产出段", () => {
    const { container } = render(
      <CoApisChatResourceBar
        items={[
          item({ path: "files/ref-hidden.txt", title: "ref-hidden.txt", role: "reference" }),
          item({ path: "files/prod-keep.txt", title: "prod-keep.txt", role: "producer" }),
        ]}
      />,
    );
    openGroup(container, "产出");
    expect(screen.getByText("prod-keep.txt")).toBeInTheDocument();
    expect(screen.queryByText("ref-hidden.txt")).not.toBeInTheDocument();
  });

  it("再点一次 chip 收起该组（chip 是开关，不是单向门）", () => {
    const { container } = render(<CoApisChatResourceBar items={many(2, "reference")} />);
    openGroup(container, "引用");
    expect(screen.getByText("reference-0.txt")).toBeInTheDocument();
    openGroup(container, "引用");
    expect(screen.queryByText("reference-0.txt")).not.toBeInTheDocument();
  });

  it("超过上限给「其余 N 项」，N 是真数（11 项 → 其余 3 项）", () => {
    const { container } = render(<CoApisChatResourceBar items={many(11, "reference")} />);
    openGroup(container, "引用");
    expect(screen.getByText("其余 3 项")).toBeInTheDocument();
    expect(container.querySelectorAll("[class*=row]").length).toBe(GROUP_CAP);
  });

  it("点「其余 3 项」后全部行出现且该控件消失", () => {
    const { container } = render(<CoApisChatResourceBar items={many(11, "reference")} />);
    openGroup(container, "引用");
    fireEvent.click(screen.getByText("其余 3 项"));
    expect(container.querySelectorAll("[class*=row]").length).toBe(11);
    expect(screen.queryByText("其余 3 项")).not.toBeInTheDocument();
  });

  it("恰好等于上限时不给「其余」控件", () => {
    const { container } = render(<CoApisChatResourceBar items={many(GROUP_CAP, "reference")} />);
    openGroup(container, "引用");
    expect(screen.queryByText(/其余/)).not.toBeInTheDocument();
    expect(container.querySelectorAll("[class*=row]").length).toBe(GROUP_CAP);
  });

  it("计数为 0 的段不出 chip（空段不许给可点控件）", () => {
    const { container } = render(<CoApisChatResourceBar items={many(2, "reference")} />);
    expect(chipByText(container, "引用")).toBeInTheDocument();
    expect(chips(container)).toHaveLength(1);
  });

  it("空列表整条不渲染（空壳条是噪音）", () => {
    const { container } = render(<CoApisChatResourceBar items={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("收起态不出现「其余」控件（没铺行就不该有展开控件）", () => {
    render(<CoApisChatResourceBar items={many(20, "reference")} />);
    expect(screen.queryByText(/其余/)).not.toBeInTheDocument();
  });

  it("活行点名字触发预览，并带上定位三件套（path/name/source）", () => {
    const onPreview = vi.fn();
    const { container } = render(
      <CoApisChatResourceBar
        items={[item({ path: "files/live.txt", title: "live.txt", role: "producer" })]}
        onPreview={onPreview}
      />,
    );
    openGroup(container, "产出");
    fireEvent.click(screen.getByText("live.txt"));
    expect(onPreview).toHaveBeenCalledTimes(1);
    const req = onPreview.mock.calls[0][0] as { path: string; name: string; source: string };
    expect(req.path).toBe("files/live.txt");
    expect(req.source).toBe("produced");
    expect(req.name).toContain("live.txt");
  });

  it("死行（已删除）点名字不触发预览——点了就是 404", () => {
    const onPreview = vi.fn();
    const { container } = render(
      <CoApisChatResourceBar
        items={[item({ path: "files/dead.txt", title: "dead.txt", role: "producer", deleted: true })]}
        onPreview={onPreview}
      />,
    );
    openGroup(container, "产出");
    fireEvent.click(screen.getByText("dead.txt"));
    expect(onPreview).not.toHaveBeenCalled();
  });

  it("盘上缺失的行（missing）点名字也不触发预览", () => {
    const onPreview = vi.fn();
    const { container } = render(
      <CoApisChatResourceBar
        items={[item({ path: "files/ghost.txt", title: "ghost.txt", role: "producer", exists: false })]}
        onPreview={onPreview}
      />,
    );
    openGroup(container, "产出");
    fireEvent.click(screen.getByText("ghost.txt"));
    expect(onPreview).not.toHaveBeenCalled();
  });

  it("死行带 rowDead 标记（样式与逻辑用同一把状态尺子）", () => {
    const { container } = render(
      <CoApisChatResourceBar
        items={[
          item({ path: "files/dead.txt", title: "dead.txt", deleted: true }),
          item({ path: "files/live.txt", title: "live.txt" }),
        ]}
      />,
    );
    openGroup(container, "引用");
    const dead = container.querySelector('[title="files/dead.txt"]');
    const live = container.querySelector('[title="files/live.txt"]');
    expect(dead?.className).toContain("rowDead");
    expect(live?.className).not.toContain("rowDead");
  });

  it("无定位回调时不给定位控件（灰控件是噪音）", () => {
    const { container } = render(
      <CoApisChatResourceBar
        items={[item({ path: "files/live.txt", title: "live.txt", role: "producer", messageId: "m-1" })]}
        onLocate={undefined}
      />,
    );
    openGroup(container, "产出");
    expect(container.querySelector(".anticon-aim")).not.toBeInTheDocument();
  });

  it("有定位回调 + 有 messageId 时给定位控件并回传 messageId", () => {
    const onLocate = vi.fn();
    const { container } = render(
      <CoApisChatResourceBar
        items={[item({ path: "files/live.txt", title: "live.txt", role: "producer", messageId: "m-42" })]}
        onLocate={onLocate}
      />,
    );
    openGroup(container, "产出");
    const aim = container.querySelector(".anticon-aim") as HTMLElement;
    expect(aim).toBeInTheDocument();
    fireEvent.click(aim);
    expect(onLocate).toHaveBeenCalledTimes(1);
    expect(onLocate.mock.calls[0][0]).toBe("m-42");
  });

  it("引用侧行不给定位控件（引用行没有产出消息可定位）", () => {
    const onLocate = vi.fn();
    const { container } = render(
      <CoApisChatResourceBar
        items={[item({ path: "files/ref.txt", title: "ref.txt", role: "reference", messageId: "m-9" })]}
        onLocate={onLocate}
      />,
    );
    openGroup(container, "引用");
    expect(container.querySelector(".anticon-aim")).not.toBeInTheDocument();
  });
});
