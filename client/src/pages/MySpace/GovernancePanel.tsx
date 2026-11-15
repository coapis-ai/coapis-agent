/**
 * 治理视图（B4 出口验收第 2 条 · B5 治理事件可见性收尾）
 *
 * 为什么是这个面板：B4 把循环闸的触发次数按门分桶写进了台账，B5 把六类治理事件
 * 收进一张联合视图，B4c 给出逐会话的上下文消耗实测。三个端点都已上线，盘上都有数，
 * 但**看不见**——「闸门到底拦没拦」「治理事件都发生了什么」「上下文吃掉多少」
 * 这三问此前只能进容器敲 SQL。审计的东西落在页面上才算数，这里就是把它们亮出来。
 *
 * 三条取数口径（都是只读 GET，本页不写任何东西）：
 * - `GET /decisions/loop-gates`  十门分桶（零值补齐）+ 未登记闸码 + 最近触发明细
 * - `GET /governance/events`      八类治理事件联合视图
 * - `GET /memory/context-usage`   逐会话窗口利用率实测
 *
 * 三张卡**独立取数、独立报错、互不牵连**：一张卡的请求失败不许让另外两张变空白。
 * 失败时把后端 detail 原文亮出来（404/503 的 detail 里写着要设哪个环境变量，
 * 那句话是给用户看的，前端不许改写成"加载失败"）。
 *
 * 「不编数」沿用仓库既定口径：台账取不到的东西就写「未知」，不许用 0 顶上去——
 * 窗口未知的会话显示「窗口未知」，绝不显示 0%；rows=0 的门**照样占一行**，
 * 因为「从没触发」和「没数据」是两件必须分得开的事。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Empty,
  Progress,
  Segmented,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { ReloadOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import {
  governanceApi,
  GOV_DAYS_OPTIONS,
  GOV_EVENT_KINDS,
  type ContextUsageResponse,
  type ContextUsageSessionRow,
  type GovernanceEventRow,
  type GovernanceEventsResponse,
  type LoopGateBucket,
  type LoopGateRecentRow,
  type LoopGateThresholds,
  type LoopGatesResponse,
} from '../../api/modules/governance';

const { Text } = Typography;

/** 单卡状态：数据 / 加载中 / 错误原文。三张卡各一份，互不共享。 */
interface CardState<T> {
  data: T | null;
  loading: boolean;
  error: string;
}

const initOf = <T,>(): CardState<T> => ({ data: null, loading: false, error: '' });

/** 后端 detail / Error → 可展示的原文，不加工（空串由调用方用 i18n 兜底）。 */
function errText(e: unknown): string {
  return e instanceof Error ? e.message : String(e ?? '');
}

/**
 * epoch 秒（float）→ `YYYY-MM-DD HH:mm:ss`（本地时区）。
 *
 * 治理事件的 `ts` 是 `time.time()` 写进去的浮点秒，*1000 才能给 Date；
 * 非法值交「-」，不编一个时间出来。写全日期（带年），治理事件按天跨度看，
 * 只有月-日会读不出「哪一年」。
 */
function fmtEpochSec(v: unknown): string {
  const sec = Number(v);
  if (!Number.isFinite(sec) || sec <= 0) return '-';
  const d = new Date(sec * 1000);
  if (Number.isNaN(d.getTime())) return '-';
  const p = (n: number) => String(n).padStart(2, '0');
  return (
    `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ` +
    `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
  );
}

/**
 * ISO 字符串 → 同样格式。循环闸明细的 `created_at` 是后端 `_lg_iso` 归一化过的
 * ISO 文本（不是 epoch 秒）——两张卡的时间类型不同，别共用一个格式化函数。
 * 解析不出来就把原文交出去，让用户看到后端到底给了什么。
 */
function fmtIso(v: unknown): string {
  const raw = String(v ?? '').trim();
  if (!raw) return '-';
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return raw;
  const p = (n: number) => String(n).padStart(2, '0');
  return (
    `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ` +
    `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
  );
}

/**
 * 百分比：取不到就是「未知」，不许渲染成 0%。
 * 注意 `Number(null) === 0` 这个陷阱 —— 只判 `Number.isFinite` 会把 null 变成 0.0%，
 * 而「利用率为零」是个和「未知」完全不同的治理结论。
 */
function pctText(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—';
  const n = Number(v);
  if (!Number.isFinite(n)) return '—';
  return `${n.toFixed(1)}%`;
}

/** 峰值利用率的色档：越吃越满越扎眼，一眼看出哪条会话在预算边缘。 */
function pctColor(v: number): string {
  if (v >= 85) return '#cf1322';
  if (v >= 60) return '#d46b08';
  return '#389e0d';
}

/**
 * kind → i18n 键。词表来自后端 `EVENT_KINDS`（SSOT 在后端），
 * 前端不发明新词 —— 界面上出现的每个 kind 都必须能在后端词表里找到。
 */
const KIND_KEYS: Record<string, string> = {
  judge: 'kindJudge',
  tool: 'kindTool',
  tool_denied: 'kindToolDenied',
  approval: 'kindApproval',
  memory: 'kindMemory',
  file_version: 'kindFileVersion',
  sandbox_denied: 'kindSandboxDenied',
  config: 'kindConfig',
};

/** 动作（block/hint/finalize/...）配色：拦下来的和只是提示的必须一眼分得开。 */
const ACTION_COLORS: Record<string, string> = {
  block: 'red',
  force_text_only: 'volcano',
  finalize: 'orange',
  hint: 'blue',
  observe: 'green',
};

/**
 * `enabled` 归一。
 *
 * 后端这个字段给的是**阈值现状对象**（GateThresholds 全字段，每次请求现读 env），
 * 不是布尔。判定口径：全字段都是「不拦」的取值（数值门为 0、开关为 false）才算未启用；
 * 空对象表示后端读不到配置 —— 那是不能下结论的，返回 null 让页面写「未知」。
 */
function gateEnabledFlag(
  enabled: LoopGateThresholds | boolean | null | undefined,
): { known: boolean; on: boolean; thresholds: LoopGateThresholds | null } {
  if (typeof enabled === 'boolean') return { known: true, on: enabled, thresholds: null };
  if (enabled && typeof enabled === 'object') {
    const entries = Object.entries(enabled);
    if (!entries.length) return { known: false, on: false, thresholds: null };
    const on = entries.some(([, v]) =>
      typeof v === 'boolean' ? v : Number(v ?? 0) > 0,
    );
    return { known: true, on, thresholds: enabled };
  }
  return { known: false, on: false, thresholds: null };
}

export default function GovernancePanel() {
  const { t } = useTranslation();
  const [days, setDays] = useState<number>(7);
  /** '' = 全部。空值时整个 kind 参数不发（后端 kind 是 list，空串会被判未知 → 400）。 */
  const [kind, setKind] = useState<string>('');

  const [gatesS, setGatesS] = useState<CardState<LoopGatesResponse>>(initOf<LoopGatesResponse>());
  const [eventsS, setEventsS] = useState<CardState<GovernanceEventsResponse>>(initOf<GovernanceEventsResponse>());
  const [usageS, setUsageS] = useState<CardState<ContextUsageResponse>>(initOf<ContextUsageResponse>());

  const loadGates = useCallback(async (d: number) => {
    setGatesS((s) => ({ ...s, loading: true, error: '' }));
    try {
      const res = await governanceApi.loopGates(d, 20);
      // 后端读库失败不抛 HTTP 错，而是在载荷里给 error —— 这条路也要能看见
      setGatesS({ data: res, loading: false, error: res?.error ? String(res.error) : '' });
    } catch (e) {
      setGatesS({ data: null, loading: false, error: errText(e) || t('myspace.governance.unknownError', '取数失败') });
    }
  }, [t]);

  const loadEvents = useCallback(async (k: string) => {
    setEventsS((s) => ({ ...s, loading: true, error: '' }));
    try {
      const res = await governanceApi.events(k, 100);
      setEventsS({ data: res, loading: false, error: '' });
    } catch (e) {
      setEventsS({ data: null, loading: false, error: errText(e) || t('myspace.governance.unknownError', '取数失败') });
    }
  }, [t]);

  const loadUsage = useCallback(async (d: number) => {
    setUsageS((s) => ({ ...s, loading: true, error: '' }));
    try {
      const res = await governanceApi.contextUsage(d, 500);
      setUsageS({ data: res, loading: false, error: res?.note && !res.ok ? String(res.note) : '' });
    } catch (e) {
      setUsageS({ data: null, loading: false, error: errText(e) || t('myspace.governance.unknownError', '取数失败') });
    }
  }, [t]);

  // 窗口变化：卡 A + 卡 C 并发重取（两者都按 days 收窄）
  useEffect(() => {
    void loadGates(days);
    void loadUsage(days);
  }, [days, loadGates, loadUsage]);

  // kind 只影响卡 B —— 切过滤只重取事件，不惊动另外两张卡
  useEffect(() => {
    void loadEvents(kind);
  }, [kind, loadEvents]);

  const refreshAll = useCallback(() => {
    void loadGates(days);
    void loadEvents(kind);
    void loadUsage(days);
  }, [days, kind, loadGates, loadEvents, loadUsage]);

  const anyLoading = gatesS.loading || eventsS.loading || usageS.loading;

  // ── 卡 A · 循环闸对账 ─────────────────────────────────
  const gates: LoopGateBucket[] = useMemo(() => {
    const list = [...(gatesS.data?.gates ?? [])];
    // 按台账行倒序。后端已经这么排了，这里再排一次是防「接口顺序变了页面跟着变」——
    // 治理页的排序是页面的承诺，不该依赖服务端返回顺序。
    list.sort((a, b) => Number(b?.rows ?? 0) - Number(a?.rows ?? 0));
    return list;
  }, [gatesS.data]);

  const gateFlag = useMemo(() => gateEnabledFlag(gatesS.data?.enabled), [gatesS.data]);

  const gateColumns = useMemo<ColumnsType<LoopGateBucket>>(
    () => [
      {
        title: t('myspace.governance.colGate', '闸'),
        dataIndex: 'gate',
        width: 200,
        render: (v: string, row) => (
          <span style={{ fontSize: 12 }}>
            <b>{row.label || v || '—'}</b>
            <br />
            <Text type="secondary" style={{ fontSize: 11 }}>
              {v || t('myspace.governance.emptyGateCode', '未标注')}
            </Text>
          </span>
        ),
      },
      {
        title: t('myspace.governance.colRows', '台账行'),
        dataIndex: 'rows',
        width: 92,
        sorter: (a, b) => Number(a.rows ?? 0) - Number(b.rows ?? 0),
        render: (v: number) =>
          Number(v ?? 0) > 0 ? (
            <b>{Number(v ?? 0)}</b>
          ) : (
            // 0 必须占着这一行：「从没触发」是治理结论，不是可以省略的空格
            <Text type="secondary">0</Text>
          ),
      },
      {
        title: t('myspace.governance.colHits', '触发次数'),
        dataIndex: 'hits',
        width: 96,
        render: (v: number) => <span style={{ fontSize: 12 }}>{Number(v ?? 0)}</span>,
      },
      {
        title: t('myspace.governance.colActions', '动作'),
        dataIndex: 'actions',
        width: 150,
        render: (v: Record<string, number>) => {
          const entries = Object.entries(v ?? {});
          if (!entries.length) return <Text type="secondary">—</Text>;
          return (
            <Space size={4} wrap>
              {entries.map(([a, c]) => (
                <Tag key={a} color={ACTION_COLORS[a] || 'default'} style={{ fontSize: 11 }}>
                  {a}×{Number(c ?? 0)}
                </Tag>
              ))}
            </Space>
          );
        },
      },
      {
        title: t('myspace.governance.colLast', '最近触发'),
        dataIndex: 'last_at',
        width: 150,
        render: (v: string | null) => (
          <span style={{ fontSize: 12 }}>{v ? fmtIso(v) : '—'}</span>
        ),
      },
      {
        title: '',
        dataIndex: '_never',
        key: '_never',
        render: (_: unknown, row) =>
          Number(row.rows ?? 0) > 0 ? null : (
            <Text type="secondary" style={{ fontSize: 11 }} data-testid="never-tag">
              {t('myspace.governance.never', '从没触发')}
            </Text>
          ),
      },
    ],
    [t],
  );

  const recentColumns = useMemo<ColumnsType<LoopGateRecentRow>>(
    () => [
      {
        title: t('myspace.governance.colTime', '时间'),
        dataIndex: 'created_at',
        width: 150,
        render: (v: string) => <span style={{ fontSize: 12 }}>{fmtIso(v)}</span>,
      },
      {
        title: t('myspace.governance.colGate', '闸'),
        dataIndex: 'gate',
        width: 110,
        render: (v: string) => <Tag style={{ fontSize: 11 }}>{v || t('myspace.governance.emptyGateCode', '未标注')}</Tag>,
      },
      {
        title: t('myspace.governance.colActionShort', '动作'),
        dataIndex: 'action',
        width: 90,
        render: (v: string) =>
          v ? <Tag color={ACTION_COLORS[v] || 'default'} style={{ fontSize: 11 }}>{v}</Tag> : '—',
      },
      {
        title: t('myspace.governance.colSession', '会话'),
        dataIndex: 'chat_id',
        width: 130,
        ellipsis: true,
        render: (v: string) => <span style={{ fontSize: 12 }}>{v || '—'}</span>,
      },
      {
        title: t('myspace.governance.colTurn', '轮次'),
        dataIndex: 'turn',
        width: 60,
        render: (v: number) => <span style={{ fontSize: 12 }}>{v == null ? '—' : v}</span>,
      },
      {
        title: t('myspace.governance.colReason', '为什么'),
        dataIndex: 'reason',
        ellipsis: { showTitle: false },
        render: (v: string) =>
          v ? (
            <Tooltip title={v} placement="topLeft">
              <Text style={{ fontSize: 12 }} ellipsis>
                {v}
              </Text>
            </Tooltip>
          ) : (
            '—'
          ),
      },
    ],
    [t],
  );

  // ── 卡 B · 治理事件 ──────────────────────────────────
/** 事件行 + 补齐的行键（antd rowKey 的第二参数已弃用，键在取数时拼好）。 */
type EventRow = GovernanceEventRow & { __rowKey: string };

  const eventColumns = useMemo<ColumnsType<EventRow>>(
    () => [
      {
        title: t('myspace.governance.colKind', '类别'),
        dataIndex: 'kind',
        width: 110,
        render: (v: string) => (
          <Tag style={{ fontSize: 11 }}>
            {KIND_KEYS[v] ? t(`myspace.governance.${KIND_KEYS[v]}`, v) : v}
          </Tag>
        ),
      },
      {
        title: t('myspace.governance.colTime', '时间'),
        dataIndex: 'ts',
        width: 150,
        render: (v: number | null) => (
          <span style={{ fontSize: 12 }} data-testid="event-time">
            {fmtEpochSec(v)}
          </span>
        ),
      },
      {
        title: t('myspace.governance.colSource', '来源'),
        dataIndex: 'source',
        width: 120,
        ellipsis: true,
        render: (v: string) => <span style={{ fontSize: 12 }}>{v || '—'}</span>,
      },
      {
        title: t('myspace.governance.colAction', '动作'),
        dataIndex: 'action',
        ellipsis: { showTitle: false },
        render: (v: string, row) => (
          <span style={{ fontSize: 12 }}>
            {v || '—'}
            {row.reason ? (
              <Tooltip title={row.reason} placement="topLeft">
                {/* reason 后端截到 200 字，仍是长句。整段收进 Tooltip，
                    绝不整列撑开 —— 表格被一句话撑破就没法横向看了 */}
                <Text
                  type="secondary"
                  style={{ fontSize: 11, marginLeft: 6, maxWidth: 220 }}
                  ellipsis
                >
                  {row.reason}
                </Text>
              </Tooltip>
            ) : null}
          </span>
        ),
      },
      {
        title: t('myspace.governance.colTarget', '对象'),
        dataIndex: 'target',
        width: 140,
        ellipsis: true,
        render: (v: string, row) => (
          <span style={{ fontSize: 12 }}>{v || row.session || '—'}</span>
        ),
      },
      {
        title: t('myspace.governance.colResult', '结果'),
        dataIndex: 'result',
        width: 100,
        ellipsis: true,
        render: (v: string) => <span style={{ fontSize: 12 }}>{v || '—'}</span>,
      },
      {
        title: t('myspace.governance.colUser', '操作者'),
        dataIndex: 'username',
        width: 100,
        ellipsis: true,
        render: (v: string) => <span style={{ fontSize: 12 }}>{v || '—'}</span>,
      },
    ],
    [t],
  );

  // ── 卡 C · 上下文消耗对账 ────────────────────────────
  const usageRows = useMemo<ContextUsageSessionRow[]>(
    () =>
      // 会话标识可为空（后端按 chat_key 空串归到一处），所以行键补齐序号
      (usageS.data?.usage?.sessions ?? []).map(
        (r, i): ContextUsageSessionRow => ({
          ...r,
          session_id: r.session_id || `__nosid_${i}`,
        }),
      ),
    [usageS.data],
  );

  const usageColumns = useMemo<ColumnsType<ContextUsageSessionRow>>(
    () => [
      {
        title: t('myspace.governance.colSession', '会话'),
        dataIndex: 'session_id',
        width: 150,
        ellipsis: true,
        render: (v: string) => (
          <span style={{ fontSize: 12 }} title={v || ''}>
            {v || '(无会话标识)'}
          </span>
        ),
      },
      {
        title: t('myspace.governance.colCalls', '调用数'),
        dataIndex: 'calls',
        width: 80,
        render: (v: number) => <span style={{ fontSize: 12 }}>{Number(v ?? 0)}</span>,
      },
      {
        title: t('myspace.governance.colWindow', '窗口'),
        dataIndex: 'window_tokens',
        width: 130,
        render: (v: number | null) =>
          Number(v ?? 0) > 0 ? (
            <span style={{ fontSize: 12 }}>{Number(v)} tokens</span>
          ) : (
            // 窗口取不到 → 说「窗口未知」。利用率不可计算，写 0% 就是编数
            <Tooltip
              title={t(
                'myspace.governance.windowUnknownHint',
                '台账里没有该会话的模型记录，模型窗口自报值取不到 → 利用率不可计算（不猜窗口）',
              )}
            >
              <Tag color="default" style={{ fontSize: 11 }} data-testid="window-unknown">
                {t('myspace.governance.windowUnknown', '窗口未知')}
              </Tag>
            </Tooltip>
          ),
      },
      {
        title: t('myspace.governance.colAvg', '均值利用率'),
        dataIndex: 'avg_used_pct',
        width: 110,
        render: (v: number | null) => (
          <span style={{ fontSize: 12 }} data-testid="avg-pct">
            {pctText(v)}
          </span>
        ),
      },
      {
        title: t('myspace.governance.colPeak', '峰值利用率'),
        dataIndex: 'peak_used_pct',
        width: 180,
        render: (v: number | null, row) =>
          Number(v ?? 0) > 0 ? (
            <Space size={6} style={{ fontSize: 12 }}>
              <Progress
                percent={Math.min(100, Number(v))}
                size={[70, 6]}
                showInfo={false}
                strokeColor={pctColor(Number(v))}
              />
              <b style={{ fontSize: 12, color: pctColor(Number(v)) }} data-testid="peak-pct">
                {pctText(v)}
              </b>
              {Number(v) > 100 ? (
                <Text type="danger" style={{ fontSize: 11 }}>
                  {t('myspace.governance.over100', '超窗口')}
                </Text>
              ) : null}
            </Space>
          ) : (
            // 窗口未知时 peak 也是 null —— 这一格同样是「未知」，不是 0%
            <Text type="secondary" style={{ fontSize: 11 }} data-testid="peak-unknown">
              {row.window_source === 'unknown'
                ? t('myspace.governance.windowUnknown', '窗口未知')
                : '—'}
            </Text>
          ),
      },
      {
        title: t('myspace.governance.colOver', '预算'),
        dataIndex: 'over_budget',
        width: 90,
        render: (v: boolean | null) =>
          v === true ? (
            <Text type="danger" style={{ fontSize: 12 }} data-testid="over-budget">
              {t('myspace.governance.overBudget', '超预算')}
            </Text>
          ) : v === false ? (
            <Text type="secondary" style={{ fontSize: 12 }}>
              {t('myspace.governance.inBudget', '预算内')}
            </Text>
          ) : (
            <Text type="secondary" style={{ fontSize: 11 }}>
              {t('myspace.governance.overUnknown', '不可判')}
            </Text>
          ),
      },
    ],
    [t],
  );

  const recent = gatesS.data?.recent ?? [];
  const unknownGates = Object.entries(gatesS.data?.unknown_gates ?? {});
  /**
   * 行键在取数时补齐（不用 antd rowKey 的第二参数 —— 那个签名已弃用）。
   * 事件行没有稳定唯一 id（ref_id 可为 null，同秒可多行），所以用「序号 + 字段」拼。
   */
  const events = (eventsS.data?.events ?? []).map((r, i) => ({
    ...r,
    __rowKey: `${i}-${r.kind}-${r.ts ?? 'x'}-${r.ref_id ?? ''}`,
  }));
  const tier = usageS.data?.tier ?? {};
  const tierTargets = tier.targets ?? {};
  const rowsScanned = Number(usageS.data?.rows_scanned ?? 0);

  return (
    <div>
      {/* ── 面板工具条 ─────────────────────────────────
          days 只有卡 A/卡 C 用（后端按 created_at / ts 收窄），卡 B 的治理事件
          审计链没有 days 参数 —— 窗口选择器不假装影响三张卡。 */}
      <Space size={12} wrap style={{ marginBottom: 12 }}>
        <Text style={{ fontSize: 12 }}>{t('myspace.governance.daysLabel', '统计窗口')}</Text>
        <Segmented
          size="small"
          value={String(days)}
          onChange={(v) => setDays(Number(v) || 7)}
          options={GOV_DAYS_OPTIONS.map((d) => ({
            value: String(d),
            label: t('myspace.governance.daysN', '{{n}} 天', { n: d }),
          }))}
        />
        <Tooltip title={t('myspace.governance.refreshTip', '重新取数（三个只读端点，不写任何东西）')}>
          <Button
            size="small"
            icon={<ReloadOutlined />}
            loading={anyLoading}
            onClick={refreshAll}
          >
            {t('common.refresh', '刷新')}
          </Button>
        </Tooltip>
        <Text type="secondary" style={{ fontSize: 12 }}>
          {t('myspace.governance.panelNote', '三个只读对账视图，数据都来自服务端台账与审计链。')}
        </Text>
      </Space>

      {/* ── 卡 A · 循环闸对账 ─────────────────────────── */}
      <Card
        size="small"
        style={{ marginBottom: 16 }}
        title={
          <Text style={{ fontSize: 13, fontWeight: 600 }}>
            {t('myspace.governance.gatesTitle', '循环闸对账')}
          </Text>
        }
      >
        {gatesS.error ? (
          <Alert
            type="error"
            showIcon
            style={{ marginBottom: 12 }}
            message={t('myspace.governance.loadFailed', '取数失败')}
            description={gatesS.error}
          />
        ) : null}
        {!gatesS.error && gateFlag.known && !gateFlag.on ? (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 12 }}
            message={t('myspace.governance.gatesOff', '循环闸当前未启用')}
            description={t(
              'myspace.governance.gatesOffBody',
              '阈值全部为「不拦」的取值（数值门为 0、开关为 false）。台账里的闸门行是历史行，当前轮次不会再生成。',
            )}
          />
        ) : null}
        {!gatesS.error && !gateFlag.known ? (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 12 }}
            message={t('myspace.governance.gatesUnknown', '闸开关状态未知')}
            description={t(
              'myspace.governance.gatesUnknownBody',
              '后端未返回阈值现状，无法判断启用与否 —— 这里不下结论。',
            )}
          />
        ) : null}
        {!gatesS.error && unknownGates.length > 0 ? (
          <Alert
            type="warning"
            showIcon
            data-testid="unknown-gates"
            style={{ marginBottom: 12 }}
            message={t('myspace.governance.unknownGates', '未登记闸码')}
            description={
              <Space size={4} wrap>
                {unknownGates.map(([g, c]) => (
                  <Tag key={g || '__empty'} color="red" style={{ fontSize: 11 }}>
                    {g || t('myspace.governance.emptyGateCode', '未标注')}×{Number(c ?? 0)}
                  </Tag>
                ))}
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {t(
                    'myspace.governance.unknownGatesHint',
                    '这些闸码不在闸码表里，计数没有并进十门 —— 明细见下表，不静默丢弃。',
                  )}
                </Text>
              </Space>
            }
          />
        ) : null}
        {!gatesS.error && gatesS.data ? (
          <Space size={10} wrap style={{ marginBottom: 12 }}>
            <Text style={{ fontSize: 12 }}>
              {t('myspace.governance.totalRows', '台账行合计')}{' '}
              <b data-testid="total-rows">{Number(gatesS.data.total_rows ?? 0)}</b>
            </Text>
            <Text style={{ fontSize: 12 }}>
              {t('myspace.governance.totalHits', '触发合计')}{' '}
              <b data-testid="total-hits">{Number(gatesS.data.total_hits ?? 0)}</b>
            </Text>
            <Text style={{ fontSize: 12 }} data-testid="active-gates">
              {t('myspace.governance.activeGates', '有触发的门')}{' '}
              <b>
                {Number(gatesS.data.active_gates ?? 0)}/{gates.length}
              </b>
            </Text>
            {gatesS.data.counting_note ? (
              <Text type="secondary" style={{ fontSize: 11 }} data-testid="counting-note">
                {gatesS.data.counting_note}
              </Text>
            ) : null}
            {gateFlag.thresholds ? (
              <Tooltip
                title={
                  <span>
                    round_budget={String(gateFlag.thresholds.round_budget ?? '')}
                    <br />
                    stop_phrase={String(gateFlag.thresholds.stop_phrase ?? '')}
                    <br />
                    dedup={String(gateFlag.thresholds.dedup ?? '')}
                    <br />
                    empty_streak={String(gateFlag.thresholds.empty_streak ?? '')}
                    <br />
                    session_warn={String(gateFlag.thresholds.session_warn ?? '')}
                    <br />
                    stagnation_similarity={String(gateFlag.thresholds.stagnation_similarity ?? '')}
                    <br />
                    stagnation_force_exit={String(gateFlag.thresholds.stagnation_force_exit ?? '')}
                  </span>
                }
              >
                <Tag color={gateFlag.on ? 'green' : 'default'} style={{ fontSize: 11 }}>
                  {t('myspace.governance.thresholds', '当前阈值')}
                </Tag>
              </Tooltip>
            ) : null}
          </Space>
        ) : null}
        <Table
          size="small"
          rowKey={(r) => r.gate || '__empty_gate'}
          loading={gatesS.loading}
          dataSource={gates}
          columns={gateColumns}
          pagination={false}
          locale={{
            emptyText: (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={t(
                  'myspace.governance.gatesEmpty',
                  '后端没有返回任何闸门行（十门应当全部出现，含零值行）',
                )}
              />
            ),
          }}
        />
        <div style={{ marginTop: 12 }}>
          <Text style={{ fontSize: 12, fontWeight: 600 }}>
            {t('myspace.governance.recentTitle', '最近触发明细')}
          </Text>
          <Table
            size="small"
            style={{ marginTop: 8 }}
            rowKey={(r) => r.event_id || `${r.created_at}-${r.gate}-${r.turn}`}
            dataSource={recent}
            columns={recentColumns}
            pagination={false}
            locale={{
              emptyText: (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description={t(
                    'myspace.governance.recentEmpty',
                    '窗口内没有闸触发的台账行',
                  )}
                />
              ),
            }}
          />
        </div>
      </Card>

      {/* ── 卡 B · 治理事件 ───────────────────────────── */}
      <Card
        size="small"
        style={{ marginBottom: 16 }}
        title={
          <Space size={10} wrap>
            <Text style={{ fontSize: 13, fontWeight: 600 }}>
              {t('myspace.governance.eventsTitle', '治理事件')}
            </Text>
            <Segmented
              size="small"
              value={kind}
              onChange={(v) => setKind(String(v))}
              options={[
                { value: '', label: t('common.all', '全部') },
                ...GOV_EVENT_KINDS.map((k) => ({
                  value: k,
                  label: t(`myspace.governance.${KIND_KEYS[k]}`, k),
                })),
              ]}
            />
          </Space>
        }
        extra={
          <Text type="secondary" style={{ fontSize: 11 }}>
            {t('myspace.governance.eventsScope', '管理员看全量，普通用户只看自己的事件')}
          </Text>
        }
      >
        {eventsS.error ? (
          <Alert
            type="error"
            showIcon
            style={{ marginBottom: 12 }}
            message={t('myspace.governance.loadFailed', '取数失败')}
            description={eventsS.error}
          />
        ) : null}
        <Table
          size="small"
          rowKey={(r) => r.__rowKey}
          loading={eventsS.loading}
          dataSource={events}
          columns={eventColumns}
          pagination={{ pageSize: 20, size: 'small', showSizeChanger: false }}
          locale={{
            emptyText: (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={t('myspace.governance.eventsEmpty', '没有治理事件记录')}
              />
            ),
          }}
        />
      </Card>

      {/* ── 卡 C · 上下文消耗对账 ─────────────────────── */}
      <Card
        size="small"
        title={
          <Text style={{ fontSize: 13, fontWeight: 600 }}>
            {t('myspace.governance.ctxTitle', '上下文消耗对账')}
          </Text>
        }
      >
        {usageS.error ? (
          <Alert
            type="error"
            showIcon
            style={{ marginBottom: 12 }}
            message={t('myspace.governance.loadFailed', '取数失败')}
            description={usageS.error}
          />
        ) : null}
        <Space size={6} wrap style={{ marginBottom: 12 }}>
          <Tag
            color={tier.compact_enabled ? 'green' : 'default'}
            style={{ fontSize: 11 }}
            data-testid="compact-flag"
          >
            {tier.compact_enabled
              ? t('myspace.governance.compactOn', '压缩已开启')
              : t('myspace.governance.compactOff', '压缩未开启')}
          </Tag>
          {(['full', 'thinking', 'lightweight'] as const).map((k) =>
            tierTargets[k] == null ? null : (
              <Tag key={k} style={{ fontSize: 11 }} data-testid={`tier-${k}`}>
                {t(`myspace.governance.tier.${k}`, k)} {Number(tierTargets[k])} tokens
              </Tag>
            ),
          )}
          <Text style={{ fontSize: 12 }}>
            {t('myspace.governance.rowsScanned', '扫描台账行')} {rowsScanned}
          </Text>
          {usageS.data?.usage?.measurable_sessions != null ? (
            <Text style={{ fontSize: 12 }}>
              {t('myspace.governance.measurable', '可测会话')}{' '}
              {Number(usageS.data.usage.measurable_sessions)}
            </Text>
          ) : null}
          {usageS.data?.usage?.window_note ? (
            <Text type="secondary" style={{ fontSize: 11 }} data-testid="window-note">
              {usageS.data.usage.window_note}
            </Text>
          ) : null}
        </Space>
        <Table
          size="small"
          rowKey={(r) => r.session_id}
          loading={usageS.loading}
          dataSource={usageRows}
          columns={usageColumns}
          pagination={{ pageSize: 20, size: 'small', showSizeChanger: false }}
          locale={{
            emptyText: (
              // 空白表格读起来像「消耗为零」。台账里没有可测记录必须明说，
              // 且带上扫描行数 —— 扫到行但利用率全不可测，是另一种情况。
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={
                  rowsScanned > 0
                    ? t(
                        'myspace.governance.usageUnmeasurable',
                        '台账里没有可测的调用记录（扫到行，但没有一条算得出利用率）',
                      )
                    : t('myspace.governance.usageEmpty', '台账里没有可测的调用记录')
                }
              />
            ),
          }}
        />
      </Card>
    </div>
  );
}




