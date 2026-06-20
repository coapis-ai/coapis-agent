import React from "react";
import { Button, Card, Input } from "@agentscope-ai/design";
import { UndoOutlined, SaveOutlined } from "@ant-design/icons";
import type { MarkdownFile } from "../../../../api/types";
import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

interface FileEditorProps {
  selectedFile: MarkdownFile | null;
  fileContent: string;
  loading: boolean;
  hasChanges: boolean;
  onContentChange: (content: string) => void;
  onSave: () => void;
  onReset: () => void;
}

export const FileEditor: React.FC<FileEditorProps> = ({
  selectedFile,
  fileContent,
  loading,
  hasChanges,
  onContentChange,
  onSave,
  onReset,
}) => {
  const { t } = useTranslation();

  return (
    <div className={styles.fileEditor}>
      <Card className={styles.editorCard}>
        {selectedFile ? (
          <>
            <div className={styles.editorHeader}>
              <div>
                <div className={styles.fileName}>{selectedFile.filename}</div>
                <div className={styles.filePath}>{selectedFile.path}</div>
              </div>
              <div className={styles.buttonGroup}>
                <Button
                  size="small"
                  onClick={onReset}
                  disabled={!hasChanges}
                  icon={<UndoOutlined />}
                >
                  {t("common.reset")}
                </Button>
                <Button
                  type="primary"
                  size="small"
                  onClick={onSave}
                  disabled={!hasChanges}
                  loading={loading}
                  icon={<SaveOutlined />}
                >
                  {t("common.save")}
                </Button>
              </div>
            </div>

            <div className={styles.editorContent}>
              <div className={styles.contentLabel}>
                <div>{t("common.content")}</div>
              </div>
              <Input.TextArea
                value={fileContent}
                onChange={(e) => onContentChange(e.target.value)}
                className={styles.textarea}
                placeholder={t("workspace.fileContent")}
              />
            </div>
          </>
        ) : (
          <div className={styles.emptyState}>{t("workspace.selectFile")}</div>
        )}
        <p className={styles.attribution}>{t("workspace.attribution")}</p>
      </Card>
    </div>
  );
};
