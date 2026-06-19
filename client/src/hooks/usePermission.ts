/**
 * usePermission — Check if the current user has specific permissions.
 *
 * Uses the backend /api/permissions/check endpoint.
 * Results are cached per permission string within the component lifecycle.
 *
 * Strategy: conservative — permissions default to false until verified.
 * This prevents unauthorized UI elements from flashing before the
 * async check completes.
 *
 * Usage:
 *   const { hasPermission, loaded, checkPermissions } = usePermission();
 *
 *   // Lazy single check (returns false until async resolves)
 *   if (hasPermission("tools:write")) { ... }
 *
 *   // Pre-load multiple permissions at once (recommended)
 *   useEffect(() => {
 *     checkPermissions(["cron-jobs:create", "cron-jobs:delete"]);
 *   }, []);
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useUser } from "../contexts/UserContext";
import { checkPermission } from "../api/modules/permissions";

interface PermissionResult {
  /** True after the initial user context is resolved */
  loaded: boolean;
  /** Returns true only if the permission has been verified and allowed */
  hasPermission: (permission: string) => boolean;
  /** Check multiple permissions in one batch; updates cache when done */
  checkPermissions: (permissions: string[]) => Promise<void>;
}

export function usePermission(): PermissionResult {
  const { user } = useUser();
  const [cache, setCache] = useState<Record<string, boolean>>({});
  const [loaded, setLoaded] = useState(false);
  // Track in-flight checks to avoid duplicate requests
  const inflight = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (!user) {
      setCache({});
      setLoaded(true);
      return;
    }
    setLoaded(true);
  }, [user]);

  const hasPermission = useCallback(
    (permission: string): boolean => {
      if (permission in cache) {
        return cache[permission];
      }

      // Fire-and-forget async check; update cache when it resolves
      if (!inflight.current.has(permission)) {
        inflight.current.add(permission);
        checkPermission(permission)
          .then((result) => {
            setCache((prev) => ({ ...prev, [permission]: result.allowed }));
          })
          .catch(() => {
            setCache((prev) => ({ ...prev, [permission]: false }));
          })
          .finally(() => {
            inflight.current.delete(permission);
          });
      }

      // Conservative: assume denied until proven otherwise
      return false;
    },
    [cache],
  );

  const checkPermissions = useCallback(
    async (permissions: string[]): Promise<void> => {
      const unchecked = permissions.filter((p) => !(p in cache));
      if (unchecked.length === 0) return;

      const results = await Promise.allSettled(
        unchecked.map((p) => checkPermission(p)),
      );

      const updates: Record<string, boolean> = {};
      results.forEach((r, i) => {
        const perm = unchecked[i];
        if (r.status === "fulfilled") {
          updates[perm] = r.value.allowed;
        } else {
          updates[perm] = false;
        }
      });

      setCache((prev) => ({ ...prev, ...updates }));
    },
    [cache],
  );

  return { loaded, hasPermission, checkPermissions };
}
