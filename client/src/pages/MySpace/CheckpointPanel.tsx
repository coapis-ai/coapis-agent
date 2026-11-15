import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Modal,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useTranslation } from 'react-i18next';
import {
  checkpointsApi,
  type CheckpointListResponse,
  type CheckpointPreview,
  type CheckpointSummary,
} from '../../api/modules/checkpoints';

const { Text } = Typography;

/** 预览表的一行 = 后端 diff 项（先声明，列定义在组件里要用到） */
/** 检查点类型 → 颜色（pre_restore 是恢复前自动留底，视觉上要和手工快照分开） */
const KIND_COLORS: Record<string, string> = {
  manual: 'blue',
  pre_restore: 'orange',
  auto: 'green',
};

function fmtTime(v?: number | null): string {
  const sec = Number(v);
  if (!Number.isFinite(sec) || sec <= 0) return '-';
  const d = new Date(sec * 1000);
  if (Number.isNaN(d.getTime())) return '-';
  const p = (n: number) => String(n).padStart(2, '0');
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function fmtBytes(v?: number | null): string {
  const n = Number(v);
  if (!Number.isFinite(n) || n < 0) return '-';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

/**
 * 检查点抽屉（B5-A）—— 列表 + 预览 diff + 恢复二次确认。
 *
 * 三条硬规矩（对齐后端 D13）：
 * 1. 功能默认关：后端 404 时这里明说开关名，不伪装成"没有数据"；
 * 2. 预览 = 只读演练，UI 上写死「不会影响任何文件」；
 * 3. 恢复必须二次确认，确认框里点名「会覆盖哪些文件」+「恢复前自动留底」。
 */
export default function CheckpointPanel() {
  const { t } = useTranslation();
  const [data, setData] = useState<CheckpointListResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [preview, setPreview] = useState<{ cp: CheckpointSummary; plan: CheckpointPreview } | null>(
    null,
  );
  const [busy, setBusy] = useState('');

  const refresh = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await checkpointsApi.list({ limit: 100 });
      setData(res);
      if (res.note) setError('');
    } catch (e) {
      setError(String((e as Error)?.message || e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const openPreview = useCallback(async (cp: CheckpointSummary) => {
    setBusy(cp.checkpoint_id);
    setError('');
    try {
      const plan = await checkpointsApi.preview({ checkpoint_id: cp.checkpoint_id });
      setPreview({ cp, plan });
    } catch (e) {
      setError(String((e as Error)?.message || e));
    } finally {
      setBusy('');
    }
  }, []);

  const doRestore = useCallback(
    async (cp: CheckpointSummary) => {
      setBusy(cp.checkpoint_id);
      try {
        const res = await checkpointsApi.restore({
          checkpoint_id: cp.checkpoint_id,
          confirm: true,
        });
        Modal.info({
          title: t('myspace.checkpointRestoredTitle', 'Restored'),
          content: (
            <div>
              <p>
                {t('myspace.checkpointRestoredFiles', 'Files restored')}: {res.restored.length}
                {' · '}
                {fmtBytes(res.total_bytes)}
              </p>
              {res.pre_restore_checkpoint_id ? (
                <p style={{ wordBreak: 'break-all' }}>
                  {t('myspace.checkpointPreRestore', 'Pre-restore snapshot')}:{' '}
                  {res.pre_restore_checkpoint_id}
                </p>
              ) : null}
            </div>
          ),
        });
        void refresh();
      } catch (e) {
        setError(String((e as Error)?.message || e));
      } finally {
        setBusy('');
      }
    },
    [refresh, t],
  );

  const askRestore = useCallback(
    (cp: CheckpointSummary) => {
      Modal.confirm({
        title: t('myspace.checkpointConfirmTitle', 'Restore this checkpoint?'),
        content: (
          <div>
            <p>
              {t(
                'mySpace.checkpointConfirmBody',
                'Files in the workspace will be overwritten with the snapshot content. Files added after the snapshot are kept.',
              )}
            </p>
            <p>
              {t('myspace.checkpointConfirmCount', 'Files to overwrite')}: {cp.file_count ?? '-'}
              {' · '}
              {fmtBytes(cp.total_bytes)}
            </p>
            <p>
              {t(
                'mySpace.checkpointConfirmSafety',
                'A snapshot of the current state is taken first, so this can be undone.',
              )}
            </p>
          </div>
        ),
        okText: t('myspace.checkpointConfirmOk', 'Restore'),
        okType: 'primary',
        cancelText: t('common.cancel', 'Cancel'),
        onOk: () => doRestore(cp),
      });
    },
    [doRestore, t],
  );

  const columns = useMemo<ColumnsType<CheckpointSummary>>(
    () => [
      {
        title: t('myspace.checkpointColTime', 'Time'),
        dataIndex: 'created_at',
        render: (v: number) => <Text>{fmtTime(v)}</Text>,
      },
      {
        title: t('myspace.checkpointColKind', 'Kind'),
        dataIndex: 'kind',
        render: (v: string) => <Tag color={KIND_COLORS[v] || 'default'}>{v}</Tag>,
      },
      {
        title: t('myspace.checkpointColFiles', 'Files'),
        render: (_: unknown, row: CheckpointSummary) => (
          <Text>
            {row.file_count ?? 0} · {fmtBytes(row.total_bytes)}
          </Text>
        ),
      },
      {
        title: t('myspace.checkpointColSession', 'Session'),
        dataIndex: 'session',
        render: (v?: string | null) => (
          <Text type={v ? undefined : 'secondary'} style={{ fontSize: 12 }}>
            {v || '-'}
          </Text>
        ),
      },
      {
        title: t('myspace.checkpointColNote', 'Note'),
        dataIndex: 'note',
        render: (v?: string | null) => <Text style={{ fontSize: 12 }}>{v || '-'}</Text>,
      },
      {
        title: t('myspace.checkpointColOps', 'Ops'),
        render: (_: unknown, row: CheckpointSummary) => (
          <Space size={4}>
            <Button size="small" loading={busy === row.checkpoint_id} onClick={() => void openPreview(row)}>
              {t('myspace.checkpointPreview', 'Preview')}
            </Button>
            <Button
              size="small"
              danger
              disabled={busy === row.checkpoint_id}
              onClick={() => askRestore(row)}
            >
              {t('myspace.checkpointRestore', 'Restore')}
            </Button>
          </Space>
        ),
      },
    ],
    [askRestore, busy, openPreview, t],
  );

  const diffColumns = useMemo<ColumnsType<CheckpointDiffRow>>(
    () => [
      {
        title: t('myspace.checkpointDiffKind', 'Change'),
        dataIndex: 'kind',
        render: (v: string) => (
          <Tag
            color={
              v === 'restore' ? 'red' : v === 'extra' ? 'gold' : v === 'missing' ? 'volcano' : 'default'
            }
          >
            {v}
          </Tag>
        ),
      },
      {
        title: t('myspace.checkpointDiffPath', 'Path'),
        dataIndex: 'rel',
        render: (v: string) => <Text style={{ fontSize: 12 }}>{v}</Text>,
      },
      {
        title: t('myspace.checkpointDiffSize', 'Size'),
        dataIndex: 'size_bytes',
        render: (v?: number | null) => <Text style={{ fontSize: 12 }}>{fmtBytes(v)}</Text>,
      },
    ],
    [t],
  );

  const enabled = data?.enabled ?? false;

  return (
    <div>
      <Card
        size="small"
        title={t('myspace.checkpointTitle', 'Checkpoints')}
        extra={
          <Button size="small" onClick={() => void refresh()} loading={loading}>
            {t('common.refresh', 'Refresh')}
          </Button>
        }
      >
        {!enabled ? (
          <Alert
            type="info"
            showIcon
            message={t('myspace.checkpointDisabledTitle', 'Checkpoints are off')}
            description={
              <div>
                <p>
                  {t(
                    'mySpace.checkpointDisabledBody',
                    'File-level snapshots are disabled by default. Turn them on with the server switch COAPIS_CHECKPOINTS_ENABLED=true.',
                  )}
                </p>
                {data?.note ? <Text type="secondary">{data.note}</Text> : null}
              </div>
            }
          />
        ) : (
          <>
            {error ? (
              <Alert
                type="error"
                showIcon
                closable
                style={{ marginBottom: 8 }}
                message={error}
              />
            ) : null}
            <Table
              rowKey="checkpoint_id"
              size="small"
              loading={loading}
              columns={columns}
              dataSource={data?.items || []}
              pagination={{ pageSize: 10 }}
            />
          </>
        )}
      </Card>

      <Modal
        open={preview !== null}
        title={t('myspace.checkpointPreviewTitle', 'Restore preview (read-only)')}
        onCancel={() => setPreview(null)}
        footer={[
          <Button key="close" onClick={() => setPreview(null)}>
            {t('common.close', 'Close')}
          </Button>,
          <Button
            key="go"
            type="primary"
            danger
            disabled={!preview?.plan.writable}
            onClick={() => {
              const cp = preview?.cp;
              setPreview(null);
              if (cp) askRestore(cp);
            }}
          >
            {t('myspace.checkpointRestore', 'Restore')}
          </Button>,
        ]}
      >
        {preview ? (
          <div>
            <Alert
              type={preview.plan.writable ? 'warning' : 'error'}
              showIcon
              style={{ marginBottom: 8 }}
              message={
                preview.plan.writable
                  ? t(
                      'mySpace.checkpointPreviewNote',
                      'Preview only — nothing on disk was touched.',
                    )
                  : t(
                      'mySpace.checkpointPreviewBlocked',
                      'Snapshot content is incomplete, restore is blocked.',
                    )
              }
            />
            <p style={{ fontSize: 12 }}>
              {t('myspace.checkpointPreviewCount', 'Files to restore')}:{' '}
              {preview.plan.to_restore_count ?? 0} · {fmtBytes(preview.plan.to_restore_bytes)}
            </p>
            <Table
              rowKey="rel"
              size="small"
              columns={diffColumns}
              dataSource={preview.plan.diffs.map((d) => ({ ...d, key: d.rel }))}
              pagination={{ pageSize: 10 }}
            />
          </div>
        ) : null}
      </Modal>
    </div>
  );
}

type CheckpointDiffRow = CheckpointPreview['diffs'][number];
