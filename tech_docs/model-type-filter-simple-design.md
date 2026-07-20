# 模型分类筛选 - 极简实现方案

> **目标**: 在模型列表上方添加模型分类筛选，最小改动，保持现有设计
> 
> **创建时间**: 2026-07-18
> 
**状态**: ✅ 设计完成

---

## 一、UI 设计（极简）

### 现有界面

```
+--------------------------------------------------+
| 模型管理                                          |
+--------------------------------------------------+
| [默认LLM模型选择卡片]                             |
|                                                  |
| 提供商                                            |
| [🔍 搜索...] [🔄] [+ 添加提供商]                  |
|                                                  |
| [OpenAI 提供商卡片]                              |
| [DeepSeek 提供商卡片]                            |
| [Qwen 提供商卡片]                                |
+--------------------------------------------------+
```

### 改进后界面

```
+----------------------------------------------------------+
| 模型管理                                                  |
+----------------------------------------------------------+
| [默认LLM模型选择卡片]                                     |
|                                                            |
| 提供商                      [全部类型 ▼]  [🔍 搜索...]    |
|                            [🔄] [+ 添加提供商]            |
|                                                            |
| [OpenAI 提供商卡片]                                        |
| [DeepSeek 提供商卡片]                                      |
| [Qwen 提供商卡片]                                          |
+----------------------------------------------------------+
```

### 筛选下拉框选项

```
[全部类型 ▼]
 ├─ 全部类型
 ├─ 💬 对话模型
 ├─ 🔢 嵌入模型
 ├─ 🔄 重排序模型
 ├─ 🎵 音频模型
 └─ 👁 视觉模型
```

---

## 二、实现方案（最小改动）

### 2.1 后端 API 修改

#### 修改 ProviderManager

```python
# server/coapis/providers/provider_manager.py

def list_providers(
    self,
    model_type: Optional[str] = None
) -> List[ProviderInfo]:
    """列出所有提供商
    
    Args:
        model_type: 可选的模型类型筛选 (chat/embedding/rerank/audio/vision)
    """
    providers = []
    
    for provider_id in self._providers.keys():
        provider_info = self.get_provider(provider_id)
        
        # 如果指定了模型类型，筛选提供商
        if model_type:
            has_type = any(
                m.model_type == model_type
                for m in provider_info.models
            )
            if not has_type:
                continue
        
        providers.append(provider_info)
    
    return providers
```

#### 修改 API 路由

```python
# server/coapis/app/routers/providers.py

@router.get("")
async def list_providers(
    model_type: Optional[str] = Query(
        None, 
        description="模型类型筛选: chat, embedding, rerank, audio, vision"
    ),
    current_user: dict = Depends(get_current_user_optional),
):
    """列出所有提供商"""
    pm = ProviderManager.get_instance()
    
    providers = pm.list_providers(model_type=model_type)
    
    return [p.model_dump() for p in providers]
```

---

### 2.2 前端修改

#### 修改 index.tsx

```typescript
// client/src/pages/Settings/Models/index.tsx

function ModelsPage() {
  const { t } = useTranslation();
  const { providers, activeModels, loading, error, fetchAll } = useProviders();
  const [addProviderOpen, setAddProviderOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  
  // 新增：模型类型筛选
  const [modelTypeFilter, setModelTypeFilter] = useState<string | undefined>(undefined);
  
  // 模型类型选项
  const modelTypeOptions = [
    { value: undefined, label: t("models.allTypes") },
    { value: "chat", label: "💬 " + t("models.chatModels") },
    { value: "embedding", label: "🔢 " + t("models.embeddingModels") },
    { value: "rerank", label: "🔄 " + t("models.rerankModels") },
    { value: "audio", label: "🎵 " + t("models.audioModels") },
    { value: "vision", label: "👁 " + t("models.visionModels") },
  ];
  
  const { sortedProviders } = useMemo(() => {
    // ... 现有排序逻辑 ...
    
    // 新增：模型类型筛选
    let filtered = sorted;
    if (modelTypeFilter) {
      filtered = sorted.filter((p) =>
        p.models.some((m) => m.model_type === modelTypeFilter)
      );
    }
    
    // 现有：搜索筛选
    const query = searchQuery.trim().toLowerCase();
    if (query) {
      filtered = filtered.filter((p) =>
        p.name.toLowerCase().includes(query)
      );
    }
    
    return { sortedProviders: filtered };
  }, [providers, searchQuery, modelTypeFilter]);
  
  return (
    <div className={styles.modelsPage}>
      {/* 现有：默认LLM选择 */}
      <ModelsSection ... />
      
      {/* 提供商列表 */}
      <div className={styles.providersSection}>
        <div className={styles.providersHeader}>
          <h2 className={styles.sectionTitle}>{t("models.providers")}</h2>
          
          {/* 新增：筛选器行 */}
          <div className={styles.filtersRow}>
            <Select
              style={{ width: 150 }}
              value={modelTypeFilter}
              onChange={setModelTypeFilter}
              options={modelTypeOptions}
              allowClear
              placeholder={t("models.allTypes")}
            />
            
            <Input
              prefix={<SearchOutlined />}
              placeholder={t("models.searchProviders")}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              style={{ width: 200 }}
            />
            
            <Button
              icon={<SyncOutlined />}
              onClick={refreshProvidersSilently}
            />
            
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => setAddProviderOpen(true)}
            >
              {t("models.addProvider")}
            </Button>
          </div>
        </div>
        
        {/* 现有：提供商卡片列表 */}
        {renderProviderCards(sortedProviders)}
      </div>
      
      {/* 现有：添加提供商弹窗 */}
      <CustomProviderModal ... />
    </div>
  );
}
```

#### 添加样式

```less
// client/src/pages/Settings/Models/index.module.less

.providersSection {
  margin-top: 24px;
}

.providersHeader {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.sectionTitle {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.filtersRow {
  display: flex;
  gap: 12px;
  align-items: center;
}
```

#### 添加国际化文本

```json
// client/src/locales/zh-CN/models.json

{
  "allTypes": "全部类型",
  "chatModels": "对话模型",
  "embeddingModels": "嵌入模型",
  "rerankModels": "重排序模型",
  "audioModels": "音频模型",
  "visionModels": "视觉模型"
}
```

```json
// client/src/locales/en-US/models.json

{
  "allTypes": "All Types",
  "chatModels": "Chat Models",
  "embeddingModels": "Embedding Models",
  "rerankModels": "Rerank Models",
  "audioModels": "Audio Models",
  "visionModels": "Vision Models"
}
```

---

## 三、工作量估算

| 任务 | 工作量 | 说明 |
|------|--------|------|
| 后端 API 修改 | 0.5小时 | ProviderManager + 路由 |
| 前端 UI 修改 | 1小时 | 筛选器 + 样式 |
| 国际化文本 | 0.2小时 | 中英文翻译 |
| 测试验证 | 0.3小时 | 功能测试 |
| **总计** | **2小时** | 极简实现 |

---

## 四、实施步骤

### Step 1: 后端修改（30分钟）

```bash
# 1. 修改 ProviderManager
server/coapis/providers/provider_manager.py

# 2. 修改 API 路由
server/coapis/app/routers/providers.py
```

### Step 2: 前端修改（60分钟）

```bash
# 1. 修改主页面
client/src/pages/Settings/Models/index.tsx

# 2. 添加样式
client/src/pages/Settings/Models/index.module.less

# 3. 添加国际化
client/src/locales/zh-CN/models.json
client/src/locales/en-US/models.json
```

### Step 3: 测试验证（20分钟）

```bash
# 1. 构建前端
cd client && npm run build

# 2. 重启后端
cd docker && docker compose restart server

# 3. 测试功能
# - 打开模型管理页面
# - 选择不同模型类型
# - 验证提供商列表正确筛选
```

---

## 五、可选增强（后续）

### 5.1 提供商卡片显示模型类型标签

```
+----------------------------------------------------------+
| OpenAI                                    [编辑] [管理]  |
+----------------------------------------------------------+
| 模型：gpt-4o 💬 | text-embedding-3 🔢 | whisper 🎵      |
+----------------------------------------------------------+
```

**实现**：在 ProviderCard 组件中，为每个模型添加类型图标。

### 5.2 模型管理弹窗分类显示

```
+----------------------------------------------------------+
| 管理模型 - OpenAI                                         |
+----------------------------------------------------------+
| [💬 对话] [🔢 嵌入] [🎵 音频]                             |
|                                                            |
| 💬 对话模型：                                              |
| - gpt-4o                                                   |
| - gpt-3.5-turbo                                            |
|                                                            |
| 🔢 嵌入模型：                                              |
| - text-embedding-3-large                                   |
+----------------------------------------------------------+
```

---

**文档版本**: v2.0（简化版）  
**创建日期**: 2026-07-18  
**状态**: ✅ 设计完成，待实施
