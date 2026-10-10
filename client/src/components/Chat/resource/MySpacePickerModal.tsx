import { useCallback, useEffect, useState } from "react";
import { Modal, Button, Segmented, Radio, Spin, Empty } from "antd";
import { useTranslation } from "react-i18next";
import api from "@/api";
import { FileTreeSelector } from "./FileTreeSelector";
import type { FileInfo } from "../types";
import styles from "./resource.module.less";

interface MySpacePickerModalProps {
  open: boolean;
  onClose: () => void;
  /** 确认选择（与现有 selectedFiles 合并去重） */
  onConfirm: (files: FileInfo[]) => void;
  /** 聊天 UUID（chat_id），"本会话"过滤依赖它（D1） */
  chatId?: string;
  /** 打开时的初始视图（"全部文件"走文件树，其余走台账） */
  initialView?: "tree" | "ledger";
  /** 打开时的初始过滤 */
  initialFilter?: FilterKey;
}

interface LedgerRecord {
  id?: number;
  file_path: string;
  size_bytes: number;
  source: string;
  session_id: string | null;
  chat_id?: string | null;
  created_at: string | number | null;
  mime_type?: string;
}

type FilterKey = "all" | "session" | "upload";

const SOURCE_LABEL: Record<string, string> = {
  upload: "上传",
  write_file: "生成",
  edit_file: "编辑",
  append_file: "追加",
  reconcile: "对账",
};

function basename(p: string): string {
  const idx = p.lastIndexOf("/");
  return idx >= 0 ? p.slice(idx + 1) : p;
}

function timeLabel(v: string | number | null): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "number") {
    const d = new Date(v * 1000);
    const p = (n: number) => String(n).padStart(2, "0");
    return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
  }
  return String(v).slice(5, 16).replace("T", " ");
}

/**
 * M4/T4.3：我的空间选择面板。
 * 两个视图：文件树浏览（复用 FileTreeSelector）+ 台账列表（GET /api/myfiles/records，
 * 支持 全部 / 本会话 / 我上传的 三种过滤）。
 *
 * "本会话"用 chat_id 过滤（D1）。旧数据的 chat_id 为 NULL，所以本会话只覆盖
 * 新产生的文件（D2）—— 这是接受的现状，不做回填。
 */
export default function MySpacePickerModal(props: MySpacePickerModalProps) {
  const { t } = useTranslation();
  const [view, setView] = useState<"tree" | "ledger">(props.initialView ?? "tree");
  const [filter, setFilter] = useState<FilterKey>(props.initialFilter ?? "all");
  const [records, setRecords] = useState<LedgerRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedMap, setSelectedMap] = useState<Map<string, FileInfo>>(new Map());

  const refreshLedger = useCallback(async () => {
    if (!props.open) return;
    setLoading(true);
    try {
      const params: Record<string, string> = { limit: "100" };
      if (filter === "upload") params.source = "upload";
      if (filter === "session" && props.chatId) params.chat_id = props.chatId;
      const qs = new URLSearchParams(params).toString();
      // 兼容两种响应形态：信封 {items:[...]} 或裸数组 [...]（网关/版本差异）
      const resp = (await api.get(`/myfiles/records?${qs}`)) as
        | { items?: LedgerRecord[] }
        | LedgerRecord[];
      let items: LedgerRecord[] = Array.isArray(resp)
        ? resp
        : Array.isArray(resp?.items)
          ? resp!.items
          : [];
      setRecords(items);
    } catch {
      setRecords([]);
    } finally {
      setLoading(false);
    }
  }, [props.open, filter, props.chatId]);

  useEffect(() => {
    if (view === "ledger") refreshLedger();
  }, [view, refreshLedger]);

  const toggleSelect = (f: FileInfo) => {
    setSelectedMap((prev) => {
      const next = new Map(prev);
      if (next.has(f.path)) next.delete(f.path);
      else next.set(f.path, f);
      return next;
    });
  };

  const handleLedgerPick = (rec: LedgerRecord) => {
    toggleSelect({
      id: rec.file_path,
      name: basename(rec.file_path),
      path: rec.file_path,
      type: "file",
      size: rec.size_bytes,
      mimeType: rec.mime_type,
    });
  };

  const handleTreeSelect = (files: FileInfo[]) => {
    setSelectedMap((prev) => {
      const next = new Map(prev);
      files.forEach((f) =>
        next.set(f.path, {
          id: f.path,
          name: f.name,
          path: f.path,
          type: "file",
          size: f.size,
          mimeType: f.mimeType,
        }),
      );
      return next;
    });
  };

  const handleClose = () => {
    setSelectedMap(new Map());
    setFilter(props.initialFilter ?? "all");
    setView(props.initialView ?? "tree");
    props.onClose();
  };

  const handleOk = () => {
    props.onConfirm(Array.from(selectedMap.values()));
    handleClose();
  };

  const filterOptions = [
    { label: t("resourcePicker.filterAll"), value: "all" as FilterKey },
    { label: t("resourcePicker.filterSession"), value: "session" as FilterKey },
    { label: t("resourcePicker.filterUpload"), value: "upload" as FilterKey },
  ];

  return (
    <Modal
      title={t("resourceMenu.mySpace")}
      open={props.open}
      onCancel={handleClose}
      width={560}
      destroyOnClose
      footer={
        <div className={styles.footerBar}>
          <span className={styles.footerCount}>
            {t("resourcePicker.selectedCount", { count: selectedMap.size })}
          </span>
          <span>
            <Button onClick={handleClose}>{t("common.cancel")}</Button>
            <Button type="primary" disabled={selectedMap.size === 0} onClick={handleOk}>
              {t("common.confirm")}
            </Button>
          </span>
        </div>
      }
    >
      <Segmented
        value={view}
        onChange={(v) => setView(v as "tree" | "ledger")}
        options={[
          { label: t("resourcePicker.tabTree"), value: "tree" },
          { label: t("resourcePicker.tabLedger"), value: "ledger" },
        ]}
        style={{ marginBottom: 12 }}
      />
      {view === "tree" ? (
        <div className={styles.modalBody}>
          <FileTreeSelector
            selected={Array.from(selectedMap.values())}
            onSelect={handleTreeSelect}
          />
        </div>
      ) : (
        <>
          <div className={styles.filterBar}>
            <Radio.Group
              size="small"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              options={filterOptions}
            />
          </div>
          <Spin spinning={loading}>
            {records.length === 0 && !loading ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("resourcePicker.noRecords")} />
            ) : (
              <div className={styles.recordList}>
                {records.map((rec) => (
                  <div
                    key={rec.id ?? rec.file_path}
                    className={styles.recordRow}
                    onClick={() => handleLedgerPick(rec)}
                    role="checkbox"
                    aria-checked={selectedMap.has(rec.file_path)}
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") handleLedgerPick(rec);
                    }}
                  >
                    <span
                      style={{
                        width: 14,
                        height: 14,
                        borderRadius: 3,
                        border: selectedMap.has(rec.file_path)
                          ? "1px solid transparent"
                          : "1px solid var(--color-border, rgba(0,0,0,0.15))",
                        background: selectedMap.has(rec.file_path)
                          ? "var(--color-primary, #1677ff)"
                          : "transparent",
                        flexShrink: 0,
                        display: "inline-flex",
                        alignItems: "center",
                        justifyContent: "center",
                        color: "#fff",
                        fontSize: 10,
                      }}
                    >
                      {selectedMap.has(rec.file_path) ? "✓" : ""}
                    </span>
                    <span className={styles.recordName} title={rec.file_path}>
                      {basename(rec.file_path)}
                    </span>
                    <span className={styles.recordMeta}>
                      {SOURCE_LABEL[rec.source] ?? rec.source}
                      {timeLabel(rec.created_at) ? ` · ${timeLabel(rec.created_at)}` : ""}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </Spin>
        </>
      )}
    </Modal>
  );
}
