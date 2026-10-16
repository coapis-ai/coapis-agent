# ToolManager dev 实测报告（2026-10-16 02:00）

配套：`ToolManager实施方案v2_20261016.md`、`ToolManager复核报告_20261016.md`

测量方式：`POST /api/console/chat`（SSE）真实对话，读运行期日志
`[MCP_DEBUG] schemas_at_call_time NAMES` 与 `context_budget` 实测行。
模型：dev 会话模型 `a3/A3`（自报无窗口 → `config_fallback` → `max_input_length`
= 65536 字符）。

## 1. 分组生效（实测数字）

| 场景 | step-1 schema 工具数 | 工具 schema 字符 | 相对基线 |
|---|---|---|---|
| 基线（全量注入，改造前） | 53 | 44677 | — |
| 关键词无命中（"帮我算 1 到 100 的和"） | **20** | **14336** | **−67.9%** |
| 命中 browser/media/web（"用浏览器打开…并截图"） | 23 | 23875 | −46.5% |

- 预激活日志：`Tool groups pre-activated for query: browser, media, web` ✅
- `reset_equipped_tools` 在 step-1 schema 中（元工具已注册）✅
- 被门控的 `browser_use` 预激活后可被模型直接调用并真实执行
  （日志 `[BROWSER_USE_DBG] action=...`）✅
- 关键词无命中时 schema 只剩 core(11) + plan(8) + 元工具(1) = 20 个 ✅
- 全量注册 53 个工具中，33 个在 step-1 被门控掉 ✅

## 2. E2E 撞出的 P0（属 G3 预算闸门，与 ToolManager 无关）

```
Context overflow for agent 'user:admin': prompt 76691 chars vs 65536-char window
  fixed overhead 48113（其中工具 schema 23875）; history 28578;
  pruning reclaimed 11239; floor 28835 blocks further pruning
```

- **地板（`keep_chars_floor`）只由窗口推导，不看固定开销**：
  当 `fixed + floor > window`，闸门必然失败，且**拒绝执行本可救场的裁剪**。
- admin：可用 `65536 − 48113 = 17423`，地板却是 28835 →
  **该 agent 每次对话必 422**（`MODEL_CONTEXT_LENGTH_EXCEEDED`）。
- 全新用户 `e2e_tg_user`：第 5 步即 `fixed 41414 + history 24478 = 65892 > 65536`；
  history 已低于地板 28835 → `pruning reclaimed 0` → 硬失败。
- 闸门语义本身正确（快速失败 + 可执行提示 + 落盘归档不删记录），
  **需要改的是地板策略：地板必须"可负担"**。

## 3. 附带观察

- `browser_use` 被模型以空参调用 → `missing 1 required positional argument: 'action'`。
  弱本地模型（A3）行为，非分组问题；元工具目录里 browser 组的描述已含
  "open pages, click, type…"，可考虑在描述里点名 `action` 必填。
- dev 会话模型自报无窗口，窗口全靠 `config_fallback`；G1 的"模型自报 × 0.5"
  在这条链路上没有生效入口（`window_source` 已正确降级并标注来源）。
