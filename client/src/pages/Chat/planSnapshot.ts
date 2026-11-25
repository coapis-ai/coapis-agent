/**
 * 计划快照读取 · 一轮应答 → 该轮的计划快照
 * ---------------------------------------------------------------------------
 * 背景（2026-11-25 实测踩坑）：
 * 消息卡片的插槽拿到的 `data` 是**一轮应答**本身，它只有
 * `id / output / status / usage …`，**没有 metadata**。
 * 而计划快照是后端在收口时写进「本轮最后一条正式回复」的
 * `metadata.metadata.plan_snapshot`（见 server/coapis/app/runner/runner.py）。
 *
 * 所以旧写法 `data?.metadata?.metadata?.plan_snapshot` 恒为 undefined，
 * 刷新后计划卡片整张消失——快照明明落进了聊天记录，前端却读不到。
 * 这里把读取口径收成一个函数，并用契约测试钉住，防止再写回 data.metadata。
 */

/** 一轮应答里最后一条带快照的正式回复 → 快照；没有则 undefined。 */
export function planSnapshotFromResponse(data: any): any {
  const output = Array.isArray(data?.output) ? data.output : [];
  for (let i = output.length - 1; i >= 0; i--) {
    const item = output[i];
    if (item?.type !== "message" || item?.role !== "assistant") continue;
    const snap = item?.metadata?.metadata?.plan_snapshot;
    if (snap) return snap;
  }
  return undefined;
}
