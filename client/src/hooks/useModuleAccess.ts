/**
 * useModuleAccess — Reusable hook for server-driven module access control.
 *
 * Replaces hardcoded isAdmin checks in route guards and page components.
 * Fetches allowed modules from /api/permissions/modules on mount.
 */
import { useEffect, useState } from "react";
import { useUser } from "../contexts/UserContext";
import { permissionsApi } from "../api/modules/permissions";

interface ModuleAccessResult {
  /** Whether the permission data has finished loading */
  loaded: boolean;
  /** Full list of allowed module keys (or ["all"] for admin) */
  allowedModules: string[];
  /** Check if a specific module is accessible */
  isAllowed: (moduleKey: string) => boolean;
}

export function useModuleAccess(): ModuleAccessResult {
  const { user } = useUser();
  const [allowedModules, setAllowedModules] = useState<string[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!user) {
      // No user — anonymous mode, allow all
      setAllowedModules(["all"]);
      setLoaded(true);
      return;
    }

    permissionsApi
      .getAllowedModules()
      .then((res) => {
        setAllowedModules(res.modules || []);
        setLoaded(true);
      })
      .catch(() => {
        // On error, deny all (safe default)
        setAllowedModules([]);
        setLoaded(true);
      });
  }, [user]);

  const isAllowed = (moduleKey: string): boolean => {
    if (!loaded) return false;
    if (allowedModules.includes("all")) return true;
    return allowedModules.includes(moduleKey);
  };

  return { loaded, allowedModules, isAllowed };
}
