# 模型类型管理 V2 设计方案（已实现）

> 状态：**已实现并部署到 dev**（2026-09-04）
> 范围：后端 5 文件 + 前端 9 文件，新增 1 个后端测试文件
> 关联文档：`model-type-management-deep-design.md`（历史背景）、`model-management-ui-design.md`

## 1. 问题与目标

### 1.1 原始痛点
1. **无法筛选非 chat 模型**：嵌入 / 重排序 / 音频 / 视觉模型无法被筛出来。
2. **按“提供商”筛选不合理**：一个提供商（如 Ollama）常同时提供多种类型模型。
3. **模型无法分类**：类型本应在“具体提供商的模型内部”管理，但此前所有模型都被默认当成 `chat`，导致模型选择错误。
4. **典型误配**：dev 环境的 Ollama 配了嵌入模型 `qwen3-embedding:0.6b`，但系统不知道它是嵌入模型，UI 里和 chat 模型混在一起。

### 1.2 目标
- 模型类型成为**一等公民字段**，可在提供商的模型内部**编辑 / 选择**。
- 新模型**自动推断**类型（用户显式选择始终优先）。
- 模型管理主界面**按类型筛选**，且与“提供商管理”解耦。
- 每种类型可独立设置**默认模型**，选择器只列出对应类型的模型。

### 1.3 已确认的决策
- 自动推断：**可接受**（仅对新模型生效，存量后续手动改）。
- 存量数据：不做批量迁移，由用户在 UI 里逐个改。
- 模型类型：在提供商模型内部做成**可编辑 / 可选择**。
- 主界面：**两区布局**（已配置模型 + 提供商管理分开）。

## 2. 数据模型

### 2.1 新增字段
`ModelInfo`（`server/coapis/providers/provider.py`）新增：

```python
model_type: ModelType = "chat"   # chat | embedding | rerank | audio | vision
```

- 默认值 `"chat"`（向后兼容：旧数据无该字段时仍按 chat 处理）。
- 持久化到 `providers.json`（随 provider 一起落盘）。
- 读取侧统一用 `getattr(model, "model_type", "chat")` 兜底，避免旧对象缺字段。

### 2.2 默认模型槽
`DefaultModelsConfig`（每个类型一个 slot）已存在，本次不改结构，仅确保 5 个类型 slot 都被正确读写与校验。

## 3. 类型推断（后端唯一权威）

### 3.1 新文件 `server/coapis/providers/model_type.py`
集中所有类型推断逻辑，避免规则分散：

- `VALID_MODEL_TYPES = ("chat","embedding","rerank","audio","vision")`
- `is_valid_model_type(value) -> bool`
- `infer_model_type(model_id, model_name="") -> ModelType`

### 3.2 推断规则（大小写不敏感，对 `"{id} {name}"` 匹配，先命中先赢）
| 优先级 | 关键词 / 特征 | 类型 |
|---|---|---|
| 1 | 含 `rerank` | `rerank` |
| 2 | 含 `embed` / `bge` / `e5-` | `embedding` |
| 3 | 含 `whisper` / `asr` / `tts` / `speech` / `speak` | `audio` |
| 4 | 含 `vision` / `omni` / `llava` / `clip` / `-vl` / `_vl` / `vl-`，或以 `vl` 结尾 | `vision` |
| 5 | 其它 | `chat` |

### 3.3 应用时机（重要）
推断**只用于“首次进入系统”的新模型**：
- 通过“添加模型”表单且 `model_type` 选“自动”时 → 走 `infer_model_type`。
- 通过“自动发现模型”且该模型是**新增**时 → 走 `infer_model_type`。
- **重新发现已存在的模型 → 保留用户已设置的 `model_type`**（不覆盖）。
- 用户通过 UI/API 显式设置后，**始终优先**，可随时改。

## 4. 后端 API 变更

### 4.1 新增 / 修改端点（`coapis/app/routers/providers.py`，prefix `/models`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/models/by-type/{model_type}` | **新增**：跨所有提供商返回某类型的模型列表 |
| PUT | `/{provider_id}/models/{model_id:path}` | **新增**：更新模型可变元数据（`model_type` / `name` / `is_free`），落盘 |
| POST | `/{provider_id}/models` | 添加模型时 `model_type` 可为空 → 自动推断 |

请求/校验：
- `AddModelRequest.model_type` / `UpdateModelRequest.model_type` 均为 `Optional[str]`，并用 `field_validator` 校验必须属于 `VALID_MODEL_TYPES`（`None` 允许，代表“自动”）。

### 4.2 `ProviderManager` 新增方法（`provider_manager.py`）
- `update_model_metadata(provider_id, model_id, metadata) -> ProviderInfo`：更新并落盘（内置 / 插件两条路径）。
- `_clear_stale_default_models(provider_id, model_ids=None)`：删除 / 隐藏模型时，清理指向它们的默认模型槽（`model_ids=None` 表示整提供商级别清理）；chat 默认同步清理 `active_model`。
- `deactivate_model(provider_id)`：此前**缺失**（删除提供商时前端调它导致 500 死引用），本次补上。
- `get_models_by_type(model_type)`：聚合所有 provider 中该类型的模型。
- 发现模型时（约 L949-974）：新增模型用 `infer_model_type`，已有模型保留旧 `model_type`。

### 4.3 类型一致性校验
`set_default_model` 校验 `model.model_type == model_type`，不一致抛 `ModelTypeMismatch`（防止把 chat 模型设成 embedding 默认）。

## 5. 前端变更

### 5.1 类型定义
`client/src/api/types/provider.ts`：`ModelInfo` 增加 `model_type?: "chat"|"embedding"|"rerank"|"audio"|"vision"`。
`client/src/api/modules/provider.ts`：增加 `updateModel`（PUT 元数据）、`getModelsByType` 等 API 封装。

### 5.2 主界面两区布局（`pages/Settings/Models/index.tsx`）
- **默认模型栏（DefaultModelBar）**：置顶。每类型一个 chip，点开直接切换该类型默认模型（即改即存），三态：已设置 / 未设置 / 已失效（指向已删模型）。
- **已配置模型（ConfiguredModelsSection）**：扁平表格（模型 / 提供商 / 类型 / 能力 / 免费 / 默认 / 操作），上方“类型筛选 tabs + 搜索框”紧耦合一行。唯一操作是“设为默认”。
- **提供商（ProviderCard 分组紧凑卡）**：按 可用（有模型）/ 未就绪 分组，卡上带类型 chip 计数（如 `💬1`）。管理 CRUD 在提供商“模型”弹窗里。

### 5.3 新增组件
- `components/sections/DefaultModelBar.tsx`：默认模型 chip 栏。
- `components/sections/ConfiguredModelsSection.tsx`：已配置模型表格区。
- `components/CapabilityTags.tsx`：能力标签（文本 / 多模态 / 未检测）。
- `components/ModelTypeTabs.tsx`：类型筛选 tabs（带各类型计数）。

### 5.4 提供商模型弹窗（`modals/RemoteModelManageModal.tsx`）
- 顶部类型筛选 tabs。
- 每个模型行：名称 + ID / **类型 Select（即改即存）** / 能力·免费·默认标签 / 配置·删除。
- “添加模型”表单：类型字段含“自动推断”选项（选中时前端用与后端一致的规则预览推断结果）。
- “自动发现模型”：新增模型按后端推断结果落类型。

### 5.5 i18n
`client/src/locales/{zh,en}.json` 新增 models 下相关 key（类型标签、能力、无效默认、占位符等）。

## 6. 测试

`server/tests/unit/test_model_type.py`：覆盖 `infer_model_type` 各规则分支、`is_valid_model_type` 边界、优先级（rerank > embedding 等）。
后端集成验证（dev 实测 12/12 通过）：
- 添加 / 更新 `model_type` 落盘 ✅
- `by-type/embedding` 只返回嵌入模型 ✅
- `set_default_model` 类型不匹配拦截 ✅
- 删除模型清理 stale 默认槽 ✅

## 7. E2E 验证（dev 环境，2026-09-04）
- 两区布局、默认模型栏置顶、类型筛选 tabs 计数 ✅
- 把 Ollama `qwen3-embedding:0.6b` 从“对话模型”改成“嵌入模型”（弹窗行内 Select，即改即存）→ API 持久化为 `embedding` ✅
- 主界面 tabs 计数同步（嵌入模型 1）✅
- 默认模型栏“嵌入模型”下拉**只列出嵌入模型**（`qwen3-embedding:0.6b · Ollama`）✅
- `PUT /models/default-models` + `GET` 往返 ✅

### ✅ 已修复：刷新后默认模型误判“已失效” + 表格默认徽标不显示（2026-09-04 修复并 E2E 验证）
根因：`index.tsx` 的 `loadDefaultModels()` 把 `GET /models/default-models` 的响应**直接 cast** 成
`Record<string,{providerId,modelId}>`，但后端返回的是 **snake_case**（`provider_id`/`model_id`）。
于是 `value.providerId` 为 `undefined`，`DefaultModelBar` 的 `valueValid` 判定失败 → 误判“已失效”；
`ConfiguredModelsSection` 的 `isDefault` 同样读 `slot.providerId` → 表格默认徽标也不出现。
（写入路径 `setDefaultModel` 用 camelCase 存进 state，所以刚设置时正常，刷新后即失效——与现象一致。）

修复（单文件 `client/src/pages/Settings/Models/index.tsx`，`loadDefaultModels` 内加归一化）：
```ts
const normalized: Record<string, { providerId: string; modelId: string }> = {};
for (const [type, raw] of Object.entries(data as Record<string, any>)) {
  if (raw && typeof raw === "object" && (raw.provider_id || raw.providerId)) {
    normalized[type] = {
      providerId: raw.providerId ?? raw.provider_id,
      modelId: raw.modelId ?? raw.model_id,
    };
  }
}
setDefaultModels(normalized);
```
修一处，chip 与表格徽标两处读取同时修复（都读同一 `defaultModels` state）。

E2E 验证（dev，2026-09-04）：
- 刷新后默认模型栏“嵌入模型”显示 `qwen3-embedding:0.6b · Ollama`（不再“已失效”）✅
- 已配置模型表格“默认”列 ✓ 徽标正确出现 ✅
- 类型筛选 tabs 计数正常（全部 91 / 对话 90 / 嵌入 1）✅

### 补充确认：删除路径的默认清理（后端已内置，无需改）
三条删除路径均已接 `_clear_stale_default_models`，删除后默认槽自动清空：
| 操作 | 函数 | 清理 |
|---|---|---|
| 删除自定义提供商 | `remove_custom_provider` | `_clear_stale_default_models(provider_id)` |
| 删除内置提供商（实为隐藏） | `hide_builtin_provider` | `_clear_stale_default_models(provider_id)` |
| 删除单个模型 | `delete_model_from_provider` | `_clear_stale_default_models(provider_id, model_ids={model_id})` |

## 8. 文件清单

### 后端
| 文件 | 变更 |
|---|---|
| `server/coapis/providers/model_type.py` | 新增：推断工具 |
| `server/coapis/providers/provider.py` | `ModelInfo` 增 `model_type`；`update_model_metadata` |
| `server/coapis/providers/provider_manager.py` | 增 `update_model_metadata`/`_clear_stale_default_models`/`get_models_by_type`/`deactivate_model`；发现模型推断 |
| `server/coapis/app/routers/providers.py` | 增 `by-type`、`PUT 模型元数据`；请求校验 |
| `server/tests/unit/test_model_type.py` | 新增：单测 |

### 前端
| 文件 | 变更 |
|---|---|
| `client/src/api/types/provider.ts` | `ModelInfo.model_type` |
| `client/src/api/modules/provider.ts` | `updateModel` / `getModelsByType` |
| `client/src/locales/{zh,en}.json` | i18n key |
| `client/src/pages/Settings/Models/index.tsx` | 两区布局重排 |
| `.../components/ModelTypeTabs.tsx` | 类型 tabs（计数） |
| `.../components/CapabilityTags.tsx` | 新增 |
| `.../components/sections/DefaultModelBar.tsx` | 新增 |
| `.../components/sections/ConfiguredModelsSection.tsx` | 新增 |
| `.../components/modals/RemoteModelManageModal.tsx` | 行内类型 Select + 表单类型字段 + 筛选 tabs |

## 9. 部署
- dev：后端镜像重建 + 前端 bundle 重建（nginx md5 校验一致）。
- 生产（mycom）：**未动**，待 dev 验证 + 遗留 bug 修复后再部署。
- git：改动尚未提交（待确认）。
