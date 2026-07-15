# 模型能力探测在聊天中的使用分析

## 🔍 现状分析

### 当前实现流程

```
用户选择模型
  ↓
useMultimodalCapabilities hook 获取能力
  ↓
setMultimodalCaps({
  supportsMultimodal: model.supports_multimodal,
  supportsImage: model.supports_image,
  supportsVideo: model.supports_video
})
  ↓
用户上传文件
  ↓
handleFileUpload 检查能力
  ↓
显示警告（但仍允许上传）
```

---

### 当前能力检测实现

#### 1. Hook: useMultimodalCapabilities

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
    const [providers, activeModels] = await Promise.all([
      providerApi.listProviders(),
      getActiveModelCached(selectedAgent),
    ]);
    
    const activeProviderId = activeModels?.active_llm?.provider_id;
    const activeModelId = activeModels?.active_llm?.model;
    
    const provider = providers.find(p => p.id === activeProviderId);
    const model = provider?.models?.find(m => m.id === activeModelId);
    
    setMultimodalCaps({
      supportsMultimodal: model?.supports_multimodal ?? false,
      supportsImage: model?.supports_image ?? false,
      supportsVideo: model?.supports_video ?? false,
    });
  }, [selectedAgent]);

  return multimodalCaps;
}
```

#### 2. 文件上传处理

```typescript
const handleFileUpload = async (options) => {
  const { file } = options;
  
  // 警告1：不支持多模态
  if (!multimodalCaps.supportsMultimodal) {
    message.warning("当前模型未检测到多模态能力，图片或视频可能无法被正确处理");
  } 
  // 警告2：只支持图片，但上传了其他文件
  else if (
    multimodalCaps.supportsImage &&
    !multimodalCaps.supportsVideo &&
    !file.type.startsWith("image/")
  ) {
    message.warning("当前模型仅检测到图片支持，视频等非图片文件可能无法被正确处理");
  }
  
  // 继续上传（不阻止）
  const res = await chatApi.uploadFile(file);
  onSuccess({ url: res.url });
};
```

---

## ⚠️ 存在的问题

### 1. 用户不知道当前模型的能力

```
聊天界面：
┌────────────────────────────────┐
│ [≡] 对话标题      [GPT-4o ▼] │  ← 模型名称，但没有能力提示
├────────────────────────────────┤
│                                │
│ 用户不知道：                   │
│ - 这个模型支持图片吗？✗        │
│ - 支持视频吗？✗               │
│ - 支持什么格式？✗             │
│                                │
└────────────────────────────────┘
```

### 2. 只在上传时警告，缺乏提前提示

```
用户上传视频
  ↓
显示警告："当前模型仅支持图片文件"
  ↓
用户困惑：
- 为什么不早说？✗
- 我能切换模型吗？✗
- 已上传的文件怎么办？✗
```

### 3. 警告信息不够明确

**当前警告**：
```
"当前模型未检测到多模态能力，图片或视频可能无法被正确处理"
```

**问题**：
- ❌ "未检测" = 没探测过？还是探测了但不支持？
- ❌ "可能无法" = 到底能不能？
- ❌ 没有建议操作

### 4. 切换模型时没有能力提示

```
用户从 GPT-4o（支持图片+视频）切换到 GPT-3.5（纯文本）
  ↓
已上传的图片/视频还在
  ↓
用户发送消息
  ↓
模型无法处理图片/视频 ❌
```

### 5. ModelSelector 不显示能力信息

```tsx
// 当前 ModelSelector 只显示模型名称
<Dropdown
  menu={{
    items: availableModels.map(m => ({
      key: `${m.provider_id}:${m.model_id}`,
      label: (
        <Space>
          <ProviderIcon providerId={m.provider_id} />
          <Text>{m.model_name}</Text>
          {m.is_free && <Tag>免费</Tag>}
        </Space>
      ),
    })),
  }}
/>
```

**缺少**：
- ❌ 能力标签（图片/视频）
- ❌ 推荐标记
- ❌ 能力对比

---

## 💡 改进方案

### 方案一：聊天界面显示当前模型能力

#### 1. 模型选择器显示能力标签

```
┌─────────────────────────────────┐
│ GPT-4o ▼                        │
├─────────────────────────────────┤
│ GPT-4o                          │
│   ✓ 图片 ✓ 视频    推荐         │
├─────────────────────────────────┤
│ GPT-4-Turbo                     │
│   ✓ 图片 ✗ 视频                 │
├─────────────────────────────────┤
│ GPT-3.5-Turbo                   │
│   ✗ 纯文本                      │
└─────────────────────────────────┘
```

**实现代码**：

```tsx
// ModelSelector/index.tsx
const items = availableModels.map(m => {
  const caps = m.capabilities || {};
  return {
    key: `${m.provider_id}:${m.model_id}`,
    label: (
      <Space direction="vertical" size={2} style={{ width: '100%' }}>
        <Space>
          <ProviderIcon providerId={m.provider_id} />
          <Text strong>{m.model_name}</Text>
          {m.is_free && <Tag color="green">免费</Tag>}
        </Space>
        <Space size={4}>
          <CapabilityTag type="image" supported={caps.supports_image} />
          <CapabilityTag type="video" supported={caps.supports_video} />
        </Space>
      </Space>
    ),
  };
});
```

#### 2. 聊天标题栏显示能力标签

```
┌────────────────────────────────────────────┐
│ [≡] 对话标题          [GPT-4o ▼] [📷][🎬] │
│                                            │
│ 📷 = 支持图片识别                          │
│ 🎬 = 支持视频识别                          │
└────────────────────────────────────────────┘
```

**实现代码**：

```tsx
// ChatSessionHeader/index.tsx
const ModelCapabilityBadge = ({ caps }) => (
  <Space size={4}>
    {caps.supportsImage ? (
      <Tooltip title="支持图片识别">
        <Tag color="success" style={{ fontSize: 11 }}>
          <EyeOutlined /> 图片
        </Tag>
      </Tooltip>
    ) : null}
    {caps.supportsVideo ? (
      <Tooltip title="支持视频识别">
        <Tag color="success" style={{ fontSize: 11 }}>
          <VideoCameraOutlined /> 视频
        </Tag>
      </Tooltip>
    ) : null}
    {!caps.supportsImage && !caps.supportsVideo && (
      <Tooltip title="纯文本模型，不支持图片或视频">
        <Tag color="default" style={{ fontSize: 11 }}>
          <FileTextOutlined /> 文本
        </Tag>
      </Tooltip>
    )}
  </Space>
);
```

---

### 方案二：文件上传区域显示能力提示

#### 1. 上传区域根据能力动态提示

```
支持图片+视频的模型：
┌─────────────────────────────────┐
│ 拖拽或点击上传文件              │
│ 支持: 图片、视频、文档          │
│ 最大: 20MB                      │
└─────────────────────────────────┘

仅支持图片的模型：
┌─────────────────────────────────┐
│ 拖拽或点击上传文件              │
│ ⚠️ 当前模型仅支持图片识别       │
│ 支持: 图片（JPG, PNG, GIF）     │
│ 最大: 20MB                      │
└─────────────────────────────────┘

纯文本模型：
┌─────────────────────────────────┐
│ 拖拽或点击上传文件              │
│ ⚠️ 当前模型不支持图片/视频识别  │
│ 建议: 切换到支持多模态的模型    │
│ 支持: 文档（PDF, TXT, DOCX）    │
└─────────────────────────────────┘
```

#### 2. 上传按钮根据能力显示图标

```tsx
// 根据能力显示不同的上传按钮
const UploadButton = ({ caps }) => {
  if (caps.supportsImage && caps.supportsVideo) {
    return (
      <Tooltip title="上传图片、视频或文档">
        <Button icon={<CloudUploadOutlined />}>
          上传文件
        </Button>
      </Tooltip>
    );
  }
  
  if (caps.supportsImage) {
    return (
      <Tooltip title="仅支持图片（当前模型不支持视频）">
        <Button icon={<PictureOutlined />}>
          上传图片
        </Button>
      </Tooltip>
    );
  }
  
  return (
    <Tooltip title="当前模型不支持图片/视频，建议切换模型">
      <Button icon={<FileOutlined />}>
        上传文档
      </Button>
    </Tooltip>
  );
};
```

---

### 方案三：切换模型时的能力变化提示

#### 1. 切换模型时检查已上传文件

```tsx
const handleModelChange = async (providerId: string, modelId: string) => {
  const newModel = availableModels.find(
    m => m.provider_id === providerId && m.model_id === modelId
  );
  
  const newCaps = {
    supportsImage: newModel?.supports_image ?? false,
    supportsVideo: newModel?.supports_video ?? false,
  };
  
  // 检查已上传的文件
  const uploadedFiles = getUploadedFiles();
  const hasImage = uploadedFiles.some(f => f.type.startsWith('image/'));
  const hasVideo = uploadedFiles.some(f => f.type.startsWith('video/'));
  
  // 显示警告
  if (hasImage && !newCaps.supportsImage) {
    Modal.confirm({
      title: '模型能力变化',
      content: (
        <div>
          <p>当前对话已上传图片，但新模型不支持图片识别。</p>
          <p>建议：</p>
          <ul>
            <li>保留原模型（支持图片）</li>
            <li>移除已上传的图片后再切换</li>
          </ul>
        </div>
      ),
      okText: '仍然切换',
      cancelText: '取消',
    });
  }
  
  if (hasVideo && !newCaps.supportsVideo) {
    Modal.confirm({
      title: '模型能力变化',
      content: '当前对话已上传视频，但新模型不支持视频识别。',
      okText: '仍然切换',
      cancelText: '取消',
    });
  }
  
  // 确认切换
  await userModelPrefsApi.setActiveModel({
    provider_id: providerId,
    model_id: modelId,
    agent_id: selectedAgent,
  });
};
```

#### 2. 模型切换后显示能力变化通知

```
┌─────────────────────────────────────┐
│ ℹ️ 模型能力变化                     │
├─────────────────────────────────────┤
│ 从 GPT-4o 切换到 GPT-3.5-Turbo      │
│                                     │
│ 能力变化：                          │
│ ✗ 图片识别：支持 → 不支持           │
│ ✗ 视频识别：支持 → 不支持           │
│                                     │
│ 已上传的图片/视频可能无法处理       │
└─────────────────────────────────────┘
```

---

### 方案四：改进警告信息

#### 1. 更明确的警告内容

```typescript
// 改进前
message.warning("当前模型未检测到多模态能力，图片或视频可能无法被正确处理");

// 改进后
if (!multimodalCaps.supportsMultimodal) {
  Modal.warning({
    title: '模型不支持多模态',
    content: (
      <div>
        <p>当前模型 <strong>{currentModel.name}</strong> 不支持图片或视频识别。</p>
        <p>您可以选择：</p>
        <ul>
          <li>继续上传（模型将无法处理文件内容）</li>
          <li>
            <a onClick={() => setShowModelSelector(true)}>
              切换到支持多模态的模型
            </a>
            （如 GPT-4o、Claude-3）
          </li>
        </ul>
      </div>
    ),
    okText: '仍然上传',
    cancelText: '取消',
  });
}
```

#### 2. 根据文件类型提供精确警告

```typescript
const file = options.file;

if (file.type.startsWith('image/')) {
  if (!multimodalCaps.supportsImage) {
    return Modal.confirm({
      title: '模型不支持图片识别',
      content: '当前模型不支持图片识别，上传的图片将无法被分析。',
      okText: '仍然上传',
      cancelText: '取消',
    });
  }
}

if (file.type.startsWith('video/')) {
  if (!multimodalCaps.supportsVideo) {
    return Modal.confirm({
      title: '模型不支持视频识别',
      content: (
        <div>
          <p>当前模型不支持视频识别。</p>
          {multimodalCaps.supportsImage && (
            <p>提示：当前模型支持图片识别，您可以提取视频帧作为图片上传。</p>
          )}
        </div>
      ),
      okText: '仍然上传',
      cancelText: '取消',
    });
  }
}
```

---

### 方案五：智能推荐模型

#### 1. 根据上传内容自动推荐模型

```tsx
// 检测到用户上传图片后
if (hasImageUpload && !currentModel.supportsImage) {
  notification.info({
    message: '推荐切换模型',
    description: (
      <div>
        <p>您上传了图片，但当前模型不支持图片识别。</p>
        <p>推荐模型：</p>
        <Space>
          <Button 
            size="small" 
            onClick={() => switchModel('openai', 'gpt-4o')}
          >
            GPT-4o（推荐）
          </Button>
          <Button 
            size="small" 
            onClick={() => switchModel('anthropic', 'claude-3-opus')}
          >
            Claude-3
          </Button>
        </Space>
      </div>
    ),
    duration: 10,
  });
}
```

#### 2. 模型选择器标记推荐模型

```tsx
const getRecommendedModels = (fileType: string) => {
  if (fileType.startsWith('image/')) {
    return availableModels.filter(m => m.supports_image);
  }
  if (fileType.startsWith('video/')) {
    return availableModels.filter(m => m.supports_video);
  }
  return [];
};

// 在模型列表中标记推荐
<Dropdown
  menu={{
    items: availableModels.map(m => ({
      ...m,
      label: (
        <Space>
          {m.model_name}
          {recommendedModels.includes(m.id) && (
            <Tag color="blue">推荐</Tag>
          )}
        </Space>
      ),
    })),
  }}
/>
```

---

## 🎯 综合改进方案

### 优先级排序

| 功能 | 优先级 | 工作量 | 效果 |
|------|--------|--------|------|
| 模型选择器显示能力标签 | ⭐⭐⭐ 高 | 0.5天 | 一目了然 |
| 聊天标题栏显示能力 | ⭐⭐⭐ 高 | 0.5天 | 实时可见 |
| 改进警告信息 | ⭐⭐⭐ 高 | 0.5天 | 明确指导 |
| 上传区域能力提示 | ⭐⭐ 中 | 1天 | 提前告知 |
| 切换模型检查 | ⭐⭐ 中 | 1天 | 防止错误 |
| 智能推荐模型 | ⭐ 低 | 1天 | 自动优化 |

---

### 实施步骤

#### 第一步：显示能力信息（高优先级）

1. **ModelSelector 添加能力标签**
   - 显示每个模型的图片/视频支持情况
   - 标记推荐模型

2. **聊天标题栏添加能力徽章**
   - 显示当前模型的能力状态
   - 点击可切换模型

3. **改进警告信息**
   - 使用 Modal 而非 message
   - 提供明确的建议和操作

#### 第二步：增强用户体验（中优先级）

1. **上传区域能力提示**
   - 根据能力动态显示支持类型
   - 提前告知限制

2. **切换模型检查**
   - 检查已上传文件
   - 显示能力变化
   - 提供建议

#### 第三步：智能优化（低优先级）

1. **智能推荐模型**
   - 根据文件类型推荐
   - 一键切换

---

## 📊 数据流设计

### 当前数据流

```
模型配置
  ↓
ModelInfo {
  supports_multimodal: bool
  supports_image: bool
  supports_video: bool
}
  ↓
useMultimodalCapabilities hook
  ↓
multimodalCaps state
  ↓
handleFileUpload 检查
```

### 改进后数据流

```
模型配置
  ↓
ModelInfo {
  supports_multimodal: bool
  supports_image: bool
  supports_video: bool
  probe_source: string
  probed_at: datetime
}
  ↓
┌─────────────────────────────────────┐
│ 多个消费者                          │
├─────────────────────────────────────┤
│ 1. ModelSelector 显示能力标签       │
│ 2. ChatHeader 显示当前能力          │
│ 3. UploadArea 显示支持类型          │
│ 4. handleFileUpload 检查能力        │
│ 5. handleModelChange 检查冲突       │
└─────────────────────────────────────┘
```

---

## 🎨 UI/UX 设计建议

### 1. 能力标签样式

```less
// 支持状态
.capability-tag {
  &.supported {
    background: #f6ffed;
    border-color: #b7eb8f;
    color: #52c41a;
  }
  
  &.not-supported {
    background: #fff2f0;
    border-color: #ffccc7;
    color: #ff4d4f;
  }
  
  &.unknown {
    background: #fffbe6;
    border-color: #ffe58f;
    color: #faad14;
  }
}
```

### 2. 上传区域提示样式

```less
.upload-hint {
  padding: 12px;
  border-radius: 8px;
  margin-bottom: 8px;
  
  &.full-support {
    background: #f6ffed;
    border: 1px solid #b7eb8f;
  }
  
  &.partial-support {
    background: #fffbe6;
    border: 1px solid #ffe58f;
  }
  
  &.no-support {
    background: #fff2f0;
    border: 1px solid #ffccc7;
  }
}
```

### 3. 模型切换提示样式

```less
.capability-change-alert {
  .ant-alert-message {
    font-weight: 500;
  }
  
  .change-item {
    display: flex;
    align-items: center;
    padding: 4px 0;
    
    .icon {
      margin-right: 8px;
    }
    
    .text {
      flex: 1;
    }
  }
}
```

---

## 📝 用户提示文案

### 模型选择器

```
GPT-4o
  ✓ 图片 ✓ 视频
  推荐

GPT-4-Turbo
  ✓ 图片 ✗ 视频

GPT-3.5-Turbo
  ✗ 纯文本
```

### 上传提示

```
支持图片+视频：
"支持上传图片、视频和文档（最大20MB）"

仅支持图片：
"⚠️ 当前模型仅支持图片识别，视频将无法处理"

纯文本：
"⚠️ 当前模型不支持图片/视频识别，建议切换到多模态模型"
```

### 切换模型警告

```
"模型能力变化"

从 GPT-4o 切换到 GPT-3.5-Turbo

能力变化：
• 图片识别：支持 → 不支持
• 视频识别：支持 → 不支持

已上传的图片/视频将无法被处理。

[取消] [仍然切换]
```

---

## ✅ 总结

### 核心改进点

1. **提前告知** - 在模型选择器和标题栏显示能力，而不是上传时才警告
2. **明确信息** - 使用 Modal 显示详细信息，提供明确的建议和操作
3. **智能检查** - 切换模型时检查已上传文件，防止能力冲突
4. **友好引导** - 推荐合适的模型，一键切换

### 实施建议

1. **第一步**（高优先级）：
   - ModelSelector 添加能力标签
   - ChatHeader 显示当前能力
   - 改进警告信息（使用 Modal）

2. **第二步**（中优先级）：
   - UploadArea 显示能力提示
   - 切换模型时检查冲突

3. **第三步**（低优先级）：
   - 智能推荐模型
   - 一键切换

---

**下一步**：是否需要我开始实施这些改进？建议从优先级最高的"显示能力信息"开始。
