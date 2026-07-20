# 模型能力自动探测方案

> **目标**: 自动验证模型配置的正确性和实际能力
> 
> **创建时间**: 2026-07-18
> 
**优先级**: P1（提高可靠性）

---

## 一、问题分析

### 1.1 当前问题

- ❌ 用户配置的模型能力可能与实际不符
- ❌ 嵌入维度配置错误会导致知识库功能失败
- ❌ API Key 错误只能在调用时才发现
- ❌ 无法验证模型是否真的支持图片/视频

### 1.2 影响场景

**场景 1：嵌入维度配置错误**
```json
{
  "id": "qwen-embedding",
  "model_type": "embedding",
  "embedding_dimension": 1024  // 配置错误
}
```

实际调用返回 1536 维向量 → 知识库索引创建失败

**场景 2：模型不支持图片**
```json
{
  "id": "deepseek-chat",
  "supports_image": true  // 配置错误
}
```

用户上传图片 → API 返回错误 → 用户体验糟糕

---

## 二、探测方案

### 2.1 对话模型探测

```python
async def probe_chat_model(provider: ProviderInfo, model: ModelInfo) -> dict:
    """探测对话模型能力"""
    
    results = {
        "connection": False,
        "chat": False,
        "image": False,
        "video": False,
        "errors": []
    }
    
    try:
        # 1. 测试基本对话
        response = await call_chat_api(
            provider, model, 
            messages=[{"role": "user", "content": "test"}]
        )
        results["connection"] = True
        results["chat"] = True
        
    except Exception as e:
        results["errors"].append(f"Chat test failed: {e}")
        return results
    
    # 2. 测试图片能力（如果配置了）
    if model.supports_image:
        try:
            # 发送一个小图片
            test_image = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
            response = await call_chat_api(
                provider, model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "What is this?"},
                        {"type": "image_url", "image_url": {"url": test_image}}
                    ]
                }]
            )
            results["image"] = True
        except Exception as e:
            results["errors"].append(f"Image test failed: {e}")
            results["image"] = False
    
    return results
```

### 2.2 嵌入模型探测

```python
async def probe_embedding_model(provider: ProviderInfo, model: ModelInfo) -> dict:
    """探测嵌入模型能力"""
    
    results = {
        "connection": False,
        "dimension": None,
        "max_length": None,
        "errors": []
    }
    
    try:
        # 测试基本嵌入
        test_text = "This is a test sentence for embedding."
        embedding = await call_embedding_api(provider, model, [test_text])
        
        results["connection"] = True
        results["dimension"] = len(embedding[0])
        
        # 验证维度配置
        if model.embedding_dimension and model.embedding_dimension != results["dimension"]:
            results["errors"].append(
                f"Dimension mismatch: config={model.embedding_dimension}, "
                f"actual={results['dimension']}"
            )
        
        # 测试最大长度（逐步增加文本长度）
        if not model.max_sequence_length:
            results["max_length"] = await estimate_max_length(provider, model)
        
    except Exception as e:
        results["errors"].append(f"Embedding test failed: {e}")
    
    return results


async def estimate_max_length(provider: ProviderInfo, model: ModelInfo) -> int:
    """估算最大序列长度"""
    
    # 使用二分查找
    low, high = 1000, 100000
    
    while low < high:
        mid = (low + high) // 2
        test_text = "test " * mid
        
        try:
            await call_embedding_api(provider, model, [test_text])
            low = mid + 1
        except:
            high = mid
    
    return low
```

### 2.3 音频模型探测

```python
async def probe_audio_model(provider: ProviderInfo, model: ModelInfo) -> dict:
    """探测音频模型能力"""
    
    results = {
        "connection": False,
        "transcription": False,
        "tts": False,
        "sample_rate": None,
        "errors": []
    }
    
    # 测试语音识别
    if model.id.startswith("whisper"):
        try:
            # 使用一个短的测试音频
            test_audio = create_silent_audio(duration=1, sample_rate=16000)
            transcript = await call_transcription_api(provider, model, test_audio)
            
            results["connection"] = True
            results["transcription"] = True
            results["sample_rate"] = 16000
            
        except Exception as e:
            results["errors"].append(f"Transcription test failed: {e}")
    
    # 测试语音合成
    elif model.id.startswith("tts"):
        try:
            audio = await call_tts_api(provider, model, "test")
            
            results["connection"] = True
            results["tts"] = True
            results["sample_rate"] = get_audio_sample_rate(audio)
            
        except Exception as e:
            results["errors"].append(f"TTS test failed: {e}")
    
    return results
```

---

## 三、自动探测触发时机

### 3.1 添加模型时

```python
async def add_model_with_probe(provider_id: str, model_config: dict):
    """添加模型并自动探测能力"""
    
    # 1. 创建模型配置
    model = ModelInfo(**model_config)
    
    # 2. 自动探测
    provider = get_provider(provider_id)
    
    if model.model_type == "chat":
        probe_results = await probe_chat_model(provider, model)
    elif model.model_type == "embedding":
        probe_results = await probe_embedding_model(provider, model)
    elif model.model_type == "audio":
        probe_results = await probe_audio_model(provider, model)
    
    # 3. 更新模型配置
    if probe_results["connection"]:
        if model.model_type == "embedding":
            # 自动修正维度配置
            model.embedding_dimension = probe_results["dimension"]
        
        # 标记为已探测
        model.probe_source = "probed"
        model.probe_time = datetime.now().isoformat()
    
    # 4. 保存配置
    save_model_config(provider_id, model)
    
    return {
        "model": model,
        "probe_results": probe_results
    }
```

### 3.2 定期验证

```python
# 定时任务：每周验证一次所有模型
@scheduled_task("weekly")
async def verify_all_models():
    """定期验证所有模型"""
    
    pm = ProviderManager.get_instance()
    
    for provider_id in pm.list_providers():
        provider = pm.get_provider(provider_id)
        
        for model in provider.models:
            try:
                if model.model_type == "embedding":
                    results = await probe_embedding_model(provider, model)
                    
                    # 如果维度变化，更新配置
                    if results["dimension"] != model.embedding_dimension:
                        logger.warning(
                            f"Model {model.id} dimension changed: "
                            f"{model.embedding_dimension} -> {results['dimension']}"
                        )
                        model.embedding_dimension = results["dimension"]
                        save_model_config(provider_id, model)
                        
            except Exception as e:
                logger.error(f"Failed to verify model {model.id}: {e}")
```

---

## 四、UI 展示

### 4.1 探测状态标签

```
+----------------------------------------------------------+
| 模型列表                                                  |
+----------------------------------------------------------+
| gpt-4o              | GPT-4o          | 💬 对话 | ✅ 已验证 |
| text-embedding-3    | Embedding 3     | 🔢 嵌入 | ⚠️ 配置差异 |
| whisper-1           | Whisper         | 🎵 音频 | ✅ 已验证 |
| unknown-model       | Unknown         | 💬 对话 | ❌ 连接失败 |
+----------------------------------------------------------+
```

### 4.2 探测详情

```
+----------------------------------------------------------+
| 模型探测详情 - text-embedding-3-large                     |
+----------------------------------------------------------+
| 连接状态: ✅ 成功                                          |
| 探测时间: 2026-07-18 14:30:25                             |
|                                                            |
| ⚠️ 配置差异：                                              |
| 配置维度: 1024                                             |
| 实际维度: 3072                                             |
|                                                            |
| 建议：更新配置以匹配实际维度                               |
|                                                            |
| [更新配置] [重新探测] [忽略]                               |
+----------------------------------------------------------+
```

---

## 五、实施建议

### 优先级

| 功能 | 优先级 | 工作量 | 价值 |
|------|--------|--------|------|
| 嵌入模型维度验证 | P0 | 2小时 | 高 |
| 对话模型基本测试 | P0 | 1小时 | 高 |
| 图片能力测试 | P1 | 2小时 | 中 |
| 最大长度估算 | P2 | 3小时 | 低 |

### 实施步骤

1. **Phase 1（核心验证）**
   - 实现嵌入模型维度验证
   - 实现对话模型连接测试
   - 添加探测 API

2. **Phase 2（能力探测）**
   - 实现图片/视频能力测试
   - 实现音频模型测试
   - 添加探测状态显示

3. **Phase 3（智能优化）**
   - 实现自动修正配置
   - 实现定期验证
   - 添加配置迁移建议

---

**文档版本**: v1.0  
**创建日期**: 2026-07-18  
**状态**: ✅ 设计完成，待实施
