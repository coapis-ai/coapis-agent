/**
 * 判断台账（v24 · 小蜜蜂 2026-11-09 第 3 条）
 *
 * 为什么搬到「我的空间」：聊天里那个「判断」入口此前挂在「会话资源」条上，
 * 它既不是资源、也不能预览，和「引用/产出/查看全部」并排出现，用户读成
 * 「这五个都是资源视图」。判断的真相本来就是**审计日志**——判官判没判、
 * 判成什么、有没有真跑模型、花了多少钱——它属于台账，不属于聊天输入区。
 * 于是入口从聊天摘掉，台账搬到这里，判官开关一并跟着走。
 *
 * 取数口径：`GET /decisions`（普通用户后端只返回自己的行）+
 * `GET /decisions/stats`（近 7 天逐来源战绩）+ `GET /decisions/config`。
 *
 * 字段以**后端真实列**为准：台账行是 `created_at`（float epoch 秒）、
 * `judgment/action/reason/hit_layer/latency_ms/cost/tokens/outcome/rating`。
 * 旧浮窗写的是 `ts` / `fallback_reason`（库里没有这两列），时间列恒显
 * 「-」、判由永远看不见——这里一次改对。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Empty,
  Segmented,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { ReloadOutlined, AuditOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import {
  decisionsApi,
  type DecisionEventResponse,
  type DecisionStatsResponse,
} from '../../api/modules/decisions';

const { Text } = Typography;

/** hit_layer → 颜色：一眼看出这一判是「真判断」还是「降级/没判断」。 */
const LAYER_COLORS: Record<string, string> = {
  llm: 'green',
  cached: 'cyan',
  rule: 'blue',
  gate: 'geekblue',
  budget: 'purple',
  breaker: 'orange',
  no_model: 'volcano',
  timeout: 'red',
  malformed: 'red',
  error: 'red',
};

/** 岗位（判断发生在哪个环节）。与后端 source 取值同名。 */
const SOURCE_KEYS: Record<string, string> = {
  plan_gate: 'sourcePlanGate',
  outcome: 'sourceOutcome',
  skill_trigger: 'sourceSkillTrigger',
  advisor: 'sourceAdvisor',
  // 工具闸（v27 护栏扩充后，这一岗是台账里产出最多的一岗，筛选里不能缺）
  tool_gate: 'sourceToolGate',
  // 主模型自评（v27 · 拍板 D3）：判官不在岗时的替代验收。单列一个来源，是为了
  // 让「自己给自己打分」和「判官外部验收」在台账里分得开——混在一起算命中率
  // 就是自欺。
  selfcheck: 'sourceSelfcheck',
  acceptance: 'sourceAcceptance',
  cache: 'sourceCache',
  hub: 'sourceHub',
};

const SOURCE_TOKENS = Object.keys(SOURCE_KEYS);

/** 台账时间：float epoch 秒 → 本地时间。非法值原样交出去，不编。 */
function fmtTime(v: unknown): string {
  const sec = Number(v);
  if (!Number.isFinite(sec) || sec <= 0) return '-';
  const d = new Date(sec * 1000);
  if (Number.isNaN(d.getTime())) return '-';
  const p = (n: number) => String(n).padStart(2, '0');
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

export default function JudgmentPanel() {
  const { t } = useTranslation();
  const [items, setItems] = useState<DecisionEventResponse[]>([]);
  const [stats, setStats] = useState<DecisionStatsResponse | null>(null);
  const [config, setConfig] = useState<Record<string, unknown> | null>(null);
  const [judge, setJudge] = useState<{
    provider_id: string;
    model: string;
    configured?: boolean;
    source?: string;
  }>({ provider_id: '', model: '' });
  const [source, setSource] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>('');

  const refresh = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [list, st, cfg] = await Promise.all([
        decisionsApi.list({ source: source || undefined, limit: 100 }),
        decisionsApi.stats(7),
        decisionsApi.getConfig(),
      ]);
      setItems(list.items || []);
      setStats(st);
      setConfig(cfg.config || null);
      setJudge(cfg.judge || { provider_id: '', model: '' });
      if (list.error || st.error) setError(list.error || st.error || '');
    } catch (e) {
      setError(String((e as Error)?.message || e));
    } finally {
      setLoading(false);
    }
  }, [source]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const setFlag = useCallback(async (key: string, value: boolean) => {
    try {
      const res = await decisionsApi.putConfig({ [key]: value });
      setConfig(res.decision_hub || { [key]: value });
    } catch (e) {
      setError(String((e as Error)?.message || e));
    }
  }, []);

  const rate = useCallback(async (eventId: string, rating: number) => {
    try {
      await decisionsApi.rate(eventId, rating);
      setItems((prev) =>
        prev.map((it) =>
          it.event_id === eventId
            ? { ...it, rating: rating === it.rating ? null : rating }
            : it,
        ),
      );
    } catch (e) {
      setError(String((e as Error)?.message || e));
    }
  }, []);

  const columns = useMemo<ColumnsType<DecisionEventResponse>>(
    () => [
      {
        title: t('decision.col.time', '时间'),
        dataIndex: 'created_at',
        width: 118,
        render: (v: number) => <span style={{ fontSize: 12 }}>{fmtTime(v)}</span>,
      },
      {
        title: t('decision.col.post', '岗位'),
        dataIndex: 'source',
        width: 96,
        render: (v: string) => (
          <span style={{ fontSize: 12 }}>
            {SOURCE_KEYS[v] ? t(`decision.${SOURCE_KEYS[v]}`, v) : v || '-'}
          </span>
        ),
      },
      {
        title: t('decision.col.judgment', '判断'),
        dataIndex: 'judgment',
        render: (v: string, row) => (
          <span style={{ fontSize: 12 }}>
            <b>{v || row.action || '-'}</b>
            {row.reason ? (
              <span style={{ color: '#999', marginLeft: 6 }}>{row.reason}</span>
            ) : null}
          </span>
        ),
      },
      {
        title: t('decision.col.layer', '怎么来的'),
        dataIndex: 'hit_layer',
        width: 92,
        render: (v: string) =>
          v ? <Tag color={LAYER_COLORS[v] || 'default'}>{v}</Tag> : '-',
      },
      {
        title: t('decision.col.cost', '耗时/花费'),
        dataIndex: 'latency_ms',
        width: 112,
        render: (v: number, row) => (
          <span style={{ fontSize: 12 }}>
            {v != null ? `${Math.round(v)}ms` : '-'}
            {row.cost ? ` · $${Number(row.cost).toFixed(4)}` : ''}
          </span>
        ),
      },
      {
        title: t('decision.col.outcome', '结果'),
        dataIndex: 'outcome',
        width: 76,
        render: (v: string) =>
          v && v !== 'pending' ? (
            <Tag color={v === 'hit' ? 'green' : v === 'miss' ? 'red' : 'default'}>
              {t(`decision.outcome.${v}`, v)}
            </Tag>
          ) : (
            <Text type="secondary" style={{ fontSize: 12 }}>
              {t('decision.outcomePending', '待回执')}
            </Text>
          ),
      },
      {
        title: t('decision.col.rate', '打分'),
        dataIndex: 'rating',
        width: 86,
        render: (v: number, row) => (
          <span>
            <Tooltip title={t('decision.rateGood', '判得准')}>
              <Button
                size="small"
                type={v === 1 ? 'primary' : 'text'}
                onClick={() => void rate(row.event_id, 1)}
              >
                ✓
              </Button>
            </Tooltip>
            <Tooltip title={t('decision.rateBad', '判得不准')}>
              <Button
                size="small"
                type={v === 0 ? 'primary' : 'text'}
                onClick={() => void rate(row.event_id, 0)}
              >
                ✗
              </Button>
            </Tooltip>
          </span>
        ),
      },
    ],
    [rate, t],
  );

  const bySource = stats?.by_source || [];

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      {error ? (
        <Alert type="warning" showIcon message={error} style={{ marginBottom: 0 }} />
      ) : null}

      <Card
        size="small"
        title={
          <Space size={8}>
            <AuditOutlined />
            <span style={{ fontSize: 13, fontWeight: 600 }}>
              {t('myspace.judgment.title', '判断台账（近 7 天）')}
            </span>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {t('myspace.judgment.scope', '只统计你自己的会话')}
            </Text>
          </Space>
        }
        extra={
          <Space size={12} wrap>
            <span style={{ fontSize: 12 }}>
              {t('decision.enabled', '判官')}{' '}
              <Switch
                size="small"
                checked={!!config?.enabled}
                onChange={(v) => void setFlag('enabled', v)}
              />
            </span>
            <span style={{ fontSize: 12 }}>
              {t('decision.advisor', '事中改道')}{' '}
              <Switch
                size="small"
                checked={!!config?.advisor_enabled}
                onChange={(v) => void setFlag('advisor_enabled', v)}
              />
            </span>
            <span style={{ fontSize: 12 }}>
              {t('decision.acceptance', '完成验收')}{' '}
              <Switch
                size="small"
                checked={!!config?.acceptance_enabled}
                onChange={(v) => void setFlag('acceptance_enabled', v)}
              />
            </span>
            <Button size="small" icon={<ReloadOutlined />} onClick={() => void refresh()}>
              {t('common.refresh', '刷新')}
            </Button>
          </Space>
        }
      >
        <div style={{ fontSize: 12, color: '#666', marginBottom: 8 }}>
          {t('decision.judgeModel', '判官模型')}：
          {judge.model
            ? `${judge.provider_id || '?'} / ${judge.model}`
            : t('decision.noJudge', '未配置（走规则）')}
          {judge.model && judge.source
            ? `（${t(`decision.source.${judge.source}`, judge.source)}）`
            : ''}
          {'  '}
          <a href="#/settings/models" style={{ fontSize: 12 }}>
            {t('decision.goJudgeSlot', '去判官槽位')}
          </a>
        </div>

        {bySource.length > 0 ? (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {bySource.map((s) => (
              <span
                key={s.source}
                style={{
                  fontSize: 12,
                  padding: '2px 8px',
                  borderRadius: 8,
                  background: 'rgba(0,0,0,0.04)',
                }}
                title={t('myspace.judgment.statTip', '判断次数 · 真判 · 降级 · 平均耗时')}
              >
                {SOURCE_KEYS[s.source]
                  ? t(`decision.${SOURCE_KEYS[s.source]}`, s.source)
                  : s.source}{' '}
                <b>{s.n}</b>
                {` · ${t('myspace.judgment.judged', '真判')} ${s.llm ?? 0}`}
                {` · ${t('myspace.judgment.degraded', '降级')} ${s.degraded ?? 0}`}
                {s.avg_ms ? ` · ${Math.round(Number(s.avg_ms))}ms` : ''}
              </span>
            ))}
          </div>
        ) : (
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t('myspace.judgment.noStats', '近 7 天没有判断记录。')}
          </Text>
        )}
      </Card>

      <Card
        size="small"
        title={
          <Space size={10} wrap>
            <span style={{ fontSize: 13, fontWeight: 600 }}>
              {t('myspace.judgment.list', '判断记录')}
            </span>
            <Segmented
              size="small"
              value={source}
              onChange={(v) => setSource(String(v))}
              options={[
                { value: '', label: t('common.all', '全部') },
                ...SOURCE_TOKENS.map((v) => ({
                  value: v,
                  label: t(`decision.${SOURCE_KEYS[v]}`, v),
                })),
              ]}
            />
          </Space>
        }
      >
        <Table
          size="small"
          rowKey="event_id"
          loading={loading}
          dataSource={items}
          columns={columns}
          locale={{
            emptyText: (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={t('myspace.judgment.empty', '还没有判断记录')}
              />
            ),
          }}
          pagination={{ pageSize: 20, size: 'small', showSizeChanger: false }}
        />
      </Card>
    </Space>
  );
}
