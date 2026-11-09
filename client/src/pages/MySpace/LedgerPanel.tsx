/**
 * 资源台账管理页（v20 · W2 台账管理面 + W3 治理动作 + W6 散文件归位）
 *
 * 为什么需要这一页：台账从 v17 起是「机器账本」——它知道每个文件是谁的、从哪来、
 * 被谁引用，但用户看不见也动不了。于是两类投诉一直在：台账有行、文件没了（没人
 * 知道）；散文件躺在 files/ 根下（没人归位）。这一页把台账变成能筛、能定稿、能
 * 巡检、能归位的地方。
 *
 * 三条边界（拍板 D1/D3/D4，写死在这里）：
 *   1. 永不删文件：delete 只是台账软删（deleted_at），磁盘文件原地不动；
 *   2. 巡检只报告：sweep 永不搬、永不删；搬家是用户在页面上的显式动作；
 *   3. 散文件进 files/_inbox/：归位不是替人整理，是进收件箱等人决定。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Empty,
  Input,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd';
import type { TableProps } from 'antd';
import {
  ClearOutlined,
  ReloadOutlined,
  SearchOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { useUser } from '../../contexts/UserContext';
import {
  resourceLedgerApi,
  type LedgerAction,
  type LedgerResource,
  type SweepReport,
} from '../../api/modules/resourceLedger';
import {
  formatResSize,
  formatResTime,
} from '../Chat/components/ChatSessionResources/resourceFormat';

const { Text } = Typography;

const KIND_TOKENS = ['file', 'web', 'db', 'kb', 'mcp'];
const STATUS_TOKENS = ['official', 'draft', 'archived', 'orphan'];
const SOURCE_KEYS: Record<string, string> = {
  hook: 'sourceHook',
  turn: 'sourceTurn',
  backfill: 'sourceBackfill',
  reconcile: 'sourceReconcile',
};

const STATUS_COLOR: Record<string, string> = {
  official: 'green',
  draft: 'gold',
  archived: 'default',
  orphan: 'orange',
};

/** 来源标签：turn:chat_id 这类带后缀的值统一归到「本轮产出」。 */
const sourceKey = (v?: string | null) => {
  const s = String(v || '');
  if (s.startsWith('turn')) return 'sourceTurn';
  return SOURCE_KEYS[s] || '';
};

const errText = (e: unknown, fallback: string) => {
  const x = e as { message?: string; response?: { data?: { detail?: string } } };
  return x?.response?.data?.detail || x?.message || fallback;
};
export default function LedgerPanel() {
  const { t } = useTranslation();
  const { isAdmin } = useUser();

  const [items, setItems] = useState<LedgerResource[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);

  const [kind, setKind] = useState<string | undefined>();
  const [status, setStatus] = useState<string | undefined>();
  const [category, setCategory] = useState<string | undefined>();
  const [source, setSource] = useState<string | undefined>();
  const [q, setQ] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);

  const [stats, setStats] = useState<Record<string, any>>({});
  const [categories, setCategories] = useState<string[]>([]);
  const [report, setReport] = useState<SweepReport | null>(null);
  const [selected, setSelected] = useState<string[]>([]);

  const loadList = useCallback(async () => {
    setLoading(true);
    try {
      const res = await resourceLedgerApi.listResources({
        kind,
        status,
        category,
        source,
        q,
        limit: pageSize,
        offset: (page - 1) * pageSize,
      });
      setItems(res?.items || []);
      setTotal(Number(res?.total || 0));
    } catch (e) {
      message.error(errText(e, t('myspace.ledger.governFailed')));
    } finally {
      setLoading(false);
    }
  }, [kind, status, category, source, q, page, pageSize, t]);

  const loadStats = useCallback(async () => {
    try {
      setStats((await resourceLedgerApi.stats()) || {});
    } catch {
      // 汇总条是锦上添花，读不到不能挡住清单。
    }
  }, []);

  useEffect(() => {
    loadList();
  }, [loadList]);

  useEffect(() => {
    loadStats();
    resourceLedgerApi
      .categories()
      .then((r) => setCategories(r?.categories || []))
      .catch(() => setCategories([]));
  }, [loadStats]);

  const refreshAll = useCallback(() => {
    loadList();
    loadStats();
    setSelected([]);
  }, [loadList, loadStats]);

  /** 批量治理：串行发请求。并发打同一张表会互相踩（台账行是同一把 key）。 */
  const runGovern = useCallback(
    async (keys: string[], action: LedgerAction) => {
      if (!keys.length) return;
      setBusy(true);
      let done = 0;
      let reason = '';
      for (const key of keys) {
        try {
          const out = await resourceLedgerApi.govern(key, action);
          if (out?.ok) done += 1;
          else reason = out?.reason || '';
        } catch (e) {
          reason = errText(e, '');
        }
      }
      setBusy(false);
      if (done) message.success(t('myspace.ledger.governDone'));
      else message.warning(reason || t('myspace.ledger.governFailed'));
      refreshAll();
    },
    [refreshAll, t],
  );

  const doSweep = useCallback(
    async (backfill = false) => {
      setBusy(true);
      try {
        const r = await resourceLedgerApi.sweep({ full: true, backfill });
        setReport(r);
        if (backfill && r?.backfilled) {
          message.success(`${t('myspace.ledger.sourceBackfill')} ${r.backfilled}`);
        }
        refreshAll();
      } catch (e) {
        message.error(errText(e, t('myspace.ledger.governFailed')));
      } finally {
        setBusy(false);
      }
    },
    [refreshAll, t],
  );

  /** 巡检报告里的「磁盘缺失」一键标删：只标台账，文件本来就已经没了。 */
  const markAllMissing = useCallback(async () => {
    const keys = ((report?.fs_missing_list as any[]) || [])
      .map((x) => x?.resource_key)
      .filter(Boolean);
    await runGovern(keys, 'delete');
  }, [report, runGovern]);

  const doInbox = useCallback(async () => {
    const paths = ((report?.unledgered_list as any[]) || [])
      .map((x) => x?.path)
      .filter(Boolean);
    if (!paths.length) {
      message.info(t('myspace.ledger.toInboxEmpty'));
      return;
    }
    setBusy(true);
    try {
      const out = await resourceLedgerApi.toInbox(paths);
      message.success(
        t('myspace.ledger.toInboxDone', { n: out?.moved_count ?? paths.length }),
      );
      setReport(null);
      refreshAll();
    } catch (e) {
      message.error(errText(e, t('myspace.ledger.governFailed')));
    } finally {
      setBusy(false);
    }
  }, [report, refreshAll, t]);

  const columns = useMemo<TableProps<LedgerResource>['columns']>(
    () => [
      {
        title: t('myspace.ledger.colName'),
        dataIndex: 'title',
        key: 'title',
        ellipsis: true,
        render: (_: unknown, r: LedgerResource) => (
          <Tooltip title={r.path}>
            <span>{r.title || r.path || r.resource_key}</span>
          </Tooltip>
        ),
      },
      {
        title: t('myspace.ledger.filterCategory'),
        dataIndex: 'category',
        key: 'category',
        width: 96,
        render: (v: string) => (v ? <Tag>{v}</Tag> : '-'),
      },
      {
        title: t('myspace.ledger.filterKind'),
        dataIndex: 'kind',
        key: 'kind',
        width: 72,
        render: (v: string) => <Tag>{v}</Tag>,
      },
      {
        title: t('myspace.ledger.filterSource'),
        dataIndex: 'source',
        key: 'source',
        width: 110,
        render: (v: string) => {
          const k = sourceKey(v);
          return <Tag color="blue">{k ? t(`myspace.ledger.${k}`) : v || '-'}</Tag>;
        },
      },
      {
        title: t('myspace.ledger.filterStatus'),
        dataIndex: 'status',
        key: 'status',
        width: 96,
        render: (v: string) => <Tag color={STATUS_COLOR[v] || 'default'}>{v}</Tag>,
      },
      {
        title: t('myspace.ledger.colSize'),
        dataIndex: 'size',
        key: 'size',
        width: 90,
        render: (v: number) => formatResSize(v),
      },
      {
        title: t('myspace.ledger.colTime'),
        key: 'time',
        width: 160,
        render: (_: unknown, r: LedgerResource) =>
          formatResTime(r.updated_at || r.last_seen_at),
      },
      {
        title: t('myspace.ledger.colRef'),
        dataIndex: 'ref_count',
        key: 'ref_count',
        width: 70,
        render: (v: number) => Number(v || 0),
      },
    ],
    [t],
  );

  const statCards = [
    { k: 'statTotal', v: stats?.total },
    { k: 'statOfficial', v: stats?.by_status?.official },
    { k: 'statDraft', v: stats?.by_status?.draft },
    { k: 'statOrphan', v: stats?.orphans },
    { k: 'statMissing', v: stats?.fs_missing },
  ];

  return (
    <div className="page-content" style={{ padding: 16 }}>
      <div style={{ marginBottom: 12 }}>
        <Text type="secondary">{t('myspace.ledger.desc')}</Text>
      </div>

      <Space size={12} wrap style={{ marginBottom: 16 }}>
        {statCards.map((c) => (
          <Card key={c.k} size="small" style={{ minWidth: 118 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {t(`myspace.ledger.${c.k}`)}
            </Text>
            <div style={{ fontSize: 20, lineHeight: '24px' }}>{c.v ?? 0}</div>
          </Card>
        ))}
      </Space>

      <Space size={8} wrap style={{ marginBottom: 12 }}>
        <Select allowClear style={{ width: 128 }} placeholder={t('myspace.ledger.filterKind')}
          value={kind} onChange={(v) => { setKind(v); setPage(1); }}
          options={KIND_TOKENS.map((v) => ({ value: v, label: v }))} />
        <Select allowClear style={{ width: 128 }} placeholder={t('myspace.ledger.filterStatus')}
          value={status} onChange={(v) => { setStatus(v); setPage(1); }}
          options={STATUS_TOKENS.map((v) => ({ value: v, label: v }))} />
        <Select allowClear style={{ width: 138 }} placeholder={t('myspace.ledger.filterCategory')}
          value={category} onChange={(v) => { setCategory(v); setPage(1); }}
          options={(categories || []).map((v) => ({ value: v, label: v }))} />
        <Select allowClear style={{ width: 138 }} placeholder={t('myspace.ledger.filterSource')}
          value={source} onChange={(v) => { setSource(v); setPage(1); }}
          options={Object.keys(SOURCE_KEYS).map((v) => ({
            value: v,
            label: t(`myspace.ledger.${SOURCE_KEYS[v]}`),
          }))} />
        <Input style={{ width: 200 }} allowClear prefix={<SearchOutlined />}
          placeholder={t('myspace.ledger.filterKeyword')} value={q}
          onChange={(e) => setQ(e.target.value)}
          onPressEnter={() => { setPage(1); loadList(); }} />
        <Button icon={<ReloadOutlined />} onClick={refreshAll}>
          {t('myspace.ledger.refresh')}
        </Button>
      </Space>

      {selected.length > 0 && (
        <Space size={8} wrap style={{ marginBottom: 12 }}>
          <Text type="secondary">{selected.length}</Text>
          <Button size="small" disabled={busy} onClick={() => runGovern(selected, 'publish')}>
            {t('myspace.ledger.actionPublish')}
          </Button>
          <Button size="small" disabled={busy} onClick={() => runGovern(selected, 'to_draft')}>
            {t('myspace.ledger.actionToDraft')}
          </Button>
          <Button size="small" disabled={busy} onClick={() => runGovern(selected, 'archive')}>
            {t('myspace.ledger.actionArchive')}
          </Button>
          <Popconfirm title={t('myspace.ledger.confirmDelete')}
            onConfirm={() => runGovern(selected, 'delete')}>
            <Button size="small" danger disabled={busy}>
              {t('myspace.ledger.actionDelete')}
            </Button>
          </Popconfirm>
        </Space>
      )}

      <Table size="small" rowKey="resource_key" loading={loading} dataSource={items}
        columns={columns}
        locale={{ emptyText: <Empty description={t('myspace.ledger.empty')} /> }}
        rowSelection={{ selectedRowKeys: selected, onChange: (keys) => setSelected(keys as string[]) }}
        pagination={{
          current: page, pageSize, total, showSizeChanger: true,
          onChange: (p, ps) => { setPage(p); setPageSize(ps); },
        }} />

      <div style={{ marginTop: 16 }}>
        <Space size={8} wrap>
          <Button icon={<ThunderboltOutlined />} disabled={busy || !isAdmin} onClick={() => doSweep(false)}>
            {t('myspace.ledger.sweep')}
          </Button>
          {isAdmin && (
            <Button disabled={busy} onClick={() => doSweep(true)}>
              {t('myspace.ledger.sourceBackfill')}
            </Button>
          )}
          <Button icon={<ClearOutlined />} disabled={busy || !report?.unledgered} onClick={doInbox}>
            {t('myspace.ledger.toInbox')}
          </Button>
        </Space>
        <div style={{ marginTop: 8 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {isAdmin ? t('myspace.ledger.sweepTip') : t('myspace.ledger.sweepAdminOnly')}
          </Text>
        </div>
      </div>

      {report && (
        <div style={{ marginTop: 12 }}>
          <Alert
            type={report.fs_missing || report.orphans || report.unledgered ? 'warning' : 'success'}
            showIcon
            message={
              report.fs_missing || report.orphans || report.unledgered
                ? `fs_missing=${report.fs_missing ?? 0}  orphan=${report.orphans ?? 0}  unledgered=${report.unledgered ?? 0}  relocated=${report.relocated ?? 0}  expired=${report.expired ?? 0}`
                : t('myspace.ledger.reportEmpty')
            }
            description={
              <div style={{ fontSize: 12 }}>
                {((report.fs_missing_list as any[]) || []).length > 0 && (
                  <div>
                    <b>{t('myspace.ledger.fsMissingList')}</b>
                    <ul style={{ margin: '4px 0 8px', paddingLeft: 18, maxHeight: 120, overflow: 'auto' }}>
                      {((report.fs_missing_list as any[]) || []).map((x, i) => (
                        <li key={`m${i}`}>{x?.owner_id}/{x?.path}</li>
                      ))}
                    </ul>
                    <Popconfirm title={t('myspace.ledger.confirmDelete')} onConfirm={markAllMissing}>
                      <Button size="small" danger disabled={busy}>
                        {t('myspace.ledger.markAllMissing', { n: report.fs_missing ?? 0 })}
                      </Button>
                    </Popconfirm>
                  </div>
                )}
                {((report.orphan_list as any[]) || []).length > 0 && (
                  <div style={{ marginTop: 8 }}>
                    <b>{t('myspace.ledger.orphanList')}</b>
                    <ul style={{ margin: '4px 0', paddingLeft: 18, maxHeight: 120, overflow: 'auto' }}>
                      {((report.orphan_list as any[]) || []).map((x, i) => (
                        <li key={`o${i}`}>{x?.owner_id}/{x?.path}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {((report.unledgered_list as any[]) || []).length > 0 && (
                  <div style={{ marginTop: 8 }}>
                    <b>{t('myspace.ledger.unledgeredList')}</b>
                    <ul style={{ margin: '4px 0', paddingLeft: 18, maxHeight: 120, overflow: 'auto' }}>
                      {((report.unledgered_list as any[]) || []).map((x, i) => (
                        <li key={`u${i}`}>{x?.owner_id}/{x?.path}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {((report.unowned_list as any[]) || []).length > 0 && (
                  <div style={{ marginTop: 8 }}>
                    <b>{t('myspace.ledger.unownedList')}</b>
                    <ul style={{ margin: '4px 0', paddingLeft: 18, maxHeight: 120, overflow: 'auto' }}>
                      {((report.unowned_list as any[]) || []).map((x, i) => (
                        <li key={`n${i}`}>{x?.owner_id}/{x?.path}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            }
          />
        </div>
      )}
    </div>
  );
}
