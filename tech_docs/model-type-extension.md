# 模型类型扩展方案 - 社区版

> **目标**: 在社区版 ProviderManager 基础上，扩展支持嵌入、重排序、音频等多种模型类型
> 
> **创建时间**: 2026-07-18
> 
> **优先级**: P0（知识库功能依赖）
> 
> **影响范围**: 社区版核心模块

---

## 一、背景与目标

### 1.1 当前状况

社区版 ProviderManager 目前主要支持：
- ✅ Chat 模型（文本生成、多模态对话）
- ✅ 模型发现机制（fetch_provider_models）
- ✅ JSON 配置管理
- ✅ API Key 加密存储

### 1.2 需求驱动

企业版知识库功能需要：
- ❌ Embedding 模型（向量化、语义搜索）
- ❌ Rerank 模型（搜索结果重排序）
- ❌ Audio 模型（语音识别、语音合成）

### 1.3 扩展目标

**最小改动原则**：
- 向后兼容现有配置
- 新增字段为可选，默认值不影响现有功能
- 不破坏现有架构

**支持模型类型**：
- `chat` - 对话模型（现有）
- `embedding` - 嵌入模型（新增）
- `rerank` - 重排序模型（新增）
- `audio` - 音频模型（新增）
- `vision` - 视觉模型（新增）

---

## 二、技术方案

### 2.1 ModelInfo 扩展

**文件**: `coapis/providers/provider.py`

**修改内容**:

```python
class ModelInfo(BaseModel):
    """Model information."""
    
    # ===== 现有字段（保持不变）=====
    id: str = Field(..., description="Model identifier used in API calls")
    name: str = Field(..., description="Human-readable model name")
    supports_multimodal: bool | None = Field(
        default=None,
        description="Whether this model supports multimodal input "
        "(image/audio/video). None means not yet probed.",
    )
    supports_image: bool | None = Field(
        default=None,
        description="Whether this model supports image input. "
        "None means not yet probed.",
    )
    supports_video: bool | None = Field(
        default=None,
        description="Whether this model supports video input. "
        "None means not yet probed.",
    )
    probe_source: str | None = Field(
        default=None,
        description=(
            "Probe result source: 'documentation' (from docs)"
            " or 'probed' (actual probe)"
        ),
    )
    is_free: bool = Field(
        default=False,
        description="Whether this model is free to use (e.g., no API cost)",
    )
    generate_kwargs: Dict[str, Any] = Field(
        default_factory=dict,
        description="Per-model generation parameters that override "
        "provider-level generate_kwargs.",
    )
    source: str = Field(
        default="builtin",
        description="Model source: 'builtin' (defined in code) "
        "or 'added' (user-added via UI/API).",
    )
    
    # ===== 新增字段（可选，默认值兼容）=====
    model_type: str = Field(
        default="chat",
        description="模型类型: chat/embedding/rerank/audio/vision"
    )
    
    # 嵌入模型专用字段
    embedding_dimension: Optional[int] = Field(
        default=None,
        description="嵌入向量维度（仅嵌入模型，如 1024, 1536）"
    )
    max_sequence_length: Optional[int] = Field(
        default=None,
        description="最大序列长度（仅嵌入模型，如 8192, 32768）"
    )
    
    # 重排序模型专用字段
    rerank_top_k: Optional[int] = Field(
        default=None,
        description="重排序TopK数量（仅重排序模型）"
    )
    
    # 音频模型专用字段
    audio_sample_rate: Optional[int] = Field(
        default=None,
        description="音频采样率（仅音频模型，如 16000, 44100）"
    )
```

### 2.2 ProviderInfo 扩展

**文件**: `coapis/providers/provider.py`

**修改内容**:

```python
class ProviderInfo(BaseModel):
    """Provider information."""
    
    # ===== 现有字段（保持不变）=====
    id: str
    name: str
    base_url: str = ""
    api_key: str = ""
    models: List[ModelInfo] = []
    is_local: bool = False
    is_custom: bool = False
    support_model_discovery: bool = False
    owner: str = ""
    
    # ===== 新增字段（可选）=====
    supported_model_types: List[str] = Field(
        default=["chat"],
        description="支持的模型类型列表: chat/embedding/rerank/audio/vision"
    )
```

---

## 三、配置示例

### 3.1 Qwen 本地部署（支持对话和嵌入）

```json
{
  "id": "qwen-local",
  "name": "Qwen本地部署",
  "base_url": "http://localhost:8082/v1",
  "api_key": "",
  "is_local": true,
  "support_model_discovery": true,
  "supported_model_types": ["chat", "embedding"],
  "models": [
    {
      "id": "Qwen3-Embedding-0.6B",
      "name": "Qwen3嵌入模型0.6B",
      "model_type": "embedding",
      "embedding_dimension": 1024,
      "max_sequence_length": 32768,
      "supports_image": false,
      "supports_video": false,
      "is_free": true
    },
    {
      "id": "Qwen3-Chat-8B",
      "name": "Qwen3对话模型8B",
      "model_type": "chat",
      "supports_image": true,
      "supports_video": false
    }
  ]
}
```

### 3.2 OpenAI（支持对话、嵌入、音频）

```json
{
  "id": "openai",
  "name": "OpenAI",
  "base_url": "https://api.openai.com/v1",
  "supported_model_types": ["chat", "embedding", "audio"],
  "models": [
    {
      "id": "gpt-4o",
      "name": "GPT-4o",
      "model_type": "chat",
      "supports_image": true,
      "supports_video": true
    },
    {
      "id": "text-embedding-3-large",
      "name": "Text Embedding 3 Large",
      "model_type": "embedding",
      "embedding_dimension": 3072,
      "max_sequence_length": 8191
    },
    {
      "id": "whisper-1",
      "name": "Whisper",
      "model_type": "audio",
      "audio_sample_rate": 16000
    }
  ]
}
```

### 3.3 Cohere（支持对话、嵌入、重排序）

```json
{
  "id": "cohere",
  "name": "Cohere",
  "base_url": "https://api.cohere.ai/v1",
  "supported_model_types": ["chat", "embedding", "rerank"],
  "models": [
    {
      "id": "command-r",
      "name": "Command R",
      "model_type": "chat"
    },
    {
      "id": "embed-english-v3.0",
      "name": "Embed English v3",
      "model_type": "embedding",
      "embedding_dimension": 1024
    },
    {
      "id": "rerank-english-v3.0",
      "name": "Rerank English v3",
      "model_type": "rerank",
      "rerank_top_k": 100
    }
  ]
}
```

---

## 四、向后兼容性

### 4.1 现有配置无需改动

```json
// 现有配置（无需修改）
{
  "id": "deepseek",
  "name": "DeepSeek",
  "models": [
    {
      "id": "deepseek-chat",
      "name": "DeepSeek Chat"
      // 没有 model_type 字段 → 自动默认为 "chat"
    }
  ]
}
```

### 4.2 加载逻辑

```python
# Pydantic 自动处理缺失字段
model = ModelInfo(
    id="deepseek-chat",
    name="DeepSeek Chat"
    # model_type 缺失 → 自动使用默认值 "chat"
)

print(model.model_type)  # 输出: "chat"
print(model.embedding_dimension)  # 输出: None
```

### 4.3 测试验证

```python
# 测试向后兼容性
from coapis.providers.provider import ModelInfo

# 测试1：现有配置加载
m1 = ModelInfo(id="test", name="Test")
assert m1.model_type == "chat"  # 默认值
assert m1.embedding_dimension is None

# 测试2：新配置加载
m2 = ModelInfo(
    id="test-embedding",
    name="Test Embedding",
    model_type="embedding",
    embedding_dimension=1024
)
assert m2.model_type == "embedding"
assert m2.embedding_dimension == 1024

print("✅ 向后兼容性测试通过")
```

---

## 五、实现步骤

### 步骤1：修改数据模型（30分钟）

```bash
# 编辑文件
vim coapis/providers/provider.py

# 修改内容：
# 1. ModelInfo 增加 model_type 等字段
# 2. ProviderInfo 增加 supported_model_types 字段
```

### 步骤2：向后兼容测试（30分钟）

```bash
cd coapis-agent/server

# 运行测试
python3 << 'EOF'
from coapis.providers.provider import ModelInfo, ProviderInfo

# 测试现有配置
m = ModelInfo(id="test", name="Test")
print(f"model_type: {m.model_type}")
print(f"embedding_dimension: {m.embedding_dimension}")

# 测试新配置
m2 = ModelInfo(
    id="test-embedding",
    name="Test Embedding",
    model_type="embedding",
    embedding_dimension=1024
)
print(f"model_type: {m2.model_type}")
print(f"embedding_dimension: {m2.embedding_dimension}")

print("✅ 测试通过")
EOF
```

### 步骤3：创建嵌入模型配置（15分钟）

```bash
# 创建 Qwen 本地部署配置
cat > ~/.coapis/.secrets/providers/custom/qwen-local.json << 'EOF'
{
  "id": "qwen-local",
  "name": "Qwen本地部署",
  "base_url": "http://localhost:8082/v1",
  "api_key": "",
  "is_local": true,
  "support_model_discovery": true,
  "supported_model_types": ["chat", "embedding"],
  "models": [
    {
      "id": "Qwen3-Embedding-0.6B",
      "name": "Qwen3嵌入模型0.6B",
      "model_type": "embedding",
      "embedding_dimension": 1024,
      "max_sequence_length": 32768,
      "supports_image": false,
      "supports_video": false,
      "is_free": true
    }
  ]
}
EOF
```

### 步骤4：验证加载（15分钟）

```python
from coapis.providers.provider_manager import ProviderManager

pm = ProviderManager.get_instance()
provider = pm.get_provider("qwen-local")

if provider:
    print(f"Provider: {provider.name}")
    print(f"Supported types: {provider.supported_model_types}")
    
    for model in provider.models:
        print(f"  - {model.id} ({model.model_type})")
        if model.model_type == "embedding":
            print(f"    dimension: {model.embedding_dimension}")
            print(f"    max_length: {model.max_sequence_length}")
else:
    print("❌ Provider not found")
```

---

## 六、知识库集成

### 6.1 获取嵌入模型

```python
from coapis.providers.provider_manager import ProviderManager

def get_embedding_model():
    """获取嵌入模型"""
    pm = ProviderManager.get_instance()
    
    # 方式1：从指定提供商获取
    provider = pm.get_provider("qwen-local")
    if provider:
        embedding_model = next(
            (m for m in provider.models if m.model_type == "embedding"),
            None
        )
        if embedding_model:
            return provider, embedding_model
    
    # 方式2：遍历所有提供商查找
    for provider_id in pm.list_providers():
        provider = pm.get_provider(provider_id)
        if "embedding" in provider.supported_model_types:
            embedding_model = next(
                (m for m in provider.models if m.model_type == "embedding"),
                None
            )
            if embedding_model:
                return provider, embedding_model
    
    return None, None

# 使用示例
provider, model = get_embedding_model()
if model:
    print(f"使用嵌入模型: {provider.id}/{model.id}")
    print(f"向量维度: {model.embedding_dimension}")
```

### 6.2 调用嵌入模型

```python
import httpx

async def call_embedding_api(
    provider,
    model,
    texts: list[str]
) -> list[list[float]]:
    """调用嵌入模型API"""
    
    url = f"{provider.base_url}/embeddings"
    headers = {
        "Authorization": f"Bearer {provider.api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": model.id,
        "input": texts,
        "encoding_format": "float"
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            headers=headers,
            json=payload,
            timeout=30.0
        )
        response.raise_for_status()
        
        data = response.json()
        embeddings = [item["embedding"] for item in data["data"]]
        
        return embeddings

# 使用示例
texts = ["这是第一段文本", "这是第二段文本"]
embeddings = await call_embedding_api(provider, model, texts)

print(f"生成了 {len(embeddings)} 个向量")
print(f"向量维度: {len(embeddings[0])}")
```

---

## 七、测试清单

### 7.1 单元测试

```python
# tests/test_model_type_extension.py

import pytest
from coapis.providers.provider import ModelInfo, ProviderInfo


def test_model_info_default_values():
    """测试 ModelInfo 默认值"""
    m = ModelInfo(id="test", name="Test")
    
    assert m.model_type == "chat"
    assert m.embedding_dimension is None
    assert m.max_sequence_length is None
    assert m.rerank_top_k is None
    assert m.audio_sample_rate is None


def test_model_info_embedding():
    """测试嵌入模型配置"""
    m = ModelInfo(
        id="test-embedding",
        name="Test Embedding",
        model_type="embedding",
        embedding_dimension=1024,
        max_sequence_length=8192
    )
    
    assert m.model_type == "embedding"
    assert m.embedding_dimension == 1024
    assert m.max_sequence_length == 8192


def test_provider_info_default_values():
    """测试 ProviderInfo 默认值"""
    p = ProviderInfo(id="test", name="Test")
    
    assert p.supported_model_types == ["chat"]


def test_provider_info_multiple_types():
    """测试多模型类型提供商"""
    p = ProviderInfo(
        id="test",
        name="Test",
        supported_model_types=["chat", "embedding", "rerank"]
    )
    
    assert "chat" in p.supported_model_types
    assert "embedding" in p.supported_model_types
    assert "rerank" in p.supported_model_types


def test_backward_compatibility():
    """测试向后兼容性"""
    # 现有JSON加载
    import json
    
    json_str = '{"id": "test", "name": "Test"}'
    data = json.loads(json_str)
    m = ModelInfo(**data)
    
    assert m.model_type == "chat"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

### 7.2 集成测试

```bash
# 测试 ProviderManager 加载新配置
python3 << 'EOF'
from coapis.providers.provider_manager import ProviderManager

pm = ProviderManager.get_instance()

# 测试加载现有提供商
providers = pm.list_providers()
print(f"✅ 加载了 {len(providers)} 个提供商")

# 测试加载新配置提供商
provider = pm.get_provider("qwen-local")
if provider:
    print(f"✅ Provider: {provider.name}")
    print(f"✅ Supported types: {provider.supported_model_types}")
    
    for model in provider.models:
        print(f"  ✅ Model: {model.id} ({model.model_type})")
else:
    print("❌ Provider not found")
EOF
```

---

## 八、文档更新

### 8.1 README 更新

在 `coapis/README.md` 中添加：

```markdown
## 模型类型支持

CoApis 社区版支持多种模型类型：

- **Chat**: 对话模型，支持文本生成和多模态对话
- **Embedding**: 嵌入模型，支持文本向量化
- **Rerank**: 重排序模型，支持搜索结果重排序
- **Audio**: 音频模型，支持语音识别和语音合成
- **Vision**: 视觉模型，支持图像分析和OCR

### 配置示例

```json
{
  "id": "qwen-local",
  "name": "Qwen本地部署",
  "supported_model_types": ["chat", "embedding"],
  "models": [
    {
      "id": "Qwen3-Embedding-0.6B",
      "model_type": "embedding",
      "embedding_dimension": 1024
    }
  ]
}
```

详见: [模型类型扩展方案](../tech_docs/model-type-extension.md)
```

### 8.2 配置模板

在 `coapis/data/packs/base/system/` 中添加嵌入模型配置模板。

---

## 九、风险评估

### 9.1 风险点

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 向后兼容性破坏 | 高 | 新字段默认值，全面测试 |
| JSON加载失败 | 中 | 异常处理，错误日志 |
| 模型类型冲突 | 低 | 明确类型定义，文档说明 |

### 9.2 回滚方案

如果出现问题，可以：
1. 移除新增字段（保持现有字段不变）
2. 回退到上一版本 provider.py
3. 删除新创建的 JSON 配置文件

---

## 十、总结

### 10.1 改动范围

- ✅ 修改文件：`coapis/providers/provider.py`（增加字段）
- ✅ 新增配置：`~/.coapis/.secrets/providers/custom/qwen-local.json`
- ✅ 文档更新：`README.md`

### 10.2 工作量

- 数据模型修改：30分钟
- 向后兼容测试：30分钟
- 配置文件创建：15分钟
- 验证测试：15分钟
- **总计：1.5小时**

### 10.3 后续任务

- [ ] 企业版集成：调用记录、计费统计
- [ ] 知识库功能：使用嵌入模型创建向量索引
- [ ] Weaviate 集成：配置向量推理服务

---

## 十一、参考资料

### 11.1 相关文件

- 数据模型：`coapis/providers/provider.py`
- 管理器：`coapis/providers/provider_manager.py`
- 配置存储：`~/.coapis/.secrets/providers/`

### 11.2 企业版关联

- 企业版扩展：`coapis-pro/docs/design/MODEL_MANAGEMENT_EXTENSION.md`
- 数据库表：`coapis-pro/database/schema/model_invocations.sql`

---

**文档版本**: v1.0  
**创建日期**: 2026-07-18  
**作者**: Paw AI  
**审核**: liuliangxu  
**状态**: ✅ 设计完成，待实施
