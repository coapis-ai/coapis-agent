/**
 * PermissionGuard — Wraps an action element with permission checking.
 *
 * Usage:
 *   <PermissionGuard module="cron-jobs" action="create">
 *     <Button type="primary" onClick={handleCreate}>+ 新建</Button>
 *   </PermissionGuard>
 *
 * When the user lacks the permission:
 *   - fallback="disabled" (default): wraps in Tooltip, disables the child
 *   - fallback="hidden": renders nothing
 *
 * Maps module+action to permission string: "{module}:{action}"
 */
import React from "react";
import { Tooltip } from "antd";
import { useTranslation } from "react-i18next";
import { usePermission } from "../hooks/usePermission";

interface PermissionGuardProps {
  /** Permission module (e.g. "cron-jobs", "channels", "skills") */
  module: string;
  /** Permission action (e.g. "create", "write", "delete") */
  action: string;
  /** What to show when permission is denied */
  fallback?: "disabled" | "hidden";
  /** The element to guard (must be a single clickable element) */
  children: React.ReactElement;
}

export function PermissionGuard({
  module,
  action,
  fallback = "disabled",
  children,
}: PermissionGuardProps) {
  const { t } = useTranslation();
  const { loaded, hasPermission } = usePermission();
  const permission = `${module}:${action}`;
  const allowed = hasPermission(permission);

  // Not loaded yet — show disabled state to prevent flash
  if (!loaded) {
    return React.cloneElement(children, {
      disabled: true,
    } as React.HTMLAttributes<HTMLElement>);
  }

  if (allowed) {
    return children;
  }

  // Permission denied
  if (fallback === "hidden") {
    return null;
  }

  // fallback === "disabled": wrap with Tooltip
  const tooltipMsg = t(
    "permission.noAccess",
    "无权限执行此操作",
  );

  return (
    <Tooltip title={tooltipMsg}>
      {React.cloneElement(children, {
        disabled: true,
        style: { ...children.props.style, pointerEvents: "auto" },
      } as React.HTMLAttributes<HTMLElement>)}
    </Tooltip>
  );
}
