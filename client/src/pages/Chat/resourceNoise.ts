/**
 * 台账噪声判定（前端侧）。
 *
 * 与后端 `coapis/foundation/resource_ledger.py` 的 `NOISE_DIR_PARTS` 保持同一口径：
 * 软删归档、脚本暂存、依赖目录里的东西不是用户的"资源"，不该出现在会话资源面板里。
 * 后端在登记侧已经挡了一层，这里挡的是**消费侧**——历史数据里已经存在的噪声行
 * （后端补扫口径变更前后写入的）不能让它们在左栏把真实资源挤掉。
 *
 * 实测 dev：1242 条 unledgered 里 298 条来自 `.trash`/`.temp`，占比 24%。
 */

const NOISE_DIR_PARTS = new Set([
  ".trash",
  ".temp",
  ".git",
  "__pycache__",
  "node_modules",
  "venv",
  ".venv",
  "site-packages",
  ".ipynb_checkpoints",
]);

/**
 * 路径里是否含噪声目录段。
 *
 * 入参是台账行的相对路径/文件名（`ChatResourceItem.name`），可能带 `./` 前缀、
 * 反斜杠、Windows 盘符，统一切成段再比对，避免 `a.temp/b` 这种被漏掉。
 */
export function isLedgerNoise(name: string | undefined | null): boolean {
  if (!name) return false;
  const normalized = String(name).replace(/\\/g, "/");
  return normalized
    .split("/")
    .some((seg) => NOISE_DIR_PARTS.has(seg));
}

export default isLedgerNoise;
