# 模型能力探测结果显示优化分析

## 🔍 现状分析

### 当前实现

#### 1. 探测按钮

**位置**：模型列表 → 每个模型右侧 → 测试多模态按钮（实验图标）

```tsx
<Button
  type="text"
  size="small"
  icon={<ExperimentOutlined />}
  onClick={() => handleProbeMultimodal(m.id)}
  loading={probingModelId === m.id}
/>
```

#### 2. 探测结果提示

```tsx
const handleProbeMultimodal = async (modelId: string) => {
  const result = await api.probeMultimodal(provider.id, modelId);
  
  if (result.supports_image) parts.push("图片");
  if (result.supports_video) parts.push("视频");
  
  if (parts.length > 0) {
    message.success(`支持: ${parts.join(", ")}`);
  } else {
    message.info("该模型不支持多模态输入");
  }
};
```

**提示消息**：
- ✅ 支持：显示 "支持: 图片, 视频"（临时消息，几秒后消失）
- ❌ 不支持：显示 "该模型不支持多模态输入"（临时消息）

#### 3. 能力标签显示

```tsx
function CapabilityTags({ model }) {
  if (model.supports_image && model.supports_video) {
    return <Tag>多模态</Tag>;
  }
  if (model.supports_image) {
    return <Tag>视觉</Tag>;
  }
  if (model.supports_video) {
    return <Tag>视频</Tag>;
  }
  if (model.supports_multimodal === false) {
    return <Tag>文本</Tag>;
  }
  return <Tag>未检测</Tag>;
}
```

#### 4. 数据结构（后端）

```python
class ModelInfo(BaseModel):
    id: str
    name: str
    supports_multimodal: bool | None  # 总开关
    supports_image: bool | None        # 图片支持
    supports_video: bool | None        # 视频支持
    probe_source: str | None           # 探测来源
    is_free: bool
    generate_kwargs: Dict[str, Any]
```

---

## ⚠️ 存在的问题

### 1. 探测结果不持久显示

```
用户点击探测
  ↓
显示临时消息（3秒后消失）
  ↓
用户不知道模型支持什么能力 ❌
```

### 2. 能力标签过于简单

```
当前显示：
- 多模态
- 视觉
- 视频
- 文本
- 未检测

缺少详细信息：
- 具体支持什么？✓
- 什么时候探测的？✗
- 探测结果准确吗？✗
```

### 3. 用户困惑

**场景1**：探测后显示"不支持多模态"
- 用户疑惑：是完全不支持？还是只支持图片？还是只支持视频？

**场景2**：探测后显示"支持: 图片"
- 用户疑惑：不支持视频吗？还是没测试视频？

**场景3**：临时消息消失后
- 用户疑惑：刚才探测结果是什么？需要重新探测？

---

## 💡 改进方案

### 方案一：在模型列表中显示详细能力

#### 修改模型列表表格

```tsx
// 当前表格列
<Table
  columns={[
    { title: '模型名称', dataIndex: 'name' },
    { title: '模型ID', dataIndex: 'id' },
    // 缺少能力列！
    { title: '操作', ... }
  ]}
/>

// 改进后：添加能力列
<Table
  columns={[
    { 
      title: '模型名称', 
      dataIndex: 'name',
      render: (name, model) => (
        <Space direction="vertical" size={0}>
          <Text strong>{name}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {model.id}
          </Text>
        </Space>
      )
    },
    { 
      title: '能力', 
      key: 'capabilities',
      render: (_, model) => (
        <Space direction="vertical" size={4}>
          {/* 能力标签 */}
          <Space size={4}>
            <CapabilityTag type="image" supported={model.supports_image} />
            <CapabilityTag type="video" supported={model.supports_video} />
          </Space>
          
          {/* 探测状态 */}
          {model.probe_source && (
            <Text type="secondary" style={{ fontSize: 11 }}>
              {model.probe_source === 'probed' ? '已探测' : '文档数据'}
            </Text>
          )}
        </Space>
      )
    },
    { title: '操作', ... }
  ]}
/>
```

#### 新增能力标签组件

```tsx
function CapabilityTag({ 
  type, 
  supported 
}: { 
  type: 'image' | 'video'; 
  supported: boolean | null 
}) {
  if (supported === null) {
    return (
      <Tag color="default" style={{ fontSize: 11 }}>
        <QuestionCircleOutlined /> {type === 'image' ? '图片未测' : '视频未测'}
      </Tag>
    );
  }
  
  if (supported) {
    return (
      <Tag color="success" style={{ fontSize: 11 }}>
        <CheckCircleOutlined /> {type === 'image' ? '图片' : '视频'}
      </Tag>
    );
  }
  
  return (
    <Tag color="error" style={{ fontSize: 11 }}>
      <CloseCircleOutlined /> {type === 'image' ? '无图片' : '无视频'}
    </Tag>
  );
}
```

---

### 方案二：添加探测结果详情面板

#### 在模型配置区域显示详细信息

```tsx
{isConfigOpen && (
  <div className="model-detail-panel">
    {/* 能力详情卡片 */}
    <Card size="small" title="模型能力">
      <Descriptions column={1} size="small">
        <Descriptions.Item label="图片识别">
          {model.supports_image === true && (
            <Space>
              <CheckCircleOutlined style={{ color: '#52c41a' }} />
              <Text>支持</Text>
            </Space>
          )}
          {model.supports_image === false && (
            <Space>
              <CloseCircleOutlined style={{ color: '#ff4d4f' }} />
              <Text>不支持</Text>
            </Space>
          )}
          {model.supports_image === null && (
            <Space>
              <QuestionCircleOutlined style={{ color: '#faad14' }} />
              <Text type="secondary">未探测</Text>
            </Space>
          )}
        </Descriptions.Item>
        
        <Descriptions.Item label="视频识别">
          {model.supports_video === true && (
            <Space>
              <CheckCircleOutlined style={{ color: '#52c41a' }} />
              <Text>支持</Text>
            </Space>
          )}
          {model.supports_video === false && (
            <Space>
              <CloseCircleOutlined style={{ color: '#ff4d4f' }} />
              <Text>不支持</Text>
            </Space>
          )}
          {model.supports_video === null && (
            <Space>
              <QuestionCircleOutlined style={{ color: '#faad14' }} />
              <Text type="secondary">未探测</Text>
            </Space>
          )}
        </Descriptions.Item>
        
        {model.probe_source && (
          <Descriptions.Item label="数据来源">
            <Tag color="blue">
              {model.probe_source === 'probed' ? '自动探测' : '文档数据'}
            </Tag>
          </Descriptions.Item>
        )}
        
        {model.probed_at && (
          <Descriptions.Item label="探测时间">
            <Text type="secondary">
              {new Date(model.probed_at).toLocaleString()}
            </Text>
          </Descriptions.Item>
        )}
      </Descriptions>
    </Card>
    
    {/* 原有的配置编辑器 */}
    <ModelConfigEditor ... />
  </div>
)}
```

---

### 方案三：探测结果持久化提示（推荐）

#### 探测后显示详细Modal

```tsx
const handleProbeMultimodal = async (modelId: string) => {
  setProbingModelId(modelId);
  try {
    const result = await api.probeMultimodal(provider.id, modelId);
    
    // 显示详细结果Modal，而不是临时消息
    Modal.success({
      title: '模型能力探测完成',
      width: 500,
      content: (
        <div>
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="模型">
              {getModelName(modelId)}
            </Descriptions.Item>
            
            <Descriptions.Item label="图片识别">
              {result.supports_image ? (
                <Space>
                  <CheckCircleOutlined style={{ color: '#52c41a' }} />
                  <Text strong>支持</Text>
                </Space>
              ) : (
                <Space>
                  <CloseCircleOutlined style={{ color: '#ff4d4f' }} />
                  <Text>不支持</Text>
                </Space>
              )}
            </Descriptions.Item>
            
            <Descriptions.Item label="视频识别">
              {result.supports_video ? (
                <Space>
                  <CheckCircleOutlined style={{ color: '#52c41a' }} />
                  <Text strong>支持</Text>
                </Space>
              ) : (
                <Space>
                  <CloseCircleOutlined style={{ color: '#ff4d4f' }} />
                  <Text>不支持</Text>
                </Space>
              )}
            </Descriptions.Item>
          </Descriptions>
          
          <Divider />
          
          <Alert
            type="info"
            showIcon
            message="探测结果已保存，将在聊天时自动应用"
          />
        </div>
      ),
      okText: '确定',
    });
    
    await onSaved();
  } catch (error) {
    Modal.error({
      title: '探测失败',
      content: (
        <div>
          <p>错误原因：{error.message}</p>
          <Divider />
          <Alert
            type="warning"
            showIcon
            message="建议手动设置模型能力，或检查API配置"
          />
        </div>
      ),
    });
  } finally {
    setProbingModelId(null);
  }
};
```

---

## 🎯 综合改进方案（推荐）

### 结合三种方案的优势

#### 1. 模型列表中添加"能力"列

```
┌──────────────────────────────────────────────────┐
│ 模型名称    │ 能力                    │ 操作     │
├──────────────────────────────────────────────────┤
│ GPT-4o      │ ✓ 图片 ✓ 视频          │ [探测]   │
│             │ 已探测                  │ [编辑]   │
├──────────────────────────────────────────────────┤
│ GPT-4       │ ✓ 图片 ✗ 视频          │ [探测]   │
│             │ 已探测                  │ [编辑]   │
├──────────────────────────────────────────────────┤
│ GPT-3.5     │ ? 图片 ? 视频          │ [探测]   │
│             │ 未检测                 │ [编辑]   │
└──────────────────────────────────────────────────┘
```

#### 2. 探测后显示详细Modal

```
┌─────────────────────────────────────┐
│ ✓ 模型能力探测完成                  │
├─────────────────────────────────────┤
│ 模型:     GPT-4o                    │
│ 图片识别: ✓ 支持                    │
│ 视频识别: ✓ 支持                    │
│                                     │
│ ℹ️ 探测结果已保存，将在聊天时自动应用│
│                                     │
│                    [确定]           │
└─────────────────────────────────────┘
```

#### 3. 配置面板显示详细信息

```
┌─────────────────────────────────────┐
│ 模型能力                             │
├─────────────────────────────────────┤
│ 图片识别: ✓ 支持                    │
│ 视频识别: ✗ 不支持                  │
│ 数据来源: 自动探测                   │
│ 探测时间: 2026-07-14 16:00:00      │
└─────────────────────────────────────┘
```

---

## 📋 具体实现步骤

### 第一步：添加"能力"列到模型列表

**修改文件**：`RemoteModelManageModal.tsx`

**新增内容**：
1. 添加能力列到Table columns
2. 创建CapabilityTag组件
3. 显示探测状态

### 第二步：改进探测结果显示

**修改内容**：
1. 探测后显示Modal而不是message
2. 显示详细的能力信息
3. 添加保存提示

### 第三步：完善配置面板

**修改内容**：
1. 在配置区域添加能力详情卡片
2. 显示探测时间和来源
3. 支持手动修改能力

---

## 🎨 UI设计建议

### 能力标签样式

```less
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
  
  &.not-probed {
    background: #fffbe6;
    border-color: #ffe58f;
    color: #faad14;
  }
}
```

### 探测结果Modal

```less
.probe-result-modal {
  .ant-modal-content {
    border-radius: 8px;
  }
  
  .result-item {
    padding: 12px 16px;
    border-bottom: 1px solid #f0f0f0;
    
    &:last-child {
      border-bottom: none;
    }
    
    .label {
      font-weight: 500;
      color: rgba(0, 0, 0, 0.85);
    }
    
    .value {
      margin-top: 4px;
      font-size: 16px;
    }
  }
}
```

---

## 💬 用户提示文案

### 探测成功

```
✓ 图片识别：支持
✓ 视频识别：支持

该模型支持完整的图片和视频识别能力，可以上传图片和视频进行分析。

探测结果已保存，将在聊天时自动应用。
```

### 部分支持

```
✓ 图片识别：支持
✗ 视频识别：不支持

该模型仅支持图片识别，不支持视频分析。

探测结果已保存，上传视频时将显示提示。
```

### 不支持

```
✗ 图片识别：不支持
✗ 视频识别：不支持

该模型是纯文本模型，不支持图片或视频分析。

如需多模态能力，请切换到支持多模态的模型（如 GPT-4o、Claude-3）。
```

---

## 📊 数据库/配置文件改进

### 当前数据结构

```python
class ModelInfo(BaseModel):
    supports_multimodal: bool | None
    supports_image: bool | None
    supports_video: bool | None
    probe_source: str | None
```

### 建议新增字段

```python
class ModelInfo(BaseModel):
    supports_multimodal: bool | None
    supports_image: bool | None
    supports_video: bool | None
    probe_source: str | None
    
    # 新增：探测时间戳
    probed_at: datetime | None = Field(
        default=None,
        description="Last probe timestamp"
    )
    
    # 新增：探测错误信息
    probe_error: str | None = Field(
        default=None,
        description="Error message if probe failed"
    )
    
    # 新增：能力详情
    capabilities: Dict[str, Any] = Field(
        default_factory=dict,
        description="Detailed capabilities (e.g., max_image_size, supported_formats)"
    )
```

---

## 🔄 后端改进

### 探测接口返回更多信息

```python
# 当前返回
{
  "supports_image": true,
  "supports_video": false,
  "supports_multimodal": true
}

# 改进后返回
{
  "supports_image": true,
  "supports_video": false,
  "supports_multimodal": true,
  "probed_at": "2026-07-14T16:00:00Z",
  "probe_source": "probed",
  "details": {
    "image_formats": ["jpg", "png", "gif"],
    "max_image_size": "20MB",
    "video_formats": [],
    "max_video_duration": null
  }
}
```

---

## ✅ 总结

### 核心改进点

1. **持久化显示** - 能力信息在模型列表中始终可见
2. **详细信息** - 显示图片和视频的具体支持情况
3. **探测详情** - 显示探测时间、来源、错误信息
4. **友好提示** - 探测后显示Modal，信息完整

### 优先级

1. **高优先级**：在模型列表添加"能力"列
2. **高优先级**：探测后显示详细Modal
3. **中优先级**：配置面板显示能力详情
4. **低优先级**：后端增加探测时间等字段

### 实施建议

建议先实施前端改进（显示能力列 + 探测Modal），让用户能清楚看到探测结果。后端字段可以根据需要逐步添加。

---

**下一步**：是否需要我开始实施前端改进？
