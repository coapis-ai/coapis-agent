/**
 * usePermission — Check if the current user has a specific permission.
 *
 * Uses the backend /api/permissions/check endpoint.
 * Results are cached per permission string within the component lifecycle.
 *
 * Usage:
 *   const { hasPermission, loaded } = usePermission();
 *   if (hasPermission("tools:write")) { ... }
 */
import { useCallback, useEffect, useState } from "react";
import { useUser } from "../contexts/UserContext";
import { checkPermission } from "../api/modules/permissions";

interface PermissionResult {
  loaded: boolean;
  hasPermission: (permission: string) => boolean;
}

export function usePermission(): PermissionResult {
  const { user } = useUser();
  const [cache, setCache] = useState<Record<string, boolean>>({});
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!user) {
      // No user — anonymous, no permissions
      setCache({});
      setLoaded(true);
      return;
    }
    // Mark as loaded immediately; individual checks will populate cache lazily
    setLoaded(true);
  }, [user]);

  const hasPermission = useCallback(
    (permission: string): boolean => {
      if (permission in cache) {
        return cache[permission];
      }

      // Fire-and-forget async check; update cache when it resolves
      checkPermission(permission)
        .then((result) => {
          setCache((prev) => ({ ...prev, [permission]: result.allowed }));
        })
        .catch(() => {
          setCache((prev) => ({ ...prev, [permission]: false }));
        });

      // Optimistic: assume allowed until proven otherwise (prevents flash of hidden content)
      return true;
    },
    [cache],
  );

  return { loaded, hasPermission };
}
