/**
 * 全局技能 Tab — 复用 useSkillPool hook，包含完整的导入/创建/批量管理功能
 * 已移除"广播到智能体"功能（产品自动多级技能适配）
 */
import { useTranslation } from "react-i18next";
import {
  AppstoreOutlined,
  CloseOutlined,
  DeleteOutlined,
  ImportOutlined,
  PlusOutlined,
  ReloadOutlined,
  SyncOutlined,
  UnorderedListOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import { Button, Tooltip } from "@agentscope-ai/design";
import { ImportHubModal } from "./components/ImportHubModal";
import { SkillFilterDropdown } from "./components/SkillFilterDropdown";
import {
  ImportBuiltinModal,
  PoolSkillCard,
  PoolSkillListItem,
  PoolSkillDrawer,
} from "../../Settings/SkillPool/components";
import { getBuiltinNoticeLines } from "../../Settings/SkillPool/builtinNotice";
import { useSkillPool } from "../../Settings/SkillPool/useSkillPool";
import { useProgressiveRender } from "../../../hooks/useProgressiveRender";
import { useUser } from "../../../contexts/UserContext";
import styles from "./index.module.less";

export function GlobalSkillsTab() {
  const { t } = useTranslation();
  const { isAdmin } = useUser();
  const pool = useSkillPool();
  const builtinNoticeLines = getBuiltinNoticeLines(pool.builtinNotice, t);

  const {
    visibleItems: visibleSkills,
    hasMore,
    sentinelRef,
  } = useProgressiveRender(pool.sortedSkills);

  return (
    <>
      {/* === 工具栏 === */}
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 12, gap: 8 }}>
        <input
          type="file"
          accept=".zip"
          ref={pool.zipInputRef}
          onChange={pool.handleZipImport}
          style={{ display: "none" }}
        />
        {pool.batchModeEnabled ? (
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 13, color: "var(--text-color-secondary, #8c8c8c)", whiteSpace: "nowrap" }}>
              {t("skills.selectedCount", { count: pool.selectedPoolSkills.size })}
            </span>
            <Button type="default" onClick={pool.selectAllPool}>
              {t("skills.selectAll")}
            </Button>
            <Button type="default" onClick={pool.clearPoolSelection} icon={<CloseOutlined />}>
              {t("skills.clearSelection")}
            </Button>
            {isAdmin && (
              <Button danger icon={<DeleteOutlined />} onClick={pool.handleBatchDeletePool}>
                {t("common.delete")} ({pool.selectedPoolSkills.size})
              </Button>
            )}
            <Button type="primary" onClick={pool.toggleBatchMode}>
              {t("skills.exitBatch")}
            </Button>
          </div>
        ) : (
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <Tooltip title={t("skills.refreshHint")}>
              <Button
                type="default"
                icon={<ReloadOutlined spin={pool.loading} />}
                onClick={pool.handleRefresh}
                disabled={pool.loading}
              />
            </Tooltip>
            {isAdmin && (
              <>
                <Button
                  icon={<UploadOutlined />}
                  onClick={() => pool.zipInputRef.current?.click()}
                >
                  {t("skills.uploadZip")}
                </Button>
                <Button icon={<ImportOutlined />} onClick={() => pool.setImportModalOpen(true)}>
                  {t("skills.importHub")}
                </Button>
                <Button icon={<SyncOutlined />} onClick={pool.openImportBuiltin}>
                  {t("skillPool.importBuiltin")}
                </Button>
              </>
            )}
            <SkillFilterDropdown
              allTags={pool.allTags}
              searchTags={pool.searchTags}
              setSearchTags={pool.setSearchTags}
              styles={{}} />

            {isAdmin && (
              <>
                <Button type="primary" icon={<PlusOutlined />} onClick={pool.openCreate}>
                  {t("skills.createSkill")}
                </Button>
                <Button type="primary" onClick={pool.toggleBatchMode}>
                  {t("skills.batchOperation")}
                </Button>
              </>
            )}
            <div className={styles.viewToggle}>
              <button
                className={`${styles.viewToggleBtn} ${pool.viewMode === "list" ? styles.viewToggleBtnActive : ""}`}
                onClick={() => pool.setViewMode("list")}
                title={t("skills.listView")}
              >
                <UnorderedListOutlined />
              </button>
              <button
                className={`${styles.viewToggleBtn} ${pool.viewMode === "card" ? styles.viewToggleBtnActive : ""}`}
                onClick={() => pool.setViewMode("card")}
                title={t("skills.gridView")}
              >
                <AppstoreOutlined />
              </button>
            </div>
          </div>
        )}
      </div>

      {/* === 内置技能通知 === */}
      {builtinNoticeLines.length > 0 && (
        <div className={styles.builtinNotice}>
          {builtinNoticeLines.map((line, idx) => (
            <div key={idx}>{line}</div>
          ))}
        </div>
      )}

      {/* === 技能列表 === */}
      {pool.loading ? (
        <div className={styles.loading}>
          <span className={styles.loadingText}>{t("common.loading")}</span>
        </div>
      ) : pool.sortedSkills.length === 0 ? (
        <div className={styles.noSearchResults}>
          <span className={styles.noSearchResultsIcon}>🔍</span>
          <span className={styles.noSearchResultsText}>{t("skills.noSearchResults")}</span>
        </div>
      ) : pool.viewMode === "card" ? (
        <div className={styles.skillsGrid}>
          {visibleSkills.map((skill) => (
            <PoolSkillCard
              key={skill.name}
              skill={skill}
              isSelected={pool.selectedPoolSkills.has(skill.name)}
              batchModeEnabled={pool.batchModeEnabled}
              onToggleSelect={pool.togglePoolSelect}
              onEdit={pool.openEdit}
              onBroadcast={() => {}}
              onDelete={pool.handleDelete}
            />
          ))}
          {hasMore && <div ref={sentinelRef} style={{ height: 1 }} />}
        </div>
      ) : (
        <div className={styles.skillsList}>
          {visibleSkills.map((skill) => (
            <PoolSkillListItem
              key={skill.name}
              skill={skill}
              isSelected={pool.selectedPoolSkills.has(skill.name)}
              batchModeEnabled={pool.batchModeEnabled}
              onToggleSelect={pool.togglePoolSelect}
              onEdit={pool.openEdit}
              onBroadcast={() => {}}
              onDelete={pool.handleDelete}
            />
          ))}
          {hasMore && <div ref={sentinelRef} style={{ height: 1 }} />}
        </div>
      )}

      {/* === 抽屉 & 模态框 === */}
      <PoolSkillDrawer
        mode={pool.mode}
        activeSkill={pool.activeSkill}
        form={pool.form}
        drawerContent={pool.drawerContent}
        showMarkdown={pool.showMarkdown}
        configText={pool.configText}
        availableTags={pool.allTags}
        onClose={pool.closeDrawer}
        onSave={pool.handleSavePoolSkill}
        onContentChange={pool.handleDrawerContentChange}
        onShowMarkdownChange={pool.setShowMarkdown}
        onConfigTextChange={pool.setConfigText}
        onChangeBuiltinLanguage={pool.handleBuiltinLanguageSwitch}
        validateFrontmatter={pool.validateFrontmatter}
        onExport={(name) => void pool.handleExportZipFromPool([name])}
      />

      {pool.conflictRenameModal}

      <ImportHubModal
        open={pool.importModalOpen}
        importing={pool.importing}
        onCancel={pool.closeImportModal}
        onConfirm={pool.handleConfirmImport}
        hint={t("skillPool.externalHubHint")}
      />

      <ImportBuiltinModal
        open={pool.importBuiltinModalOpen}
        loading={pool.importBuiltinLoading}
        sources={pool.builtinSources}
        notice={pool.builtinNotice}
        defaultLanguage={pool.builtinLanguage}
        defaultSelectedNames={pool.builtinNotice?.actionable_skill_names}
        onCancel={pool.closeImportBuiltin}
        onConfirm={pool.handleImportBuiltins}
      />
    </>
  );
}
