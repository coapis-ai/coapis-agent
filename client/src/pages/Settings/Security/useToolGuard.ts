import { useState, useEffect, useCallback } from "react";
import api from "../../../api";
import type { ToolGuardConfig } from "../../../api/modules/security";
import type { ShellRule } from "../../../api/modules/security";

export function useToolGuard() {
  const [config, setConfig] = useState<ToolGuardConfig | null>(null);
  const [globalRules, setGlobalRules] = useState<ShellRule[]>([]);
  const [customRules, setCustomRules] = useState<ShellRule[]>([]);
  const [disabledRules, setDisabledRules] = useState<Set<string>>(new Set());
  const [shellEvasionChecks, setShellEvasionChecks] = useState<
    Record<string, boolean>
  >({});
  const [enabled, setEnabled] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [cfg, rules] = await Promise.all([
        api.getToolGuard(),
        api.getGlobalRules(),
      ]);
      setConfig(cfg);
      setEnabled(cfg.enabled);
      setGlobalRules(rules);
      setCustomRules(cfg.custom_rules ?? []);
      setDisabledRules(new Set(cfg.disabled_rules ?? []));
      setShellEvasionChecks(cfg.shell_evasion_checks ?? {});
    } catch (err) {
      const msg =
        err instanceof Error ? err.message : "Failed to load security config";
      console.error("Failed to load tool guard:", err);
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  const toggleRule = useCallback(
    (ruleId: string, currentlyDisabled: boolean) => {
      setDisabledRules((prev) => {
        const next = new Set(prev);
        if (currentlyDisabled) {
          next.delete(ruleId);
        } else {
          next.add(ruleId);
        }
        return next;
      });
    },
    [],
  );

  const deleteCustomRule = useCallback((ruleId: string) => {
    setCustomRules((prev) => prev.filter((r) => r.id !== ruleId));
    setDisabledRules((prev) => {
      const next = new Set(prev);
      next.delete(ruleId);
      return next;
    });
  }, []);

  const addCustomRule = useCallback((rule: ShellRule) => {
    setCustomRules((prev) => [...prev, rule]);
  }, []);

  const updateCustomRule = useCallback(
    (ruleId: string, rule: ShellRule) => {
      setCustomRules((prev) => prev.map((r) => (r.id === ruleId ? rule : r)));
    },
    [],
  );

  const toggleShellEvasionCheck = useCallback(
    (checkName: string, checked: boolean) => {
      setShellEvasionChecks((prev) => ({ ...prev, [checkName]: checked }));
    },
    [],
  );

  const buildSaveBody = useCallback((): ToolGuardConfig => {
    return {
      enabled,
      guarded_tools: config?.guarded_tools ?? null,
      denied_tools: config?.denied_tools ?? [],
      custom_rules: customRules,
      disabled_rules: Array.from(disabledRules),
      shell_evasion_checks: shellEvasionChecks,
    };
  }, [enabled, config, customRules, disabledRules, shellEvasionChecks]);

  return {
    config,
    globalRules,
    customRules,
    disabledRules,
    enabled,
    setEnabled,
    shellEvasionChecks,
    toggleShellEvasionCheck,
    loading,
    error,
    fetchAll,
    toggleRule,
    deleteCustomRule,
    addCustomRule,
    updateCustomRule,
    buildSaveBody,
  };
}
