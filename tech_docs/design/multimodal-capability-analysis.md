# 图片上传与模型多模态能力检测分析

## 🔍 问题分析

### 用户问题
在输入框中上传图片时提示不支持，需要确定如何根据模型来判断是否支持图片识别（非图片生成）。

---

## 📊 当前实现逻辑

### 1. 前端检测流程

**文件位置**: `client/src/pages/Chat/index.tsx`

#### 多模态能力检测Hook

```typescript
function useMultimodalCapabilities(
  refreshKey: number,
  locationPathname: string,
  isChatActive: () => boolean,
  selectedAgent: string,
) {
  const [multimodalCaps, setMultimodalCaps] = useState<{
    supportsMultimodal: boolean;
    supportsImage: boolean;
    supportsVideo: boolean;
  }>({ 
    supportsMultimodal: false, 
    supportsImage: false, 
    supportsVideo: false 
  });

  const fetchMultimodalCaps = useCallback(async () => {
    try {
      // 1. 获取所有提供商
      const [providers, activeModels] = await Promise.all([
        providerApi.listProviders(),
        getActiveModelCached(selectedAgent),
      ]);
      
      // 2. 找到当前激活的提供商和模型
      const activeProviderId = activeModels?.active_llm?.provider_id;
      const activeModelId = activeModels?.active_llm?.model;
      
      if (!activeProviderId || !activeModelId) {
        setMultimodalCaps({
          supportsMultimodal: false,
          supportsImage: false,
          supportsVideo: false,
        });
        return;
      }
      
      // 3. 查找模型配置
      const provider = providers.find(p => p.id === activeProviderId);
      const model = provider?.models?.find(m => m.id === activeModelId);
      
      // 4. 设置能力标志
      setMultimodalCaps({
        supportsMultimodal: model?.supports_multimodal ?? false,
        supportsImage: model?.supports_image ?? false,
        supportsVideo: model?.supports_video ?? false,
      });
    } catch {
      // 失败时默认不支持
      setMultimodalCaps({
        supportsMultimodal: false,
        supportsImage: false,
        supportsVideo: false,
      });
    }
  }, [selectedAgent]);
}
```

#### 上传时的检测逻辑

```typescript
async (options) => {
  const { file, onSuccess, onError } = options;
  
  try {
    // 警告1：模型不支持多模态
    if (!multimodalCaps.supportsMultimodal) {
      message.warning(t("chat.attachments.multimodalWarning"));
      // 提示：当前模型未检测到多模态能力，图片或视频可能无法被正确处理
    } 
    // 警告2：模型只支持图片，但上传的是视频
    else if (
      multimodalCaps.supportsImage &&
      !multimodalCaps.supportsVideo &&
      !file.type.startsWith("image/")
    ) {
      message.warning(t("chat.attachments.imageOnlyWarning"));
      // 提示：当前模型仅检测到图片支持，视频等非图片文件可能无法被正确处理
    }
    
    // 继续上传...
    const res = await chatApi.uploadFile(file);
    onSuccess({ url: res.url });
  } catch (e) {
    onError?.(e);
  }
}
```

---

### 2. 数据来源

#### 模型信息类型定义

**文件位置**: `client/src/api/types/provider.ts`

```typescript
export interface ModelInfo {
  id: string;
  name: string;
  supports_multimodal: boolean | null;  // 是否支持多模态（图片+视频）
  supports_image: boolean | null;        // 是否支持图片
  supports_video: boolean | null;        // 是否支持视频
  probe_source?: string | null;          // 能力探测来源
  is_free?: boolean;
  generate_kwargs: Record<string, unknown>;
}

export interface ProviderInfo {
  id: string;
  name: string;
  models: ModelInfo[];  // 提供商下的所有模型
  // ... 其他字段
}
```

#### 后端API

**文件位置**: `server/coapis/app/routers/providers.py`

```python
@router.get(
    "/{provider_id}/models/{model_id:path}/probe-multimodal",
    response_model=ProbeMultimodalResponse,
    summary="Probe model multimodal capability",
)
async def probe_model_multimodal(
    request: Request,
    manager: ProviderManager = Depends(get_provider_manager),
    provider_id: str = Path(...),
    model_id: str = Path(...),
) -> ProbeMultimodalResponse:
    """探测图片和视频支持，通过发送轻量级测试请求"""
    result = await manager.probe_model_multimodal(provider_id, model_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return ProbeMultimodalResponse(**result)
```

---

## 🎯 能力判断逻辑

### 三级能力判断

```
supports_multimodal: true/false
    ↓
    ├─ true  → 支持图片和视频
    │
    └─ false → 检查详细能力
                ├─ supports_image: true  → 仅支持图片
                ├─ supports_video: true  → 仅支持视频（罕见）
                └─ 都为false            → 不支持多模态
```

### 前端行为

| 场景 | supports_multimodal | supports_image | supports_video | 行为 |
|------|---------------------|----------------|----------------|------|
| 全支持 | true | true | true | ✅ 允许上传图片和视频 |
| 仅图片 | false | true | false | ✅ 允许上传图片，警告视频 |
| 不支持 | false | false | false | ⚠️ 警告，但允许上传 |
| 未知 | null | null | null | ⚠️ 警告，但允许上传 |

---

## 🔧 问题定位

### 可能的问题原因

#### 1. 模型配置缺少能力字段

**检查方法**：
```bash
# 查看提供商配置
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:4308/api/providers" | jq '.[] | select(.id=="openai") | .models[0]'
```

**预期结果**：
```json
{
  "id": "gpt-4o",
  "name": "GPT-4o",
  "supports_multimodal": true,
  "supports_image": true,
  "supports_video": true
}
```

**问题情况**：
```json
{
  "id": "gpt-4o",
  "name": "GPT-4o",
  "supports_multimodal": null,  // ← 未设置
  "supports_image": null,
  "supports_video": null
}
```

---

#### 2. 前端获取失败

**检查方法**：
```javascript
// 浏览器控制台执行
fetch('/api/providers', {
  headers: { 'Authorization': 'Bearer ' + localStorage.getItem('coapis_auth_token') }
})
.then(r => r.json())
.then(data => {
  const openai = data.find(p => p.id === 'openai');
  const gpt4o = openai?.models?.find(m => m.id === 'gpt-4o');
  console.log('Model capabilities:', {
    supports_multimodal: gpt4o?.supports_multimodal,
    supports_image: gpt4o?.supports_image,
    supports_video: gpt4o?.supports_video,
  });
});
```

---

#### 3. 后端探测失败

**检查方法**：
```bash
# 手动触发能力探测
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  "http://localhost:4308/api/providers/openai/models/gpt-4o/probe-multimodal"
```

---

## 💡 解决方案

### 方案1：手动设置模型能力

**前端界面操作**：
1. 进入"设置" → "模型管理"
2. 找到对应的提供商（如 OpenAI）
3. 点击模型的"编辑"按钮
4. 勾选"支持多模态"、"支持图片"、"支持视频"
5. 保存

**后端API操作**：
```bash
# 更新模型能力
curl -X PATCH \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  "http://localhost:4308/api/providers/openai/models/gpt-4o" \
  -d '{
    "supports_multimodal": true,
    "supports_image": true,
    "supports_video": true
  }'
```

---

### 方案2：使用探测功能

**触发探测**：
```bash
# 探测模型能力
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  "http://localhost:4308/api/providers/openai/models/gpt-4o/probe-multimodal"
```

**探测原理**：
1. 发送一个包含图片URL的测试请求
2. 如果模型返回正常响应 → 标记 `supports_image: true`
3. 发送一个包含视频URL的测试请求
4. 如果模型返回正常响应 → 标记 `supports_video: true`
5. 综合判断 → 设置 `supports_multimodal`

---

### 方案3：预设模型信息

**更新模型配置文件**：

在某些部署中，模型信息可能存储在配置文件中：

```json
{
  "openai": [
    {
      "id": "gpt-4o",
      "name": "GPT-4o",
      "supports_multimodal": true,
      "supports_image": true,
      "supports_video": true
    },
    {
      "id": "gpt-4-turbo",
      "name": "GPT-4 Turbo",
      "supports_multimodal": true,
      "supports_image": true,
      "supports_video": false
    }
  ]
}
```

---

## 📋 常见模型能力参考

### OpenAI

| 模型 | supports_multimodal | supports_image | supports_video |
|------|---------------------|----------------|----------------|
| gpt-4o | ✅ true | ✅ true | ✅ true |
| gpt-4o-mini | ✅ true | ✅ true | ✅ true |
| gpt-4-turbo | ✅ true | ✅ true | ❌ false |
| gpt-4 | ✅ true | ✅ true | ❌ false |
| gpt-3.5-turbo | ❌ false | ❌ false | ❌ false |

### Anthropic

| 模型 | supports_multimodal | supports_image | supports_video |
|------|---------------------|----------------|----------------|
| claude-3-5-sonnet | ✅ true | ✅ true | ❌ false |
| claude-3-opus | ✅ true | ✅ true | ❌ false |
| claude-3-sonnet | ✅ true | ✅ true | ❌ false |
| claude-3-haiku | ✅ true | ✅ true | ❌ false |

### Google

| 模型 | supports_multimodal | supports_image | supports_video |
|------|---------------------|----------------|----------------|
| gemini-1.5-pro | ✅ true | ✅ true | ✅ true |
| gemini-1.5-flash | ✅ true | ✅ true | ✅ true |
| gemini-pro-vision | ✅ true | ✅ true | ❌ false |

### 本地模型

| 模型类型 | supports_multimodal | supports_image | supports_video |
|---------|---------------------|----------------|----------------|
| LLaVA | ✅ true | ✅ true | ❌ false |
| Qwen-VL | ✅ true | ✅ true | ❌ false |
| 纯文本模型 | ❌ false | ❌ false | ❌ false |

---

## 🚀 推荐配置策略

### 1. 自动探测（推荐）

**优点**：
- 自动识别模型能力
- 无需手动配置
- 支持动态更新

**触发时机**：
- 添加新模型时
- 切换模型时
- 用户手动触发时

**实现**：
```bash
# 在添加模型或切换模型时自动探测
curl -X POST "/api/providers/{provider_id}/models/{model_id}/probe-multimodal"
```

---

### 2. 预设配置

**优点**：
- 配置快速
- 无需API调用
- 适合离线环境

**实现**：
在系统初始化时加载预设的模型能力配置：

```json
{
  "openai": {
    "gpt-4o": { "supports_multimodal": true, "supports_image": true, "supports_video": true },
    "gpt-4-turbo": { "supports_multimodal": true, "supports_image": true, "supports_video": false }
  },
  "anthropic": {
    "claude-3-5-sonnet": { "supports_multimodal": true, "supports_image": true, "supports_video": false }
  }
}
```

---

### 3. 混合策略（最佳）

1. **预设基础配置** - 为常见模型提供默认值
2. **自动探测补充** - 对未知模型进行探测
3. **手动覆盖** - 允许用户手动调整

---

## 🔍 调试步骤

### 1. 检查当前模型能力

```javascript
// 浏览器控制台执行
fetch('/api/providers', {
  headers: { 'Authorization': 'Bearer ' + localStorage.getItem('coapis_auth_token') }
})
.then(r => r.json())
.then(providers => {
  providers.forEach(p => {
    console.log(`\n提供商: ${p.name} (${p.id})`);
    p.models?.forEach(m => {
      console.log(`  模型: ${m.name} (${m.id})`);
      console.log(`    多模态: ${m.supports_multimodal}`);
      console.log(`    图片: ${m.supports_image}`);
      console.log(`    视频: ${m.supports_video}`);
    });
  });
});
```

### 2. 检查当前激活模型

```javascript
// 浏览器控制台执行
fetch('/api/models/active', {
  headers: { 'Authorization': 'Bearer ' + localStorage.getItem('coapis_auth_token') }
})
.then(r => r.json())
.then(data => {
  console.log('当前激活模型:', data.active_llm);
});
```

### 3. 触发能力探测

```javascript
// 浏览器控制台执行
const providerId = 'openai';
const modelId = 'gpt-4o';

fetch(`/api/providers/${providerId}/models/${modelId}/probe-multimodal`, {
  method: 'POST',
  headers: { 'Authorization': 'Bearer ' + localStorage.getItem('coapis_auth_token') }
})
.then(r => r.json())
.then(result => {
  console.log('探测结果:', result);
});
```

---

## 📝 总结

### 关键要点

1. **三级能力标志**：
   - `supports_multimodal` - 总开关
   - `supports_image` - 图片支持
   - `supports_video` - 视频支持

2. **数据来源**：
   - 前端从 `/api/providers` 获取模型配置
   - 配置中的 `supports_*` 字段决定能力

3. **用户行为**：
   - 不支持时：显示警告，但不阻止上传
   - 仅支持图片时：上传视频显示警告
   - 全支持时：无警告

4. **解决方案**：
   - 方案1：手动设置模型能力
   - 方案2：使用探测功能
   - 方案3：预设模型信息
   - 推荐：混合策略

---

### 下一步建议

1. **检查模型配置** - 确认 `supports_*` 字段是否正确设置
2. **触发能力探测** - 对需要支持的模型执行探测
3. **优化用户体验** - 在模型选择界面显示能力标签
4. **文档更新** - 记录各模型的能力配置

---

**建议操作**：先检查当前模型的 `supports_multimodal` 配置，如果为 `null` 或 `false`，需要手动设置或触发探测。
