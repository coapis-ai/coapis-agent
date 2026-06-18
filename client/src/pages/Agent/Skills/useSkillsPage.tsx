import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Form, Modal } from "@agentscope-ai/design";
import type { PoolSkillSpec, SkillSpec } from "../../../api/types";
import type { SkillDrawerFormValues } from "./components";
import { useConflictRenameModal } from "./components";
import { useProgressiveRender } from "../../../hooks/useProgressiveRender";
import { useTranslation } from "react-i18next";
import { useAgentStore } from "../../../stores/agentStore";
import { useAppMessage } from "../../../hooks/useAppMessage";
import api from "../../../api";
import { invalidateSkillCache, skillApi } from "../../../api/modules/skill";
import { parseErrorDetail } from "../../../utils/error";
import { requestSaveHandle, writeBlobToHandle } from "../../../utils/saveBlobToDisk";
import { useSkills } from "./useSkills";
import { useSkillFilter } from "./useSkillFilter";
import { useCategories } from "./useCategories";

// ─── Types ──────────────────────────────────────────────────────────────────

export type DownloadConflict =
  | { skill_name: string; reason: "conflict" }
  | {
      skill_name: string;
      reason: "builtin_upgrade";
      current_version_text: string;
      source_version_text: string;
    }
  | {
      skill_name: string;
      reason: "language_switch";
      source_language: string;
      current_language: string;
    };

const MAX_UPLOAD_SIZE_MB = 100;

// ─── Hook ───────────────────────────────────────────────────────────────────

export function useSkillsPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { selectedAgent } = useAgentStore();

  const {
    skills,
    loading,
    uploading,
    importing,
    createSkill,
    uploadSkill,
    importFromHub,
    cancelImport,
    toggleEnabled,
    deleteSkill,
    refreshSkills,
    hardRefresh,
  } = useSkills();

  const {
    searchQuery,
    setSearchQuery,
    searchTags,
    setSearchTags,
    allTags,
    filteredSkills,
  } = useSkillFilter(skills);

  const { categories: categoryOptions, categoryMap, getDisplay: getCategoryDisplay, refresh: refreshCategories } = useCategories();

  const { showConflictRenameModal, conflictRenameModal } =
    useConflictRenameModal();

  // ── Local state ─────────────────────────────────────────────────────────

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [editingSkill, setEditingSkill] = useState<SkillSpec | null>(null);
  const [form] = Form.useForm<SkillDrawerFormValues>();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [poolSkills, setPoolSkills] = useState<PoolSkillSpec[]>([]);
  const [poolModal, setPoolModal] = useState<"upload" | null>(
    null,
  );
  const [selectedSkills, setSelectedSkills] = useState<Set<string>>(new Set());
  const [batchModeEnabled, setBatchModeEnabled] = useState(false);
  const [viewMode, setViewMode] = useState<"card" | "list">("card");
  const [filterOpen, setFilterOpen] = useState(false);
  const [skillMetrics, setSkillMetrics] = useState<Record<string, { score: number; precision: number; satisfaction: number }>>({});

  // ── Fetch skill metrics on mount ────────────────────────────────────────
  useEffect(() => {
    (async () => {
      try {
        const data = await skillApi.getSkillMetrics();
        const map: Record<string, { score: number; precision: number; satisfaction: number }> = {};
        for (const m of data.metrics || []) {
          map[m.skill_name] = {
            score: m.composite_score,
            precision: m.precision,
            satisfaction: m.satisfaction,
          };
        }
        setSkillMetrics(map);
      } catch { /* silent */ }
    })();
  }, []);

  // ── Derived ─────────────────────────────────────────────────────────────

  // Category display order — derived from API, not hardcoded
  const CATEGORY_ORDER = useMemo(
    () => [...categoryOptions.map((c) => c.key), ""],
    [categoryOptions],
  );

  const sortedSkills = useMemo(
    () =>
      filteredSkills.slice().sort((a, b) => {
        // Primary: category order
        const catA = CATEGORY_ORDER.indexOf(a.category || "");
        const catB = CATEGORY_ORDER.indexOf(b.category || "");
        if (catA !== catB) return (catA === -1 ? 99 : catA) - (catB === -1 ? 99 : catB);
        // Secondary: enabled first
        if (a.enabled && !b.enabled) return -1;
        if (!a.enabled && b.enabled) return 1;
        // Tertiary: name
        return a.name.localeCompare(b.name);
      }).map((skill) => {
        // Merge metric data into skill for display
        const m = skillMetrics[skill.name];
        if (m) {
          return {
            ...skill,
            metric_score: m.score,
            metric_precision: m.precision,
            metric_satisfaction: m.satisfaction,
          };
        }
        return skill;
      }),
    [filteredSkills, skillMetrics],
  );

  // Group skills by category for section rendering
  const groupedSkills = useMemo(() => {
    const groups: { category: string; skills: typeof sortedSkills }[] = [];
    let currentCat = "";
    let currentGroup: typeof sortedSkills = [];
    for (const skill of sortedSkills) {
      const cat = skill.category || "";
      if (cat !== currentCat) {
        if (currentGroup.length > 0) {
          groups.push({ category: currentCat, skills: currentGroup });
        }
        currentCat = cat;
        currentGroup = [skill];
      } else {
        currentGroup.push(skill);
      }
    }
    if (currentGroup.length > 0) {
      groups.push({ category: currentCat, skills: currentGroup });
    }
    return groups;
  }, [sortedSkills]);

  const {
    visibleItems: visibleSkills,
    hasMore,
    sentinelRef,
  } = useProgressiveRender(sortedSkills);

  // ── Effects ─────────────────────────────────────────────────────────────

  useEffect(() => {
    if (poolModal === "upload" || poolModal === "download") {
      void api
        .listSkillPoolSkills()
        .then(setPoolSkills)
        .catch(() => undefined);
    }
  }, [poolModal]);

  // ── Helpers ─────────────────────────────────────────────────────────────

  const confirmOverwrite = (title: string, content: ReactNode) =>
    new Promise<boolean>((resolve) => {
      Modal.confirm({
        title,
        content,
        okText: t("common.confirm"),
        cancelText: t("common.cancel"),
        onOk: () => resolve(true),
        onCancel: () => resolve(false),
      });
    });

  const toggleSelect = (name: string) => {
    setSelectedSkills((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const clearSelection = () => setSelectedSkills(new Set());

  const selectAll = () =>
    setSelectedSkills(new Set(filteredSkills.map((s) => s.name)));

  const toggleBatchMode = () => {
    if (batchModeEnabled) {
      clearSelection();
      setBatchModeEnabled(false);
    } else {
      setBatchModeEnabled(true);
    }
  };

  const closePoolModal = () => setPoolModal(null);

  const handleUploadClick = () => fileInputRef.current?.click();

  // ── File upload ─────────────────────────────────────────────────────────

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";
    if (!file.name.toLowerCase().endsWith(".zip")) {
      message.warning(t("skills.zipOnly"));
      return;
    }
    const sizeMB = file.size / (1024 * 1024);
    if (sizeMB > MAX_UPLOAD_SIZE_MB) {
      message.warning(
        t("skills.fileSizeExceeded", {
          limit: MAX_UPLOAD_SIZE_MB,
          size: sizeMB.toFixed(1),
        }),
      );
      return;
    }
    let renameMap: Record<string, string> | undefined;
    while (true) {
      const result = await uploadSkill(file, undefined, renameMap);
      if (result.success || !result.conflict) break;
      const conflicts = Array.isArray(result.conflict.conflicts)
        ? result.conflict.conflicts
        : [];
      if (conflicts.length === 0) break;
      const newRenames = await showConflictRenameModal(
        conflicts.map((c: { skill_name: string; suggested_name: string }) => ({
          key: c.skill_name,
          label: c.skill_name,
          suggested_name: c.suggested_name,
        })),
      );
      if (!newRenames) break;
      renameMap = { ...renameMap, ...newRenames };
    }
  };

  // ── Create / Edit / Delete ──────────────────────────────────────────────

  const handleCreate = () => {
    setEditingSkill(null);
    form.resetFields();
    form.setFieldsValue({ enabled: false, channels: ["all"], tags: [] });
    setDrawerOpen(true);
  };

  const closeImportModal = () => {
    if (importing) return;
    setImportModalOpen(false);
  };

  const handleConfirmImport = async (url: string, targetName?: string) => {
    const result = await importFromHub(url, targetName);
    if (result.success) {
      closeImportModal();
    } else if (result.conflict) {
      const detail = result.conflict;
      const suggested =
        detail?.suggested_name || detail?.conflicts?.[0]?.suggested_name;
      if (suggested) {
        const skillName =
          detail?.skill_name || detail?.conflicts?.[0]?.skill_name || "";
        const renameMap = await showConflictRenameModal([
          {
            key: skillName,
            label: skillName,
            suggested_name: String(suggested),
          },
        ]);
        if (renameMap) {
          const newName = Object.values(renameMap)[0];
          if (newName) await handleConfirmImport(url, newName);
        }
      }
    }
  };

  const handleEdit = (skill: SkillSpec) => {
    setEditingSkill(skill);
    form.setFieldsValue({
      name: skill.name,
      description: skill.description,
      content: skill.content,
      enabled: skill.enabled,
      channels: skill.channels,
    });
    setDrawerOpen(true);
  };

  const handleToggleEnabled = async (skill: SkillSpec, e: React.MouseEvent) => {
    e.stopPropagation();
    await toggleEnabled(skill);
    await refreshSkills();
  };

  const handleDelete = async (skill: SkillSpec, e?: React.MouseEvent) => {
    e?.stopPropagation();
    await deleteSkill(skill);
  };

  const handleDrawerClose = () => {
    setDrawerOpen(false);
    setEditingSkill(null);
  };

  // ── Drawer submit ───────────────────────────────────────────────────────

  const handleSubmit = async (values: SkillSpec) => {
    if (editingSkill) {
      const sourceName = editingSkill.name;
      const targetName = values.name;
      const saveEditedSkill = async (overwrite = false) => {
        const result = await api.saveSkill({
          name: targetName,
          content: values.content,
          source_name: sourceName !== targetName ? sourceName : undefined,
          config: values.config,
          category: values.category ?? null,
          overwrite,
        });
        const sideUpdates: Promise<unknown>[] = [];
        const newChannels = values.channels || ["all"];
        if (
          JSON.stringify(newChannels) !==
          JSON.stringify(editingSkill.channels || ["all"])
        ) {
          sideUpdates.push(api.updateSkillChannels(result.name, newChannels));
        }
        const newTags = values.tags || [];
        if (
          JSON.stringify(newTags) !== JSON.stringify(editingSkill.tags || [])
        ) {
          sideUpdates.push(api.updateSkillTags(result.name, newTags));
        }
        await Promise.all(sideUpdates);
        if (result.mode === "noop" && sideUpdates.length === 0) {
          setDrawerOpen(false);
          return;
        }
        if (result.mode !== "noop") {
          message.success(
            result.mode === "rename"
              ? `${t("common.save")}: ${result.name}`
              : t("common.save"),
          );
        }
        setDrawerOpen(false);
        invalidateSkillCache({ agentId: selectedAgent });
        await refreshSkills();
      };
      try {
        await saveEditedSkill();
      } catch (error) {
        const detail = parseErrorDetail(error);
        if (detail?.reason === "conflict") {
          const confirmed = await confirmOverwrite(
            t("skillPool.overwriteConfirm"),
            <div style={{ display: "grid", gap: 8 }}>
              <div>{t("skills.overwriteExistingList")}</div>
              <ul style={{ margin: 0, paddingLeft: 20 }}>
                <li>{targetName}</li>
              </ul>
            </div>,
          );
          if (!confirmed) return;
          try {
            await saveEditedSkill(true);
          } catch (retryError) {
            message.error(
              retryError instanceof Error
                ? retryError.message
                : t("common.save"),
            );
          }
        } else {
          message.error(
            error instanceof Error ? error.message : t("common.save"),
          );
        }
      }
    } else {
      const submitName = values.name;
      const result = await createSkill(
        submitName,
        values.content,
        values.config,
        true,
      );
      if (result.success) {
        const actualName = result.name || submitName;
        await Promise.all([
          api.updateSkillChannels(actualName, values.channels || ["all"]),
          ...(values.tags?.length
            ? [api.updateSkillTags(actualName, values.tags)]
            : []),
        ]);
        setDrawerOpen(false);
        invalidateSkillCache({ agentId: selectedAgent });
        await refreshSkills();
        return;
      }
      if (result.conflict?.suggested_name) {
        const renameMap = await showConflictRenameModal([
          {
            key: submitName,
            label: submitName,
            suggested_name: result.conflict!.suggested_name,
          },
        ]);
        if (renameMap) {
          const newName = Object.values(renameMap)[0];
          if (newName) await handleSubmit({ ...values, name: newName });
        }
      }
    }
  };

  // ── Pool transfer ───────────────────────────────────────────────────────

  const handleUploadToPool = async (workspaceSkillNames: string[]) => {
    if (workspaceSkillNames.length === 0) return;
    try {
      const conflictingNames: string[] = [];
      for (const skillName of workspaceSkillNames) {
        try {
          await api.uploadWorkspaceSkillToPool({
            workspace_id: selectedAgent,
            skill_name: skillName,
            preview_only: true,
          });
        } catch (error) {
          const detail = parseErrorDetail(error);
          if (detail?.reason === "conflict") {
            conflictingNames.push(skillName);
            continue;
          }
          throw error;
        }
      }
      if (conflictingNames.length > 0) {
        const confirmed = await confirmOverwrite(
          t("skillPool.overwriteConfirm"),
          <div style={{ display: "grid", gap: 8 }}>
            <div>{t("skills.overwriteExistingList")}</div>
            <ul style={{ margin: 0, paddingLeft: 20 }}>
              {conflictingNames.map((name) => (
                <li key={name}>{name}</li>
              ))}
            </ul>
          </div>,
        );
        if (!confirmed) return;
      }
      for (const skillName of workspaceSkillNames) {
        await api.uploadWorkspaceSkillToPool({
          workspace_id: selectedAgent,
          skill_name: skillName,
          overwrite: conflictingNames.includes(skillName),
        });
      }
      message.success(t("skills.uploadedToPool"));
      closePoolModal();
      invalidateSkillCache({ agentId: selectedAgent, pool: true });
      await refreshSkills();
      setPoolSkills(await api.listSkillPoolSkills());
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("skills.uploadFailed"),
      );
    }
  };

  // ── Export skills as ZIP ───────────────────────────────────────────────

  const handleExportZip = async (skillNames: string[]) => {
    if (skillNames.length === 0) return;
    const defaultName = skillNames.length === 1 ? `${skillNames[0]}.zip` : "skills_export.zip";
    // 尝试弹出"另存为"对话框（仅 HTTPS/localhost 可用）
    const handle = await requestSaveHandle(defaultName);
    try {
      const { blob } = await api.exportSkills(skillNames, selectedAgent);
      // handle 为 null 时自动 fallback 为 <a> 下载
      await writeBlobToHandle(blob, handle, defaultName);
      message.success(t("skills.exportSuccess", { count: skillNames.length }));
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("skills.exportFailed"),
      );
    }
  };

  // ── Batch delete ────────────────────────────────────────────────────────

  const handleBatchDelete = async () => {
    const names = Array.from(selectedSkills);
    if (names.length === 0) return;
    const confirmed = await new Promise<boolean>((resolve) => {
      Modal.confirm({
        title: t("skills.batchDeleteTitle", { count: names.length }),
        content: (
          <ul style={{ margin: "8px 0", paddingLeft: 20 }}>
            {names.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        ),
        okText: t("common.delete"),
        okType: "danger",
        cancelText: t("common.cancel"),
        onOk: () => resolve(true),
        onCancel: () => resolve(false),
      });
    });
    if (!confirmed) return;
    try {
      const { results } = await api.batchDeleteSkills(names);
      const failed = Object.entries(results).filter(([, r]) => !r.success);
      if (failed.length > 0) {
        message.warning(
          t("skills.batchDeletePartial", {
            deleted: names.length - failed.length,
            failed: failed.length,
          }),
        );
      } else {
        message.success(
          t("skills.batchDeleteSuccess", { count: names.length }),
        );
      }
      clearSelection();
      invalidateSkillCache({ agentId: selectedAgent });
      await refreshSkills();
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("skills.batchDeleteFailed"),
      );
    }
  };

  return {
    skills,
    sortedSkills,
    groupedSkills,
    visibleSkills,
    hasMore,
    sentinelRef,
    poolSkills,
    allTags,
    filteredSkills,
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
    categoryMap,
    getCategoryDisplay,
    categoryOptions,
    refreshCategories,
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
    clearSelection,
    selectAll,
    toggleBatchMode,
    toggleEnabled,
    refreshSkills,
    hardRefresh,
    cancelImport,
  };
}
