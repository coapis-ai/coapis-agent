import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Tabs } from "@agentscope-ai/design";
import {
  SkillCard,
  SkillDrawer,
  PoolTransferModal,
  ImportHubModal,
  HeaderActions,
  SkillsToolbar,
  SkillListItem,
  CategoryManager,
} from "./components";
import { PageHeader } from "@/components/PageHeader";
import { useSkillsPage } from "./useSkillsPage";
import { usePermission } from "@/hooks/usePermission";
import { GlobalSkillsTab } from "./GlobalSkillsTab";
import styles from "./index.module.less";

function SkillsPage() {
  const { t } = useTranslation();
  const { hasPermission } = usePermission();
  const [activeTab, setActiveTab] = useState<"my" | "global">("my");
  const {
    skills,
    hasMore,
    sentinelRef,
    poolSkills,
    allTags,
    sortedSkills,
    conflictRenameModal,
    loading,
    uploading,
    importing,
    drawerOpen,
    importModalOpen,
    setImportModalOpen,
    editingSkill,
    form,
    fileInputRef,
    poolModal,
    setPoolModal,
    selectedSkills,
    batchModeEnabled,
    viewMode,
    setViewMode,
    filterOpen,
    setFilterOpen,
    searchQuery,
    setSearchQuery,
    searchTags,
    setSearchTags,
    handleCreate,
    handleEdit,
    handleToggleEnabled,
    handleDelete,
    handleDrawerClose,
    handleSubmit,
    handleUploadToPool,
    handleExportZip,
    handleBatchDelete,
    handleUploadClick,
    handleFileChange,
    handleConfirmImport,
    closeImportModal,
    toggleSelect,
    selectAll,
    clearSelection,
    toggleBatchMode,
    toggleEnabled,
    refreshSkills,
    hardRefresh,
    cancelImport,
    categoryOptions,
    refreshCategories,
  } = useSkillsPage();

  const [catManagerOpen, setCatManagerOpen] = useState(false);

  return (
    <div className={styles.skillsPage}>
      <PageHeader
        items={[{ title: "设置" }, { title: t("skills.title") }]}
      />

      <Tabs
        activeKey={activeTab}
        onChange={(key) => setActiveTab(key as "my" | "global")}
        items={[
          {
            key: "my",
            label: t("skills.mySkills"),
            children: (
              <>
                <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 12 }}>
                  <HeaderActions
                    batchModeEnabled={batchModeEnabled}
                    selectedSkills={selectedSkills}
                    loading={loading}
                    uploading={uploading}
                    fileInputRef={fileInputRef}
                    onSelectAll={selectAll}
                    onClearSelection={clearSelection}
                    onUploadToPool={handleUploadToPool}
                    onBatchDelete={handleBatchDelete}
                    onToggleBatchMode={toggleBatchMode}
                    onHardRefresh={hardRefresh}
                    onOpenUploadPool={() => setPoolModal("upload")}
                    onUploadClick={handleUploadClick}
                    onImportHub={() => setImportModalOpen(true)}
                    onCreate={handleCreate}
                    onFileChange={handleFileChange}
                    canWrite={hasPermission("skills:write")}
                    canDelete={hasPermission("skills:delete")}
                  />
                </div>

                <ImportHubModal
                  open={importModalOpen}
                  importing={importing}
                  onCancel={closeImportModal}
                  onConfirm={handleConfirmImport}
                  cancelImport={cancelImport}
                  hint={t("skillPool.externalHubHint")}
                />

                {!loading && skills.length > 0 && (
                  <SkillsToolbar
                    searchQuery={searchQuery}
                    onSearchChange={setSearchQuery}
                    searchTags={searchTags}
                    onTagsChange={setSearchTags}
                    allTags={allTags}
                    filterOpen={filterOpen}
                    onFilterOpenChange={setFilterOpen}
                    viewMode={viewMode}
                    onViewModeChange={setViewMode}
                    onManageCategories={() => setCatManagerOpen(true)}
                  />
                )}

                <div className={styles.contentScroll}>
                {loading ? (
                  <div className={styles.loading}>
                    <span className={styles.loadingText}>{t("common.loading")}</span>
                  </div>
                ) : skills.length === 0 ? (
                  <div className={styles.emptyState}>
                    <div className={styles.emptyStateBadge}>
                      {t("skills.emptyStateBadge")}
                    </div>
                    <h2 className={styles.emptyStateTitle}>
                      {t("skills.emptyStateTitle")}
                    </h2>
                    <p className={styles.emptyStateText}>{t("skills.emptyStateText")}</p>
                  </div>
                ) : sortedSkills.length === 0 ? (
                  <div className={styles.noSearchResults}>
                    <span className={styles.noSearchResultsIcon}>🔍</span>
                    <span className={styles.noSearchResultsText}>
                      {t("skills.noSearchResults")}
                    </span>
                  </div>
                ) : viewMode === "card" ? (
                  <div className={styles.skillsGrid}>
                    {sortedSkills.map((skill) => (
                      <SkillCard
                        key={skill.name}
                        skill={skill}
                        selected={
                          batchModeEnabled ? selectedSkills.has(skill.name) : undefined
                        }
                        onSelect={() => toggleSelect(skill.name)}
                        onClick={() => handleEdit(skill)}
                        onMouseEnter={() => {}}
                        onMouseLeave={() => {}}
                        onToggleEnabled={(e) => handleToggleEnabled(skill, e)}
                        onDelete={(e) => handleDelete(skill, e)}
                      />
                    ))}
                    {hasMore && <div ref={sentinelRef} style={{ height: 1 }} />}
                  </div>
                ) : (
                  <div className={styles.skillsList}>
                    {sortedSkills.map((skill) => (
                      <SkillListItem
                        key={skill.name}
                        skill={skill}
                        batchModeEnabled={batchModeEnabled}
                        isSelected={selectedSkills.has(skill.name)}
                        onSelect={() => toggleSelect(skill.name)}
                        onClick={() => handleEdit(skill)}
                        onToggleEnabled={async () => {
                          await toggleEnabled(skill);
                          await refreshSkills();
                        }}
                        onDelete={() => handleDelete(skill)}
                      />
                    ))}
                    {hasMore && <div ref={sentinelRef} style={{ height: 1 }} />}
                  </div>
                )}
                </div>

                <PoolTransferModal
                  mode={poolModal}
                  skills={skills}
                  poolSkills={poolSkills}
                  onCancel={() => setPoolModal(null)}
                  onUpload={handleUploadToPool}
                  onDownload={async () => {}}
                />

                {conflictRenameModal}

                <SkillDrawer
                  open={drawerOpen}
                  editingSkill={editingSkill}
                  form={form}
                  availableTags={allTags}
                  categoryOptions={categoryOptions}
                  onClose={handleDrawerClose}
                  onSubmit={handleSubmit}
                  onExport={handleExportZip}
                />

                <CategoryManager
                  open={catManagerOpen}
                  onClose={() => setCatManagerOpen(false)}
                  categories={categoryOptions}
                  onRefresh={refreshCategories}
                />
              </>
            ),
          },
          {
            key: "global",
            label: t("skills.globalSkills"),
            children: <GlobalSkillsTab />,
          },
        ]}
      />
    </div>
  );
}

export default SkillsPage;
