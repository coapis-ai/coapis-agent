import { useCallback, useEffect, useState } from "react";
import api from "../../../api";
import type { CategorySpec } from "../../../api/types";

const FALLBACK_CATEGORIES: CategorySpec[] = [
  { key: "system", label: "系统", emoji: "⚙️", sort_order: 1 },
  { key: "browser", label: "浏览器", emoji: "🌐", sort_order: 2 },
  { key: "office", label: "办公文档", emoji: "📄", sort_order: 3 },
  { key: "communication", label: "通信", emoji: "💬", sort_order: 4 },
  { key: "development", label: "开发工具", emoji: "🛠", sort_order: 5 },
  { key: "research", label: "调研", emoji: "🔍", sort_order: 6 },
];

/**
 * Shared hook: fetch skill categories from API once and provide helpers.
 */
export function useCategories() {
  const [categories, setCategories] = useState<CategorySpec[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchCategories = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.listCategories();
      setCategories(data?.length ? data : FALLBACK_CATEGORIES);
    } catch {
      setCategories(FALLBACK_CATEGORIES);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchCategories();
  }, [fetchCategories]);

  /** Build a display string from category key: "⚙️ 系统" */
  const getDisplay = useCallback(
    (key: string): string => {
      const cat = categories.find((c) => c.key === key);
      if (!cat) return key || "未分类";
      return cat.emoji ? `${cat.emoji} ${cat.label}` : cat.label;
    },
    [categories],
  );

  /** Simple map for backward-compat: { system: "⚙️ 系统", ... } */
  const categoryMap = Object.fromEntries(
    categories.map((c) => [c.key, c.emoji ? `${c.emoji} ${c.label}` : c.label]),
  );

  return {
    categories,
    loading,
    categoryMap,
    getDisplay,
    refresh: fetchCategories,
  };
}
