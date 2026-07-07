import { Button, Tabs } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { useSecurityPage } from "./useSecurityPage";
import { PermissionGuard } from "@/components/PermissionGuard";
import {
  RuleModal,
  PreviewModal,
  SkillScannerSection,
  FileGuardSection,
  AllowNoAuthHostsTab,
  InputGuardTab,
  AdvancedRulesTab,
} from "./components";
import { CommandClassificationSection } from "./components/ToolGuardTab";
import { PageHeader } from "@/components/PageHeader";
import styles from "./index.module.less";

function SecurityPage() {
  const { t } = useTranslation();

  const {
    activeTab,
    setActiveTab,
    globalRules: _unusedGlobalRules,
    customRules,
    toggleRule: _unusedToggleRule,
    deleteCustomRule: _unusedDeleteCustomRule,
    shellEvasionChecks,
    toggleShellEvasionCheck,
    editModal,
    setEditModal,
    editingRule,
    editForm,
    handleEditSave,
    previewRule,
    setPreviewRule,
    fileGuardHandlers,
    onFileGuardHandlersReady,
    allowNoAuthHostsHandlers,
    onAllowNoAuthHostsHandlersReady,
    loading,
    error,
    fetchAll,
  } = useSecurityPage();

  // Loading state
  if (loading) {
    return (
      <div className={styles.securityPage}>
        <div className={styles.centerState}>
          <span className={styles.stateText}>{t("common.loading")}</span>
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className={styles.securityPage}>
        <div className={styles.centerState}>
          <span className={styles.stateTextError}>{error}</span>
          <Button size="small" onClick={fetchAll} style={{ marginTop: 12 }}>
            {t("environments.retry")}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.securityPage}>
      <PageHeader
        parent={t("security.parent")}
        current={t("security.security")}
      />

      <div className={styles.content}>
        <Tabs
          className={styles.mainTabs}
          activeKey={activeTab}
          onChange={setActiveTab}
          items={[
            {
              key: "commandClassification",
              label: (
                <span className={styles.tabLabel}>
                  {t("security.commandClassification.title", "命令分级")}
                </span>
              ),
              children: <CommandClassificationSection />,
            },
            {
              key: "advancedRules",
              label: (
                <span className={styles.tabLabel}>
                  {t("security.advancedRules.title", "高级检查规则")}
                </span>
              ),
              children: (
                <AdvancedRulesTab
                  shellEvasionChecks={shellEvasionChecks}
                  toggleShellEvasionCheck={toggleShellEvasionCheck}
                />
              ),
            },
            {
              key: "fileGuard",
              label: (
                <span className={styles.tabLabel}>
                  {t("security.fileGuard.title")}
                </span>
              ),
              children: (
                <div className={styles.tabContent}>
                  <div className={styles.sectionFileGuardContainer}>
                    <p className={styles.tabDescription}>
                      {t("security.fileGuard.description")}
                    </p>
                    <FileGuardSection onSave={onFileGuardHandlersReady} />
                  </div>
                </div>
              ),
            },
            {
              key: "skillScanner",
              label: (
                <span className={styles.tabLabel}>
                  {t("security.skillScanner.title")}
                </span>
              ),
              children: (
                <div className={styles.tabContent}>
                  <div className={styles.sectionSkillScannerContainer}>
                    <p className={styles.tabDescription}>
                      {t("security.skillScanner.description")}
                    </p>
                    <SkillScannerSection />
                  </div>
                </div>
              ),
            },
            {
              key: "allowNoAuthHosts",
              label: (
                <span className={styles.tabLabel}>
                  {t("security.allowNoAuthHosts.title")}
                </span>
              ),
              children: (
                <AllowNoAuthHostsTab onSave={onAllowNoAuthHostsHandlersReady} />
              ),
            },
            {
              key: "inputGuard",
              label: (
                <span className={styles.tabLabel}>
                  {t("security.inputGuard.title")}
                </span>
              ),
              children: <InputGuardTab />,
            },
          ]}
        />
      </div>

      {activeTab === "fileGuard" && fileGuardHandlers && (
        <div className={styles.footerButtons}>
          <Button
            onClick={fileGuardHandlers.reset}
            disabled={fileGuardHandlers.saving}
            style={{ marginRight: 8 }}
          >
            {t("common.reset")}
          </Button>
          <PermissionGuard module="security" action="write">
            <Button
              type="primary"
              onClick={fileGuardHandlers.save}
              loading={fileGuardHandlers.saving}
            >
              {t("common.save")}
            </Button>
          </PermissionGuard>
        </div>
      )}

      {activeTab === "allowNoAuthHosts" && allowNoAuthHostsHandlers && (
        <div className={styles.footerButtons}>
          <Button
            onClick={allowNoAuthHostsHandlers.reset}
            disabled={allowNoAuthHostsHandlers.saving}
            style={{ marginRight: 8 }}
          >
            {t("common.reset")}
          </Button>
          <Button
            type="primary"
            onClick={allowNoAuthHostsHandlers.save}
            loading={allowNoAuthHostsHandlers.saving}
          >
            {t("common.save")}
          </Button>
        </div>
      )}

      <RuleModal
        open={editModal}
        editingRule={editingRule}
        existingRuleIds={customRules.map((r) => r.id)}
        onOk={handleEditSave}
        onCancel={() => setEditModal(false)}
        form={editForm}
      />

      <PreviewModal rule={previewRule} onClose={() => setPreviewRule(null)} />
    </div>
  );
}

export default SecurityPage;
