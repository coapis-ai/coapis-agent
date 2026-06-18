/**
 * Backups & Cleanup page — thin assembly layer.
 * Tabs: [备份管理] [清理与归档]
 */
import { useCallback, useEffect, useState } from "react";
import { Button, Spin, Tabs } from "antd";
import { PlusOutlined, DeleteOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import api, { agentsApi } from "@/api";
import { PageHeader } from "@/components/PageHeader";
import { useAppMessage } from "@/hooks/useAppMessage";
import type { BackupMeta } from "@/api/types/backup";
import type { AgentSummary } from "@/api/types/agents";

import BackupTable from "./list/BackupTable";
import BackupToolbar from "./list/BackupToolbar";
import ImportButton from "./import/ImportButton";
import ImportConflictModal from "./import/ImportConflictModal";
import { useImportFlow } from "./import/useImportFlow";
import CreateBackupModal from "./create/CreateBackupModal";
import SilentBackupModal from "./create/SilentBackupModal";
import PreRestoreConfirmModal from "./restore/PreRestoreConfirmModal";
import RestoreBackupModal from "./restore/RestoreBackupModal";
import { useRestoreFlow } from "./restore/useRestoreFlow";
import CleanupTab from "./cleanup/CleanupTab";
import styles from "./index.module.less";

export default function BackupsPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [loading, setLoading] = useState(true);
  const [backups, setBackups] = useState<BackupMeta[]>([]);
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [activeTab, setActiveTab] = useState("backup");

  /** Fetches backups and agents in parallel; agents is non-blocking (backups
   *  page works without it — agents list is only used for display). */
  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const backupRes = await api.listBackups();
      setBackups(backupRes);
      // Non-blocking: agents list is optional (used for display only)
      agentsApi
        .listAgents()
        .then((res) => setAgents(res.agents))
        .catch(() => {});
    } catch {
      message.error(t("backup.loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [message, t]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const importFlow = useImportFlow({ onSuccess: fetchData });
  const restoreFlow = useRestoreFlow();

  if (loading) {
    return (
      <div className={styles.page}>
        <div className={styles.centerState}>
          <Spin />
        </div>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      <PageHeader
        parent={t("nav.settings")}
        current={t("backup.title")}
        extra={
          activeTab === "backup" ? (
            <div className={styles.headerRight}>
              <ImportButton onPick={importFlow.handleImport} />
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={() => setCreateOpen(true)}
              >
                {t("backup.create")}
              </Button>
            </div>
          ) : undefined
        }
      />

      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: "backup",
            label: (
              <span>
                <PlusOutlined style={{ marginRight: 4 }} />
                备份管理
              </span>
            ),
            children: (
              <div className={styles.content}>
                <BackupToolbar
                  searchQuery={searchQuery}
                  onSearchChange={setSearchQuery}
                />
                <BackupTable
                  backups={backups}
                  searchQuery={searchQuery}
                  onRestore={restoreFlow.handleRestore}
                  onRefresh={fetchData}
                />
              </div>
            ),
          },
          {
            key: "cleanup",
            label: (
              <span>
                <DeleteOutlined style={{ marginRight: 4 }} />
                清理与归档
              </span>
            ),
            children: <CleanupTab />,
          },
        ]}
      />

      {/* Import flow */}
      <ImportConflictModal
        conflictMeta={importFlow.conflictMeta}
        onChoice={importFlow.handleConflictChoice}
        onCancel={importFlow.clearConflict}
      />

      {/* Create flow */}
      <CreateBackupModal
        open={createOpen}
        agents={agents}
        onClose={() => setCreateOpen(false)}
        onSuccess={fetchData}
      />

      {/* Restore flow */}
      <PreRestoreConfirmModal
        target={restoreFlow.preRestoreConfirmTarget}
        onCancel={restoreFlow.cancelPreRestore}
        onNoBackup={restoreFlow.confirmRestoreWithoutBackup}
        onYesBackup={restoreFlow.confirmRestoreWithBackup}
      />

      <SilentBackupModal
        target={restoreFlow.preRestoreBackupTarget}
        agentIds={agents.map((a) => a.id)}
        onClose={restoreFlow.onPreRestoreBackupClose}
        onSuccess={restoreFlow.onPreRestoreBackupSuccess}
      />

      {restoreFlow.restoreTarget && (
        <RestoreBackupModal
          backup={restoreFlow.restoreTarget}
          agents={agents}
          open={!!restoreFlow.restoreTarget}
          onClose={() => restoreFlow.setRestoreTarget(null)}
          onSuccess={fetchData}
        />
      )}
    </div>
  );
}
