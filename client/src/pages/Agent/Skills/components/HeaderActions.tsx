import { Button, Tooltip } from "@agentscope-ai/design";
import {
  CloseOutlined,
  DeleteOutlined,
  ImportOutlined,
  PlusOutlined,
  ReloadOutlined,
  SwapOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { useUser } from "../../../../contexts/UserContext";
import styles from "../index.module.less";

interface HeaderActionsProps {
  batchModeEnabled: boolean;
  selectedSkills: Set<string>;
  loading: boolean;
  uploading: boolean;
  fileInputRef: React.RefObject<HTMLInputElement>;
  onSelectAll: () => void;
  onClearSelection: () => void;
  onUploadToPool: (names: string[]) => void;
  onBatchDelete: () => void;
  onToggleBatchMode: () => void;
  onHardRefresh: () => void;
  onOpenUploadPool: () => void;
  onUploadClick: () => void;
  onImportHub: () => void;
  onCreate: () => void;
  onFileChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
}

export function HeaderActions({
  batchModeEnabled,
  selectedSkills,
  loading,
  uploading,
  fileInputRef,
  onSelectAll,
  onClearSelection,
  onUploadToPool,
  onBatchDelete,
  onToggleBatchMode,
  onHardRefresh,
  onOpenUploadPool,
  onUploadClick,
  onImportHub,
  onCreate,
  onFileChange,
}: HeaderActionsProps) {
  const { t } = useTranslation();
  const { isAdmin } = useUser();

  return (
    <div className={styles.headerRight}>
      <input
        type="file"
        accept=".zip"
        ref={fileInputRef}
        onChange={onFileChange}
        style={{ display: "none" }}
      />
      {batchModeEnabled ? (
        <div className={styles.batchActions}>
          <>
            <span className={styles.batchCount}>
              {t("skills.selectedCount", { count: selectedSkills.size })}
            </span>
            <Button type="default" onClick={onSelectAll}>
              {t("skills.selectAll")}
            </Button>
            <Button
              type="default"
              onClick={onClearSelection}
              icon={<CloseOutlined />}
            >
              {t("skills.clearSelection")}
            </Button>
            {isAdmin ? (
              <Tooltip title={t("skills.uploadToPoolHint")}>
                <Button
                  type="default"
                  className={styles.primaryTransferButton}
                  onClick={() => {
                    const names = Array.from(selectedSkills);
                    if (names.length === 0) return;
                    onClearSelection();
                    void onUploadToPool(names);
                  }}
                  icon={<SwapOutlined />}
                >
                  {t("skills.uploadToPool")}
                </Button>
              </Tooltip>
            ) : null}
            <Button danger icon={<DeleteOutlined />} onClick={onBatchDelete}>
              {t("common.delete")} ({selectedSkills.size})
            </Button>
          </>
          <Button type="primary" onClick={onToggleBatchMode}>
            {t("skills.exitBatch")}
          </Button>
        </div>
      ) : (
        <>
          <div className={styles.headerActionsLeft}>
            <Tooltip title={t("skills.refreshHint")}>
              <Button
                type="default"
                icon={<ReloadOutlined spin={loading} />}
                onClick={onHardRefresh}
                disabled={loading}
              />
            </Tooltip>
            {isAdmin ? (
              <Tooltip title={t("skills.uploadToPoolHint")}>
                <Button
                  type="default"
                  className={styles.primaryTransferButton}
                  onClick={onOpenUploadPool}
                  icon={<SwapOutlined />}
                >
                  {t("skills.uploadToPool")}
                </Button>
              </Tooltip>
            ) : null}
          </div>
          <div className={styles.headerActionsRight}>
            <Tooltip title={t("skills.uploadZipHint")}>
              <Button
                type="default"
                className={styles.creationActionButton}
                onClick={onUploadClick}
                icon={<UploadOutlined />}
                loading={uploading}
                disabled={uploading}
              >
                {t("skills.uploadZip")}
              </Button>
            </Tooltip>
            <Tooltip title={t("skills.importHubHint")}>
              <Button
                type="default"
                className={styles.creationActionButton}
                onClick={onImportHub}
                icon={<ImportOutlined />}
              >
                {t("skills.importHub")}
              </Button>
            </Tooltip>
            <Button type="primary" onClick={onToggleBatchMode}>
              {t("skills.batchOperation")}
            </Button>
            <Tooltip title={t("skills.createSkillHint")}>
              <Button
                type="primary"
                className={styles.primaryActionButton}
                onClick={onCreate}
                icon={<PlusOutlined />}
              >
                {t("skills.createSkill")}
              </Button>
            </Tooltip>
          </div>
        </>
      )}
    </div>
  );
}
