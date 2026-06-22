/**
 * PermissionMatrix — 可复用的权限 CRUD 矩阵组件
 *
 * 用于：
 * 1. 角色管理（RolesSubTab）— 编辑角色默认权限
 * 2. 用户覆盖（PermissionOverrideMatrix）— 编辑用户级覆盖，高亮差异
 * 3. 审计日志展示、模块操作配置等
 */
import { Table, Checkbox, Tooltip, Tag, Space, Button } from "antd";
import { useTranslation } from "react-i18next";

export const CRUD_OPS = ["read", "create", "update", "delete"] as const;
export type CrudOp = (typeof CRUD_OPS)[number];

export interface PermissionMatrixProps {
  /** 模块定义: { [moduleKey]: { name, icon, ... } } */
  moduleDefs: Record<string, { name?: string; icon?: string; description?: string; adminOnly?: boolean; operations?: CrudOp[] }>;
  /** 当前值: { [moduleKey]: { read: bool, create: bool, ... } } */
  value: Record<string, Record<string, boolean>>;
  /** 变更回调 */
  onChange: (next: Record<string, Record<string, boolean>>) => void;
  /** 基准矩阵（用于显示差异高亮），不传则不显示差异 */
  baseMatrix?: Record<string, Record<string, boolean>>;
  /** 是否显示还原默认按钮 */
  showReset?: boolean;
  /** 还原默认回调 */
  onReset?: () => void;
  /** 差异数量标签（由父组件计算） */
  diffCount?: number;
  /** 表格尺寸 */
  size?: "small" | "middle" | "large";
  /** 是否显示边框 */
  bordered?: boolean;
}

export default function PermissionMatrix({
  moduleDefs,
  value,
  onChange,
  baseMatrix,
  showReset = false,
  onReset,
  diffCount,
  size = "small",
  bordered = true,
}: PermissionMatrixProps) {
  const { t } = useTranslation();

  const opLabels: Record<string, string> = {
    read: t("admin.opRead", "读"),
    create: t("admin.opCreate", "增"),
    update: t("admin.opUpdate", "改"),
    delete: t("admin.opDelete", "删"),
  };

  // 可用的操作列（按模块配置过滤）
  const getOpsForModule = (mod: string): readonly CrudOp[] => {
    const allowed = moduleDefs[mod]?.operations;
    if (allowed && allowed.length > 0) return allowed;
    return CRUD_OPS;
  };

  const setCell = (mod: string, op: string, val: boolean) => {
    const next = { ...value, [mod]: { ...(value[mod] || {}), [op]: val } };
    onChange(next);
  };

  const setAll = (mod: string, val: boolean) => {
    const ops = getOpsForModule(mod);
    const next = { ...value, [mod]: { ...value[mod] } };
    for (const op of ops) {
      next[mod][op] = val;
    }
    onChange(next);
  };

  const moduleKeys = Object.keys(moduleDefs);

  const isOverridden = (mod: string, op: string) => {
    if (!baseMatrix) return false;
    return value[mod]?.[op] !== baseMatrix[mod]?.[op];
  };

  const columns = [
    {
      title: t("admin.moduleName", "功能模块"),
      dataIndex: "key",
      key: "key",
      width: 180,
      render: (key: string) => {
        const def = moduleDefs[key];
        const ops = getOpsForModule(key);
        const allChecked = ops.every((op) => value[key]?.[op]);
        const someChecked = ops.some((op) => value[key]?.[op]);
        return (
          <Space size={4}>
            <Checkbox
              checked={allChecked}
              indeterminate={!allChecked && someChecked}
              disabled={def?.adminOnly}
              onChange={(e) => setAll(key, e.target.checked)}
            >
              <span>{def?.icon} {def?.name || key}</span>
            </Checkbox>
          </Space>
        );
      },
    },
    ...CRUD_OPS.map((op) => ({
      title: opLabels[op],
      dataIndex: "key",
      key: op,
      width: 60,
      align: "center" as const,
      render: (key: string) => {
        const def = moduleDefs[key];
        const supported = getOpsForModule(key);
        const isSupported = supported.includes(op);
        const overridden = isOverridden(key, op);
        if (!isSupported) {
          return <span style={{ color: "#d9d9d9" }}>—</span>;
        }
        return (
          <Tooltip title={overridden ? t("admin.overridden", "已覆盖") : ""}>
            <Checkbox
              checked={!!value[key]?.[op]}
              disabled={def?.adminOnly}
              style={overridden ? { color: "#1677ff" } : undefined}
              onChange={(e) => setCell(key, op, e.target.checked)}
            />
          </Tooltip>
        );
      },
    })),
  ];

  const data = moduleKeys.map((k) => ({ key: k }));

  return (
    <div>
      {showReset && (
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
          <Space>
            <span style={{ fontWeight: 500 }}>{t("admin.permissionOverrides", "权限覆盖")}</span>
            {typeof diffCount === "number" && diffCount > 0 && (
              <Tag color="blue">{t("admin.overrideCount", { count: diffCount, defaultValue: `${diffCount} 项差异` })}</Tag>
            )}
          </Space>
          <Button size="small" onClick={onReset}>{t("admin.resetToDefault", "还原默认")}</Button>
        </div>
      )}
      <Table
        columns={columns}
        dataSource={data}
        rowKey="key"
        pagination={false}
        size={size}
        bordered={bordered}
      />
    </div>
  );
}
