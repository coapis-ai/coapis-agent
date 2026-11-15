/**
 * 治理视图面板测试（GovernancePanel）
 *
 * 为什么要这么mock：三个端点的响应形状是**实测**来的（decisions/loop-gates、
 * governance/events、memory/context-usage），字段名、可空性、类型都得按真的来 ——
 * 特别是 `window_tokens: null`、`over_budget: null` 这种「后端故意不猜」的字段，
 * mock 里给个数字就测不到「窗口未知」这条口径了。
 *
 * 覆盖的口径（都是这次交付的承诺，逐条钉住）：
 * 1. 十门全部出现，rows=0 的门照样占一行并标「从没触发」——「从没触发」不许被当成「没数据」消失
 * 2. 未登记闸码必须显式列出
 * 3. kind 过滤切换只重取事件卡，请求参数跟着变
 * 4. `ts`（epoch 秒 float）格式化成 YYYY-MM-DD HH:mm:ss
 * 5. over_budget 标红 / 窗口未知显示「窗口未知」而不是 0%
 * 6. 单卡失败只显示该卡的 Alert + 后端 detail 原文，另外两张卡不受影响
 * 7. 前端不许把未知 kind 发给后端
 */
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import GovernancePanel from '../GovernancePanel';

const mocks = vi.hoisted(() => ({
  loopGates: vi.fn(),
  events: vi.fn(),
  contextUsage: vi.fn(),
}));

vi.mock('../../../api/modules/governance', () => ({
  governanceApi: {
    loopGates: mocks.loopGates,
    events: mocks.events,
    contextUsage: mocks.contextUsage,
  },
  GOV_DAYS_OPTIONS: [1, 7, 30],
  GOV_EVENT_KINDS: [
    'judge',
    'tool',
    'tool_denied',
    'approval',
    'memory',
    'file_version',
    'sandbox_denied',
    'config',
  ],
}));

// ── 真实形状的样例数据 ──────────────────────────────────────────

const GATES_OK = {
  days: 7,
  gates: [
    { gate: 'round_budget', label: '一轮里工具调用次数超过预算', rows: 12, hits: 12, actions: { hint: 9, block: 3 }, last_at: '2026-11-14T09:12:33+08:00' },
    { gate: 'stop_phrase', label: '模型自己喊了「我卡住了」这类话', rows: 8, hits: 8, actions: { finalize: 8 }, last_at: '2026-11-13T18:02:10+08:00' },
    { gate: 'dedup', label: '同一调用重复发了几次', rows: 5, hits: 5, actions: { block: 5 }, last_at: '2026-11-12T11:40:00+08:00' },
    { gate: 'empty_streak', label: '连着空转几轮', rows: 4, hits: 4, actions: { hint: 4 }, last_at: null },
    { gate: 'session_warn', label: '这一轮跑了多久', rows: 2, hits: 2, actions: { observe: 2 }, last_at: null },
    { gate: 'max_exec', label: '真跑了 N 次工具调用', rows: 1, hits: 1, actions: { force_text_only: 1 }, last_at: null },
    { gate: 'stagnation', label: '内容原地踏步', rows: 0, hits: 0, actions: {}, last_at: null },
    { gate: 'tool_budget', label: '工具调用条数', rows: 0, hits: 0, actions: {}, last_at: null },
    { gate: 'overflow', label: '上下文压缩', rows: 0, hits: 0, actions: {}, last_at: null },
    { gate: 'tool_dupe', label: '工具参数重复调用', rows: 0, hits: 0, actions: {}, last_at: null },
  ],
  total_rows: 32,
  total_hits: 32,
  active_gates: 6,
  unknown_gates: {},
  recent: [
    { event_id: 'evt-1', created_at: '2026-11-14T09:12:33+08:00', gate: 'round_budget', action: 'block', reason: '一轮 25 次调用超预算', chat_id: 'chat-abc', turn: 7, user_id: 'u1' },
    { event_id: 'evt-2', created_at: '2026-11-13T18:02:10+08:00', gate: 'stop_phrase', action: 'finalize', reason: '模型自述卡住', chat_id: 'chat-def', turn: 3, user_id: 'u1' },
  ],
  ledger_every: 1,
  counting_note: '闸门行是事件行，不是拦截行；「触发合计」是闸在轮次里被 evaluated 的次数，读作「闸看了多少次、拦了多少次」。',
  enabled: { round_budget: 20, stop_phrase: true, dedup: 3, empty_streak: 3, session_warn: 900, stagnation_similarity: 0.95, stagnation_force_exit: 3 },
};

const EVENTS_OK = {
  events: [
    { kind: 'judge', ts: 1731412345.678, username: 'alice', source: 'round_count', action: 'block', session: 'sess-1', target: 'tool_call', result: 'blocked', reason: '一轮工具调用 25 次超预算，judge 拦下来。这段理由后端截到 200 字，前端必须收进 Tooltip 不许撑破表格。', ref_id: 'r-1' },
    { kind: 'tool_denied', ts: 1731412400, username: null, source: 'sandbox', action: 'deny', session: null, target: 'execute_shell_command', result: 'denied', reason: null, ref_id: null },
  ],
  kinds: ['judge', 'tool_denied'],
  limit: 100,
  count: 2,
  role: 'admin',
  scope: 'global',
};

const USAGE_OK = {
  ok: true,
  scope: { user_id: null, days: 7, limit: 500 },
  cutoff_epoch: 1763000000,
  rows_scanned: 42,
  usage: {
    sessions: [
      // 可测且超预算
      { session_id: 'sess-hot', calls: 18, input_tokens_avg: 120000, input_tokens_max: 190000, window_tokens: 200000, peak_used_pct: 95.0, avg_used_pct: 60.0, mean_used_pct: 60.0, over_budget: true, models: ['claude-x'], window_source: 'model_self_reported', utilization_note: '利用率按调用自报的 prompt_tokens 占模型自报窗口换算' },
      // 窗口未知 —— 台账里没有该会话的模型记录
      { session_id: 'sess-blind', calls: 6, input_tokens_avg: 30000, input_tokens_max: 41000, window_tokens: null, peak_used_pct: null, avg_used_pct: null, mean_used_pct: null, over_budget: null, models: [], window_source: 'unknown', utilization_note: '台账里没有该会话的模型记录，窗口自报值取不到 → 利用率不可计算' },
      // 预算内
      { session_id: 'sess-ok', calls: 4, input_tokens_avg: 8000, input_tokens_max: 12000, window_tokens: 200000, peak_used_pct: 6.0, avg_used_pct: 4.0, mean_used_pct: 4.0, over_budget: false, models: ['qwen-y'], window_source: 'model_self_reported', utilization_note: null },
    ],
    session_count: 3,
    measurable_sessions: 2,
    peak_used_pct_max: 95.0,
    peak_used_pct_avg: 50.5,
    window_tokens: 200000,
    unknown_window_models: [],
    window_note: '台账行里没有窗口列；模型窗口取 provider 上报的自报值，取不到就返回未知。',
    utilization_unit: 'prompt_tokens / window_tokens',
  },
  tier: { compact_enabled: true, targets: { full: 200000, thinking: 64000, lightweight: 16000 } },
};

beforeEach(() => {
  mocks.loopGates.mockReset().mockResolvedValue(GATES_OK);
  mocks.events.mockReset().mockResolvedValue(EVENTS_OK);
  mocks.contextUsage.mockReset().mockResolvedValue(USAGE_OK);
});

describe('GovernancePanel · 卡 A 循环闸对账', () => {
  it('十门全部渲染，rows=0 的门照样占一行并标「从没触发」（零值不隐藏）', async () => {
    render(<GovernancePanel />);
    await waitFor(() => expect(screen.getByText('循环闸对账')).toBeInTheDocument());

    for (const g of GATES_OK.gates) {
      expect(screen.getByText(g.label)).toBeInTheDocument();
    }
    // 四条零值行必须逐条占位，并给出「从没触发」这个治理结论
    expect(screen.getAllByTestId('never-tag')).toHaveLength(4);
    expect(screen.getByText('tool_dupe')).toBeInTheDocument();
    // 合计与计数口径原文都要亮出来（口径是后端的，前端不改写）
    expect(screen.getByTestId('counting-note')).toHaveTextContent('闸门行是事件行');
    expect(screen.getByTestId('total-rows')).toHaveTextContent('32');
    expect(screen.getByTestId('total-hits')).toHaveTextContent('32');
    expect(screen.getByTestId('active-gates')).toHaveTextContent('6/10');
  });

  it('unknown_gates 非空时显式列出未登记闸码，不静默', async () => {
    mocks.loopGates.mockResolvedValue({
      ...GATES_OK,
      unknown_gates: { legacy_gate: 3, '': 1 },
    });
    render(<GovernancePanel />);
    await waitFor(() => expect(screen.getByTestId('unknown-gates')).toBeInTheDocument());
    const alert = screen.getByTestId('unknown-gates');
    expect(alert).toHaveTextContent('未登记闸码');
    expect(within(alert).getByText('legacy_gate×3')).toBeInTheDocument();
    expect(screen.getByText('循环闸对账')).toBeInTheDocument();
  });

  it('阈值全为「不拦」时显式提示循环闸当前未启用', async () => {
    mocks.loopGates.mockResolvedValue({
      ...GATES_OK,
      enabled: { round_budget: 0, stop_phrase: false, dedup: 0, empty_streak: 0, session_warn: 0, stagnation_similarity: 0, stagnation_force_exit: 0 },
    });
    render(<GovernancePanel />);
    await waitFor(() => expect(screen.getByText('循环闸当前未启用')).toBeInTheDocument());
  });
});

describe('GovernancePanel · 卡 B 治理事件', () => {
  it('ts 是 epoch 秒（float），按 YYYY-MM-DD HH:mm:ss 本地时间格式化', async () => {
    render(<GovernancePanel />);
    await waitFor(() => expect(screen.getByText('治理事件')).toBeInTheDocument());
    const stamps = await screen.findAllByTestId('event-time');
    const p = (n: number) => String(n).padStart(2, '0');
    const d = new Date(1731412345.678 * 1000);
    const want = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
    expect(stamps[0].textContent).toBe(want);
    expect(stamps[0].textContent).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/);
  });

  it('切换 kind 过滤后只重取事件卡，请求参数跟着变', async () => {
    const { container } = render(<GovernancePanel />);
    await waitFor(() => expect(mocks.events).toHaveBeenCalledWith('', 100));
    expect(mocks.loopGates).toHaveBeenCalledTimes(1);

    // Segmented 的真控件是 label 里的 radio input，点它才会触发 onChange
    const seg = Array.from(container.querySelectorAll('.ant-segmented')).pop() as HTMLElement;
    const input = Array.from(seg.querySelectorAll('input[type="radio"]'))[2] as HTMLInputElement;
    fireEvent.click(input);

    await waitFor(() => expect(mocks.events).toHaveBeenCalledWith('tool', 100));
    // 卡 A / 卡 C 不受 kind 过滤牵连：各只取数一次
    expect(mocks.loopGates).toHaveBeenCalledTimes(1);
    expect(mocks.contextUsage).toHaveBeenCalledTimes(1);
  });
});

describe('GovernancePanel · 卡 C 上下文消耗对账', () => {
  it('over_budget 标红，窗口未知的会话显示「窗口未知」而不是 0%（不编数）', async () => {
    const { container } = render(<GovernancePanel />);
    await waitFor(() => expect(screen.getByText('上下文消耗对账')).toBeInTheDocument());

    const over = await screen.findByTestId('over-budget');
    expect(over).toHaveTextContent('超预算');
    expect(over).toHaveClass('ant-typography-danger');

    const unknown = screen.getAllByTestId('window-unknown');
    // 窗口未知的会话：窗口格与峰值格都是未知，整行不许出现 0%
    expect(unknown.length).toBeGreaterThanOrEqual(1);
    const blindRow = Array.from(container.querySelectorAll('tbody tr')).find((tr) =>
      tr.textContent?.includes('sess-blind'),
    ) as HTMLElement;
    expect(within(blindRow as HTMLElement).getByTestId('window-unknown')).toBeInTheDocument();
    expect(within(blindRow as HTMLElement).getByTestId('peak-unknown')).toHaveTextContent('窗口未知');
    expect(within(blindRow as HTMLElement).getByText('不可判')).toBeInTheDocument();
    expect(blindRow.textContent).not.toContain('0%');

    // 可测会话给出色档百分比（sess-hot 峰值 95%）
    const hotRow = Array.from(container.querySelectorAll('tbody tr')).find((tr) =>
      tr.textContent?.includes('sess-hot'),
    ) as HTMLElement;
    expect(within(hotRow as HTMLElement).getByTestId('peak-pct')).toHaveTextContent('95.0%');
    expect(within(hotRow as HTMLElement).getByTestId('over-budget')).toHaveTextContent('超预算');
    expect(screen.getByTestId('tier-full')).toBeInTheDocument();
    expect(screen.getByTestId('compact-flag')).toHaveTextContent('压缩已开启');
  });

  it('台账里没有可测记录时明确写出来，不给空白表格', async () => {
    mocks.contextUsage.mockResolvedValue({
      ok: true,
      scope: { user_id: null, days: 7, limit: 500 },
      cutoff_epoch: 1763000000,
      rows_scanned: 0,
      usage: { sessions: [], session_count: 0, measurable_sessions: 0 },
      tier: { compact_enabled: false, targets: {} },
    });
    render(<GovernancePanel />);
    await waitFor(() => expect(screen.getByText('台账里没有可测的调用记录')).toBeInTheDocument());
    expect(screen.getByTestId('compact-flag')).toHaveTextContent('压缩未开启');
  });
});

describe('GovernancePanel · 失败隔离与前端 kind 词表', () => {
  it('单卡失败只在该卡显示 Alert + 后端 detail 原文，另外两张卡照常出数', async () => {
    // 后端 404/503 的 detail 写着要设哪个环境变量 —— 那句话必须原样到用户眼前
    mocks.events.mockRejectedValue(
      new Error('Not Found: 治理事件视图未启用，需要设置 COAPIS_GOVERNANCE_EVENTS_DB'),
    );
    render(<GovernancePanel />);
    // detail 原文是一整句（含环境变量名），所以用正则匹配子串
    await waitFor(() =>
      expect(
        screen.getByText(/COAPIS_GOVERNANCE_EVENTS_DB/),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText('取数失败')).toBeInTheDocument();
    // 隔离性：卡 A / 卡 C 正常渲染，卡 B 的标题也还在（失败的是内容，不是整张卡）
    expect(screen.getByText('循环闸对账')).toBeInTheDocument();
    expect(screen.getByText('上下文消耗对账')).toBeInTheDocument();
    expect(screen.getAllByText('治理事件').length).toBeGreaterThan(0);
    expect(screen.getByText('一轮里工具调用次数超过预算')).toBeInTheDocument();
    expect(screen.getAllByTestId('peak-pct').length).toBeGreaterThan(0);
  });

  it('未知 kind 在前端就拦下，不发请求（后端对未知 kind 返回 400）', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => '{"events":[]}',
      json: async () => ({ events: [] }),
      // request helper 会读 content-type 判断是否 JSON
      headers: { get: (k: string) => (k.toLowerCase() === 'content-type' ? 'application/json' : null) },
    } as unknown as Response);
    vi.stubGlobal('fetch', fetchMock);
    try {
      const real = await vi.importActual<typeof import('../../../api/modules/governance')>(
        '../../../api/modules/governance',
      );
      // 未知 kind：本地抛，且一次请求都不发
      expect(() => real.governanceApi.events('definitely_not_a_kind')).toThrow(/Unknown event kind/);
      expect(fetchMock).not.toHaveBeenCalled();
      // 空 kind = 全部：合法，且查询串里整个 kind 参数都不出现
      await real.governanceApi.events('', 100);
      const url = String(fetchMock.mock.calls[0][0]);
      expect(url).toContain('/api/governance/events');
      expect(url).not.toContain('kind=');
      // 合法 kind：正常带上 kind
      await real.governanceApi.events('tool_denied', 50);
      expect(String(fetchMock.mock.calls[1][0])).toContain('kind=tool_denied');
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
