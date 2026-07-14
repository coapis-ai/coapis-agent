# 模型配置整合方案

> 日期：2026-06-30
> 状态：待执行

## 1. 背景

当前系统中关于"模型"的概念有 5 个，导致数据流混乱、存储冗余：

| 概念 | 位置 | 问题 |
|------|------|------|
| `models` | Provider 内置模型 | 与 extra_models 分离无意义 |
| `extra_models` | Provider 用户追加模型 | 与 models 本质相同 |
| `visible_models` / `visible_to_users` | providers.json (不存在) | 形同虚设 |
| `custom_providers` | UserModelPrefs (用户级) | 与 ProviderManager 重复 |
| `global_models` | API 计算结果 | 是输出不是存储 |

## 2. 整合目标

**只保留一个概念：`models`**

- 每个 Provider 只有一个 `models[]` 列表
- 用 `source` 字段标记来源（`builtin` / `added`）
- `isAvailable` 由 Provider 自身配置状态决定（`isConfigured && hasModels`）
- 不需要管理员额外配置"可见模型池"
- 不需要用户级 `custom_providers`，统一由 ProviderManager 管理

## 3. 整合后数据流

```
ProviderManager (内存 + 磁盘)
├── builtin_providers/
│   └── openai.json
│       └── models: [{id: "gpt-4o", source: "builtin"}, {id: "xxx", source: "added"}]
├── custom_providers/
│   └── xiaomi_mimo.json
│       └── models: [{id: "mimo-v2.5", source: "added"}]
│
└── API /models/available
    └── 遍历所有 provider → isConfigured && hasModels → global_models
```

## 4. 删除清单

### 4.1 后端删除

| 删除项 | 文件 | 说明 |
|--------|------|------|
| `extra_models` 字段 | `provider.py` ProviderInfo | 合并到 models |
| `visible_to_users` / `visible_models` | `admin_providers.py` | 不再需要 |
| `providers.json` fallback | `admin_providers.py` | 文件不存在，删除 fallback |
| `UserModelPrefs.custom_providers` | `user_model_prefs.py` | 删除用户级 custom_providers |
| `/user/custom-providers` API | `user_model_prefs.py` | 删除整个路由 |
| `_get_available_models_for_users()` | `admin_providers.py` | 用 ProviderManager 直接替代 |

### 4.2 前端删除

| 删除项 | 文件 | 说明 |
|--------|------|------|
| `source: 'custom'` 分支 | `ModelSelector/index.tsx` | 统一读 global_models |
| `extra_models` 分离逻辑 | `RemoteProviderCard.tsx` | `models.length` 直接替代 |
| `extraModelIds` 分离逻辑 | `RemoteModelManageModal.tsx` | 简化模型管理 |
| `custom_providers` 相关 API | `user_model_prefs.ts` | 删除 API 调用 |

## 5. 改动文件清单

### 5.1 后端核心改动

#### `server/coapis/providers/provider.py`
- `ProviderInfo.models` → 保持不变（合并后唯一列表）
- `ProviderInfo.extra_models` → **删除**
- `ModelInfo` → 增加 `source: str = "builtin"` 字段
- `Provider.add_model()` → 改为向 `models` 添加，标记 `source="added"`
- `Provider.remove_model()` → 从 `models` 删除
- `Provider.get_info()` → 不再返回 `extra_models`

#### `server/coapis/providers/provider_manager.py`
- `_save_provider()` → 不再序列化 `extra_models`
- `_load_provider()` / `_init_from_storage()` → 合并加载逻辑
- `_migrate_legacy_providers()` → 迁移时合并 models + extra_models
- `fetch_provider_models()` → 结果存入 `models`，标记 `source="added"`
- 删除 `visible_to_users` / `visible_models` 相关逻辑

#### `server/coapis/app/routers/admin_providers.py`
- `get_public_available_models()` → 简化为遍历 ProviderManager
- 删除 `visible_to_users` / `visible_models` 参数
- 删除 `providers.json` fallback 逻辑
- 删除 `_get_available_models_for_users()`
- 更新 ProviderConfigRequest / UpdateProviderConfigRequest → 删除 visible 字段

#### `server/coapis/app/routers/user_model_prefs.py`
- `UserModelPrefs` → 删除 `custom_providers` 字段
- 删除 `/user/custom-providers` 全部 CRUD 路由
- `get_model_prefs()` → 不再返回 custom_providers

#### `server/coapis/app/routers/config_router.py`
- `get_config_models()` → 不再读 providers.json，用 ProviderManager

#### `server/coapis/app/routers/workspace/workspace_voice.py`
- `_list_transcription_providers()` → 不再读 providers.json，用 ProviderManager

#### `server/coapis/agents/utils/intent_classifier.py`
- `_get_provider_config()` → 不再读 providers.json，用 ProviderManager

### 5.2 前端核心改动

#### `client/src/api/types/provider.ts`
- `ProviderInfo.extra_models` → **删除**
- `ModelInfo` → 增加 `source?: string`

#### `client/src/pages/Chat/ModelSelector/index.tsx`
- 删除 `custom_providers` 分支，统一读 `global_models`

#### `client/src/pages/Settings/Models/components/cards/RemoteProviderCard.tsx`
- `provider.models.length + provider.extra_models.length` → `provider.models.length`

#### `client/src/pages/Settings/Models/components/modals/RemoteModelManageModal.tsx`
- 删除 `extraModelIds` 分离逻辑
- 合并后的 models 列表中，`source === "added"` 的可删除

#### `client/src/pages/Settings/Models/components/modals/ModelManageModal.tsx`
- 适配新结构

#### `client/src/pages/Settings/Models/components/sections/ModelsSection.tsx`
- 删除 `extra_models` 引用

#### `client/src/pages/Settings/Agents/components/AgentModal.tsx`
- 删除 `extra_models` 引用

#### `client/src/pages/Chat/index.tsx`
- 删除 `extra_models` 引用

#### `client/src/api/modules/user_model_prefs.ts`
- 删除 `custom_providers` 相关 API

## 6. 数据迁移

### 6.1 Provider 配置文件迁移

对每个 `.json` provider 文件，执行：
```python
# 合并 models + extra_models
all_models = provider.models + provider.extra_models
for m in all_models:
    if m not in provider.models:
        m.source = "added"  # 原 extra_models 中的
    else:
        m.source = "builtin"  # 原 models 中的
provider.models = all_models
# 删除 extra_models 字段
```

### 6.2 UserModelPrefs 迁移

对每个用户的 `model_prefs.json`：
- 删除 `custom_providers` 字段
- 用户自定义的 provider 迁移到 `ProviderManager.custom_providers`（如需要）

## 7. API 变更

### 删除的 API
- `GET /user/custom-providers`
- `POST /user/custom-providers`
- `PUT /user/custom-providers/{id}`
- `DELETE /user/custom-providers/{id}`

### 修改的 API
- `GET /models/available` → 返回格式不变，但数据源简化
- `GET /admin/providers` → 不再返回 `visible_to_users` / `visible_models`
- `PUT /admin/providers/{id}` → 不再接受 `visible_to_users` / `visible_models`

## 8. 回滚方案

- 代码回滚：`git revert` 相关 commit
- 数据回滚：Provider JSON 文件有 git 历史，可恢复
- 用户数据：`model_prefs.json` 中删除的 `custom_providers` 已迁移到 ProviderManager

## 9. 验证清单

- [ ] 模型管理界面：Provider 列表正常显示，模型计数正确
- [ ] 模型管理界面：添加/删除模型正常
- [ ] 聊天界面：模型下拉列表正确显示可用模型
- [ ] 聊天界面：选择模型后能正常对话
- [ ] Provider 配置：API key / base_url 修改正常保存
- [ ] 新增 Provider：自定义 Provider 添加正常
- [ ] 数据迁移：旧的 extra_models 正确合并到 models
