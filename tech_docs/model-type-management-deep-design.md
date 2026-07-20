# 模型类型管理 - 深入设计方案

> **目标**: 支持多种模型类型的筛选、默认设置、API 查询
> 
> **创建时间**: 2026-07-18
> 
**状态**: ✅ 设计完成

---

## 一、核心优化点分析

### 用户需求

1. ✅ Tab 不需要"全部"标签
2. ✅ 提供按类型获取模型的 API 接口
3. ✅ 默认模型区域按类型设置

### 当前架构问题

```python
# 当前：只支持一个 active_llm
{
  "provider_id": "baidu",
  "model": "glm-5"
}

# 问题：
# - 无法设置默认嵌入模型
# - 知识库不知道用哪个嵌入模型
# - 语音功能不知道用哪个音频模型
```

---

## 二、数据模型重构

### 2.1 默认模型配置结构

```python
# server/coapis/providers/provider.py

from typing import Literal, Optional, Dict
from pydantic import BaseModel, Field

# 模型类型枚举
ModelType = Literal["chat", "embedding", "rerank", "audio", "vision"]

# 默认模型配置
class DefaultModelSlot(BaseModel):
    """单个类型的默认模型"""
    provider_id: str
    model_id: str
    model_type: ModelType

class DefaultModelsConfig(BaseModel):
    """所有类型的默认模型配置"""
    
    # 对话模型（核心，必需）
    chat: DefaultModelSlot | None = None
    
    # 嵌入模型（知识库必需）
    embedding: DefaultModelSlot | None = None
    
    # 重排序模型（知识库可选）
    rerank: DefaultModelSlot | None = None
    
    # 音频模型（语音功能）
    audio: DefaultModelSlot | None = None
    
    # 视觉模型（图片/视频理解）
    vision: DefaultModelSlot | None = None
    
    def get_by_type(self, model_type: ModelType) -> DefaultModelSlot | None:
        """按类型获取默认模型"""
        return getattr(self, model_type, None)
    
    def set_by_type(self, model_type: ModelType, slot: DefaultModelSlot) -> None:
        """按类型设置默认模型"""
        if hasattr(self, model_type):
            setattr(self, model_type, slot)
    
    def to_dict(self) -> Dict[str, Dict]:
        """导出为字典格式"""
        result = {}
        for field in ["chat", "embedding", "rerank", "audio", "vision"]:
            slot = getattr(self, field)
            if slot:
                result[field] = {
                    "provider_id": slot.provider_id,
                    "model_id": slot.model_id,
                }
        return result
```

### 2.2 配置文件存储

```json
// data/system/.secret/providers/default_models.json

{
  "chat": {
    "provider_id": "openai",
    "model_id": "gpt-4o"
  },
  "embedding": {
    "provider_id": "openai",
    "model_id": "text-embedding-3-large"
  },
  "rerank": {
    "provider_id": "cohere",
    "model_id": "rerank-english-v3.0"
  },
  "audio": {
    "provider_id": "openai",
    "model_id": "whisper-1"
  },
  "vision": null
}
```

### 2.3 ModelInfo 扩展（已完成）

```python
# server/coapis/providers/provider.py

class ModelInfo(BaseModel):
    """模型信息"""
    id: str
    name: str
    
    # 新增：模型类型
    model_type: ModelType = "chat"
    
    # 对话模型专用字段
    supports_image: bool = False
    supports_video: bool = False
    
    # 嵌入模型专用字段
    embedding_dimension: int | None = None
    max_sequence_length: int | None = None
    
    # 其他字段
    probe_source: str | None = None
    is_free: bool = False
    generate_kwargs: dict = {}
```

---

## 三、API 接口设计

### 3.1 按类型获取模型列表

```python
# server/coapis/app/routers/providers.py

@router.get("/by-type/{model_type}")
async def get_models_by_type(
    model_type: ModelType = Path(
        ..., 
        description="模型类型: chat, embedding, rerank, audio, vision"
    ),
    configured_only: bool = Query(
        True,
        description="只返回已配置的提供商的模型"
    ),
    manager: ProviderManager = Depends(get_provider_manager),
) -> List[Dict[str, Any]]:
    """获取指定类型的所有模型
    
    用途：
    - 知识库设置中选择嵌入模型
    - 语音功能选择音频模型
    - 模型管理页面的 Tab 筛选
    
    Args:
        model_type: 模型类型
        configured_only: 是否只返回已配置的提供商
        
    Returns:
        模型列表，每个模型包含提供商信息
    """
    
    result = []
    
    for provider_id in manager.list_providers():
        provider = manager.get_provider(provider_id)
        
        # 筛选条件：已配置的提供商
        if configured_only:
            if not manager.is_provider_configured(provider_id):
                continue
        
        # 筛选该提供商中指定类型的模型
        for model in provider.models:
            if model.model_type == model_type:
                result.append({
                    "provider_id": provider_id,
                    "provider_name": provider.name,
                    "model_id": model.id,
                    "model_name": model.name,
                    "model_type": model.model_type,
                    "supports_image": model.supports_image,
                    "embedding_dimension": model.embedding_dimension,
                    "is_free": model.is_free,
                })
    
    return result
```

### 3.2 获取/设置默认模型

```python
# server/coapis/app/routers/providers.py

@router.get("/default-models")
async def get_default_models(
    manager: ProviderManager = Depends(get_provider_manager),
) -> Dict[str, Any]:
    """获取所有类型的默认模型
    
    Returns:
        {
            "chat": {"provider_id": "openai", "model_id": "gpt-4o"},
            "embedding": {"provider_id": "openai", "model_id": "text-embedding-3"},
            ...
        }
    """
    return manager.get_default_models().to_dict()


@router.get("/default-models/{model_type}")
async def get_default_model_by_type(
    model_type: ModelType = Path(...),
    manager: ProviderManager = Depends(get_provider_manager),
) -> Dict[str, str] | None:
    """获取指定类型的默认模型
    
    Args:
        model_type: chat | embedding | rerank | audio | vision
        
    Returns:
        {"provider_id": "openai", "model_id": "gpt-4o"} 或 None
    """
    slot = manager.get_default_models().get_by_type(model_type)
    if slot:
        return {
            "provider_id": slot.provider_id,
            "model_id": slot.model_id,
        }
    return None


class SetDefaultModelRequest(BaseModel):
    provider_id: str
    model_id: str
    model_type: ModelType


@router.put("/default-models")
@require_permission("models:write")
async def set_default_model(
    request: SetDefaultModelRequest,
    manager: ProviderManager = Depends(get_provider_manager),
    current_user: dict = Depends(get_current_user),
) -> Dict[str, str]:
    """设置默认模型
    
    权限：models:write
    """
    # 验证模型是否存在
    provider = manager.get_provider(request.provider_id)
    if not provider:
        raise HTTPException(404, f"Provider {request.provider_id} not found")
    
    model = next(
        (m for m in provider.models if m.id == request.model_id),
        None
    )
    if not model:
        raise HTTPException(404, f"Model {request.model_id} not found")
    
    # 验证模型类型匹配
    if model.model_type != request.model_type:
        raise HTTPException(
            400,
            f"Model type mismatch: expected {request.model_type}, "
            f"got {model.model_type}"
        )
    
    # 设置默认模型
    manager.set_default_model(
        model_type=request.model_type,
        provider_id=request.provider_id,
        model_id=request.model_id,
    )
    
    return {
        "status": "ok",
        "message": f"Default {request.model_type} model set to {request.model_id}",
    }
```

### 3.3 ProviderManager 方法扩展

```python
# server/coapis/providers/provider_manager.py

class ProviderManager:
    # ... 现有代码 ...
    
    def __init__(self, ...):
        # ... 现有初始化 ...
        
        # 新增：默认模型配置
        self.default_models: DefaultModelsConfig = DefaultModelsConfig()
        
        # 加载默认模型配置
        self._load_default_models()
    
    def _load_default_models(self) -> None:
        """加载默认模型配置"""
        default_path = self.root_path / "default_models.json"
        
        if default_path.exists():
            try:
                data = json.loads(default_path.read_text())
                self.default_models = DefaultModelsConfig.model_validate(data)
            except Exception as e:
                logger.error(f"Failed to load default models: {e}")
                self.default_models = DefaultModelsConfig()
        else:
            # 迁移旧配置
            self._migrate_active_llm_to_default_models()
    
    def _migrate_active_llm_to_default_models(self) -> None:
        """迁移旧的 active_llm 配置到新的 default_models"""
        if self.active_model:
            self.default_models.chat = DefaultModelSlot(
                provider_id=self.active_model.provider_id,
                model_id=self.active_model.model,
                model_type="chat",
            )
            self._save_default_models()
    
    def _save_default_models(self) -> None:
        """保存默认模型配置"""
        default_path = self.root_path / "default_models.json"
        default_path.write_text(
            json.dumps(self.default_models.to_dict(), indent=2, ensure_ascii=False)
        )
    
    def get_default_models(self) -> DefaultModelsConfig:
        """获取所有默认模型配置"""
        return self.default_models
    
    def set_default_model(
        self,
        model_type: ModelType,
        provider_id: str,
        model_id: str,
    ) -> None:
        """设置指定类型的默认模型"""
        slot = DefaultModelSlot(
            provider_id=provider_id,
            model_id=model_id,
            model_type=model_type,
        )
        self.default_models.set_by_type(model_type, slot)
        self._save_default_models()
        
        logger.info(
            f"Default {model_type} model set: "
            f"{provider_id}/{model_id}"
        )
    
    def get_default_model_by_type(self, model_type: ModelType) -> DefaultModelSlot | None:
        """获取指定类型的默认模型"""
        return self.default_models.get_by_type(model_type)
    
    def list_providers_by_model_type(
        self,
        model_type: ModelType,
        configured_only: bool = True,
    ) -> List[ProviderInfo]:
        """列出包含指定类型模型的提供商
        
        Args:
            model_type: 模型类型
            configured_only: 是否只返回已配置的提供商
            
        Returns:
            提供商列表（模型已筛选）
        """
        result = []
        
        for provider_id in self.list_providers():
            provider = self.get_provider(provider_id)
            
            # 筛选已配置的提供商
            if configured_only and not self.is_provider_configured(provider_id):
                continue
            
            # 筛选该提供商中指定类型的模型
            matching_models = [
                m for m in provider.models 
                if m.model_type == model_type
            ]
            
            if matching_models:
                # 创建新的 ProviderInfo，只包含匹配的模型
                filtered_provider = ProviderInfo(
                    id=provider.id,
                    name=provider.name,
                    models=matching_models,
                    # ... 复制其他字段 ...
                )
                result.append(filtered_provider)
        
        return result
```

---

## 四、前端 UI 设计

### 4.1 模型管理页面

```
┌──────────────────────────────────────────────────────────┐
│ 模型管理                                                  │
├──────────────────────────────────────────────────────────┤
│ 默认模型设置                                              │
│ ┌──────────────────────────────────────────────────────┐ │
│ │ 💬 对话模型                                           │ │
│ │ [OpenAI / gpt-4o                              ▼]     │ │
│ ├──────────────────────────────────────────────────────┤ │
│ │ 🔢 嵌入模型                                           │ │
│ │ [OpenAI / text-embedding-3-large              ▼]     │ │
│ ├──────────────────────────────────────────────────────┤ │
│ │ 🔄 重排序模型                                         │ │
│ │ [未设置                                       ▼]     │ │
│ ├──────────────────────────────────────────────────────┤ │
│ │ 🎵 音频模型                                           │ │
│ │ [OpenAI / whisper-1                           ▼]     │ │
│ └──────────────────────────────────────────────────────┘ │
│                                                            │
│ 提供商列表                                                 │
│ ┌────────┬────────┬────────┬────────┬────────┐           │
│ │💬 对话 │🔢 嵌入 │🔄 重排│🎵 音频│👁 视觉 │           │
│ │ (28)   │ (5)    │ (2)   │ (2)    │ (0)    │           │
│ └────────┴────────┴────────┴────────┴────────┘           │
│                                                            │
│ [🔍 搜索...] [🔄] [+ 添加提供商]                           │
│                                                            │
│ [OpenAI 卡片]                                              │
│ [DeepSeek 卡片]                                            │
└──────────────────────────────────────────────────────────┘
```

### 4.2 默认模型选择器组件

```typescript
// client/src/pages/Settings/Models/components/DefaultModelSelector.tsx

interface DefaultModelSelectorProps {
  modelType: 'chat' | 'embedding' | 'rerank' | 'audio' | 'vision';
  label: string;
  icon: string;
  value?: { providerId: string; modelId: string };
  onChange: (value: { providerId: string; modelId: string }) => void;
}

function DefaultModelSelector({ modelType, label, icon, value, onChange }: Props) {
  const { t } = useTranslation();
  const [models, setModels] = useState<ModelsByType[]>([]);
  
  // 加载该类型的所有模型
  useEffect(() => {
    api.get(`/models/by-type/${modelType}`).then(res => setModels(res.data));
  }, [modelType]);
  
  // 构建选项：按提供商分组
  const options = useMemo(() => {
    const grouped = {};
    models.forEach(m => {
      if (!grouped[m.provider_name]) {
        grouped[m.provider_name] = [];
      }
      grouped[m.provider_name].push({
        value: `${m.provider_id}:${m.model_id}`,
        label: m.model_name,
        model: m,
      });
    });
    
    return Object.entries(grouped).map(([providerName, models]) => ({
      label: providerName,
      options: models,
    }));
  }, [models]);
  
  const handleChange = (combinedValue: string) => {
    const [providerId, modelId] = combinedValue.split(':');
    onChange({ providerId, modelId });
  };
  
  const currentValue = value 
    ? `${value.providerId}:${value.modelId}`
    : undefined;
  
  return (
    <div className={styles.defaultModelSelector}>
      <label>{icon} {label}</label>
      <Select
        style={{ width: '100%' }}
        value={currentValue}
        onChange={handleChange}
        options={options}
        placeholder={t('models.selectDefaultModel')}
        allowClear
        showSearch
      />
    </div>
  );
}
```

### 4.3 提供商筛选 Tab

```typescript
// client/src/pages/Settings/Models/components/ModelTypeTabs.tsx

const MODEL_TYPES = [
  { type: 'chat', icon: '💬', label: '对话' },
  { type: 'embedding', icon: '🔢', label: '嵌入' },
  { type: 'rerank', icon: '🔄', label: '重排' },
  { type: 'audio', icon: '🎵', label: '音频' },
  { type: 'vision', icon: '👁', label: '视觉' },
];

function ModelTypeTabs({ activeType, onChange, counts }: Props) {
  return (
    <div className={styles.modelTypeTabs}>
      {MODEL_TYPES.map(({ type, icon, label }) => (
        <div
          key={type}
          className={cn(styles.tab, activeType === type && styles.active)}
          onClick={() => onChange(type)}
        >
          <span className={styles.icon}>{icon}</span>
          <span className={styles.label}>{label}</span>
          <span className={styles.count}>({counts[type] || 0})</span>
        </div>
      ))}
    </div>
  );
}
```

### 4.4 样式设计

```less
// client/src/pages/Settings/Models/index.module.less

// 默认模型选择器
.defaultModelsSection {
  margin-bottom: 24px;
  padding: 20px;
  background: #fafafa;
  border-radius: 8px;
}

.defaultModelSelector {
  margin-bottom: 16px;
  
  &:last-child {
    margin-bottom: 0;
  }
  
  label {
    display: block;
    margin-bottom: 8px;
    font-weight: 500;
    color: #333;
  }
}

// Tab 样式
.modelTypeTabs {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
  border-bottom: 1px solid #e8e8e8;
  padding-bottom: 8px;
}

.tab {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
  
  &:hover {
    background: #f0f0f0;
  }
  
  &.active {
    background: #e6f4ff;
    color: #1677ff;
    font-weight: 500;
  }
  
  .icon {
    font-size: 16px;
  }
  
  .label {
    font-size: 14px;
  }
  
  .count {
    font-size: 12px;
    color: #999;
  }
}
```

---

## 五、使用场景示例

### 5.1 知识库创建时选择嵌入模型

```typescript
// client/src/pages/KnowledgeBase/CreateKB.tsx

function CreateKnowledgeBase() {
  const [embeddingModels, setEmbeddingModels] = useState([]);
  const [selectedModel, setSelectedModel] = useState(null);
  
  useEffect(() => {
    // 加载所有嵌入模型
    api.get('/models/by-type/embedding').then(res => {
      setEmbeddingModels(res.data);
      
      // 如果没有选择，使用默认嵌入模型
      if (!selectedModel) {
        api.get('/models/default-models/embedding').then(defaultRes => {
          if (defaultRes.data) {
            setSelectedModel(defaultRes.data);
          }
        });
      }
    });
  }, []);
  
  // ...
}
```

### 5.2 后端知识库服务使用默认嵌入模型

```python
# server/coapis/services/knowledge_base.py

class KnowledgeBaseService:
    async def create_collection(self, name: str, embedding_model: dict | None = None):
        """创建知识库
        
        Args:
            name: 知识库名称
            embedding_model: 嵌入模型配置，如果为 None 则使用默认
        """
        
        if embedding_model is None:
            # 使用默认嵌入模型
            pm = ProviderManager.get_instance()
            default_embedding = pm.get_default_model_by_type("embedding")
            
            if not default_embedding:
                raise ValueError("No default embedding model configured")
            
            embedding_model = {
                "provider_id": default_embedding.provider_id,
                "model_id": default_embedding.model_id,
            }
        
        # 创建向量集合...
```

---

## 六、实施步骤

### Step 1: 后端数据模型和 API（2小时）

```bash
# 1. 扩展 ModelInfo
server/coapis/providers/provider.py

# 2. 新增 DefaultModelsConfig
server/coapis/providers/provider.py

# 3. 扩展 ProviderManager
server/coapis/providers/provider_manager.py

# 4. 新增 API 路由
server/coapis/app/routers/providers.py
```

### Step 2: 前端 UI 组件（2小时）

```bash
# 1. 默认模型选择器
client/src/pages/Settings/Models/components/DefaultModelSelector.tsx

# 2. 模型类型 Tab
client/src/pages/Settings/Models/components/ModelTypeTabs.tsx

# 3. 修改主页面
client/src/pages/Settings/Models/index.tsx
```

### Step 3: 国际化和测试（1小时）

```bash
# 1. 国际化文本
client/src/locales/zh-CN/models.json
client/src/locales/en-US/models.json

# 2. 功能测试
# - 验证默认模型设置
# - 验证提供商筛选
# - 验证 API 返回正确
```

**总计：5小时**

---

## 七、向后兼容性

### 迁移策略

```python
# ProviderManager 初始化时自动迁移

def __init__(self, ...):
    # ... 现有初始化 ...
    
    # 加载新的默认模型配置
    self._load_default_models()
    
    # 如果新配置为空，尝试从旧的 active_llm 迁移
    if not self.default_models.chat and self.active_model:
        self._migrate_active_llm_to_default_models()
        logger.info("Migrated active_llm to default_models.chat")
```

### API 兼容性

```python
# 保持旧的 API 兼容

@router.get("/active")
async def get_active_models(...):
    """旧 API，返回 active_llm（兼容性）"""
    default_chat = manager.get_default_model_by_type("chat")
    
    if default_chat:
        return {
            "active_llm": {
                "provider_id": default_chat.provider_id,
                "model": default_chat.model_id,
            }
        }
    
    return {"active_llm": None}
```

---

**文档版本**: v3.0（深入设计）  
**创建日期**: 2026-07-18  
**状态**: ✅ 设计完成，待实施
