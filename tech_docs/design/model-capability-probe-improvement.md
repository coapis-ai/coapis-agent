# 模型能力探测功能改进方案

## 📊 现状分析

### 当前实现

#### 1. 前端界面

**文件位置**: `client/src/pages/Settings/Models/components/modals/RemoteModelManageModal.tsx`

**能力标签显示**：
```tsx
function CapabilityTags({ model, isDark }: { model: ModelInfo }) {
  if (model.supports_image && model.supports_video) {
    return <Tag color="blue">多模态</Tag>;
  }
  if (model.supports_image) {
    return <Tag color="cyan">视觉</Tag>;
  }
  if (model.supports_video) {
    return <Tag color="purple">视频</Tag>;
  }
  if (model.supports_multimodal === false) {
    return <Tag color="default">文本</Tag>;
  }
  return <Tag color="warning">未检测</Tag>;
}
```

**探测按钮**：
```tsx
<Button
  type="text"
  size="small"
  icon={<ExperimentOutlined />}
  onClick={() => handleProbeMultimodal(model.id)}
  loading={probingModelId === model.id}
>
  探测
</Button>
```

**探测处理函数**：
```typescript
const handleProbeMultimodal = async (modelId: string) => {
  setProbingModelId(modelId);
  try {
    const result = await api.probeMultimodal(provider.id, modelId);
    const parts: string[] = [];
    if (result.supports_image) parts.push("图片");
    if (result.supports_video) parts.push("视频");
    
    if (parts.length > 0) {
      message.success(`模型支持: ${parts.join(", ")}`);
    } else {
      message.info("模型不支持多模态");
    }
    
    await onSaved(); // 刷新模型列表
  } catch (error) {
    message.error("探测失败");
  } finally {
    setProbingModelId(null);
  }
};
```

---

#### 2. 后端实现

**文件位置**: `server/coapis/providers/provider_manager.py`

**探测方法**：
```python
async def probe_model_multimodal(
    self,
    provider_id: str,
    model_id: str,
    image_only: bool = False,
) -> dict:
    """探测模型的多模态能力并持久化结果
    
    流程：
    1. 发送测试图片URL到模型
    2. 检查模型是否正确处理图片
    3. 如果image_only=False，发送测试视频URL
    4. 检查模型是否正确处理视频
    5. 更新模型配置中的能力标志
    6. 保存配置
    """
```

---

## 🎯 问题分析

### 当前方案的不足

#### 1. 用户操作繁琐

```
用户添加模型
  ↓
手动点击"探测"按钮
  ↓
等待探测完成
  ↓
查看结果
  ↓
如果结果不对，需要手动修改
```

#### 2. 探测时机不明确

- ❌ 添加模型时不会自动探测
- ❌ 切换模型时不会自动探测
- ❌ 用户不知道何时需要探测

#### 3. 结果展示不直观

- ⚠️ 只显示"支持图片/视频"
- ⚠️ 没有详细的探测过程
- ⚠️ 失败原因不明确

#### 4. 缺少手动调整选项

- ❌ 探测结果无法手动修改
- ❌ 对于已知能力的模型，仍需探测
- ❌ 无法批量设置多个模型

---

## 💡 改进方案

### 方案一：添加模型时自动探测（推荐）

**优点**：
- 用户无需手动操作
- 结果准确可靠
- 体验流畅

**实现**：

```typescript
// 添加模型后自动探测
const handleAddModel = async (id: string, name: string) => {
  try {
    // 1. 添加模型
    await api.addModel(provider.id, { id, name });
    
    // 2. 自动探测能力
    message.loading({ content: '正在探测模型能力...', key: 'probe' });
    const result = await api.probeMultimodal(provider.id, id);
    
    // 3. 显示结果
    const capabilities = [];
    if (result.supports_image) capabilities.push('图片识别');
    if (result.supports_video) capabilities.push('视频识别');
    
    if (capabilities.length > 0) {
      message.success({ 
        content: `模型已添加，支持: ${capabilities.join('、')}`, 
        key: 'probe' 
      });
    } else {
      message.info({ 
        content: '模型已添加（纯文本模型）', 
        key: 'probe' 
      });
    }
    
    await onSaved();
  } catch (error) {
    message.error('添加模型失败');
  }
};
```

**界面改进**：

```tsx
// 添加模型对话框
<Modal title="添加模型">
  <Form>
    <Form.Item label="模型ID" required>
      <Input placeholder="例如: gpt-4o" />
    </Form.Item>
    
    <Form.Item label="模型名称" required>
      <Input placeholder="例如: GPT-4o" />
    </Form.Item>
    
    {/* 新增：能力预设选项 */}
    <Form.Item 
      label="能力预设"
      extra="可选，留空则自动探测"
    >
      <Select placeholder="选择预设或自动探测" allowClear>
        <Option value="multimodal">多模态（图片+视频）</Option>
        <Option value="vision">仅图片识别</Option>
        <Option value="video">仅视频识别</Option>
        <Option value="text">纯文本</Option>
        <Option value="auto">自动探测（推荐）</Option>
      </Select>
    </Form.Item>
    
    <Alert
      type="info"
      message="添加后将自动探测模型能力"
      showIcon
    />
  </Form>
</Modal>
```

---

### 方案二：模型列表中批量操作

**优点**：
- 支持批量探测
- 界面清晰
- 操作高效

**实现**：

```tsx
// 模型列表界面
<div className="model-list">
  {/* 批量操作按钮 */}
  <div className="batch-actions">
    <Button 
      icon={<ExperimentOutlined />}
      onClick={handleBatchProbe}
      loading={batchProbing}
    >
      批量探测选中模型
    </Button>
    
    <Button 
      icon={<SettingOutlined />}
      onClick={() => setBatchConfigOpen(true)}
    >
      批量设置能力
    </Button>
  </div>
  
  {/* 模型列表 */}
  <Table
    rowSelection={{
      selectedRowKeys,
      onChange: setSelectedRowKeys,
    }}
    columns={[
      {
        title: '模型名称',
        dataIndex: 'name',
        render: (name, model) => (
          <Space>
            {name}
            <CapabilityTags model={model} />
          </Space>
        ),
      },
      {
        title: '能力状态',
        dataIndex: 'status',
        render: (_, model) => {
          if (model.supports_multimodal === null) {
            return <Tag color="warning">未检测</Tag>;
          }
          return <Tag color="success">已检测</Tag>;
        },
      },
      {
        title: '操作',
        render: (_, model) => (
          <Space>
            <Button 
              size="small"
              icon={<ExperimentOutlined />}
              onClick={() => handleProbe(model.id)}
            >
              探测
            </Button>
            <Button 
              size="small"
              icon={<EditOutlined />}
              onClick={() => handleEdit(model.id)}
            >
              编辑
            </Button>
          </Space>
        ),
      },
    ]}
  />
</div>

{/* 批量设置能力对话框 */}
<Modal
  title="批量设置模型能力"
  open={batchConfigOpen}
  onCancel={() => setBatchConfigOpen(false)}
>
  <Form>
    <Alert
      type="warning"
      message={`将设置 ${selectedRowKeys.length} 个模型的能力`}
    />
    
    <Form.Item label="图片识别">
      <Radio.Group>
        <Radio value={true}>支持</Radio>
        <Radio value={false}>不支持</Radio>
        <Radio value={null}>保持原值</Radio>
      </Radio.Group>
    </Form.Item>
    
    <Form.Item label="视频识别">
      <Radio.Group>
        <Radio value={true}>支持</Radio>
        <Radio value={false}>不支持</Radio>
        <Radio value={null}>保持原值</Radio>
      </Radio.Group>
    </Form.Item>
  </Form>
</Modal>
```

---

### 方案三：能力编辑界面

**优点**：
- 可视化编辑
- 支持手动调整
- 信息完整

**实现**：

```tsx
// 单个模型的能力编辑界面
<Modal
  title="模型能力配置"
  open={configOpen}
  onCancel={() => setConfigOpen(false)}
  footer={[
    <Button key="probe" icon={<ExperimentOutlined />}>
      自动探测
    </Button>,
    <Button key="cancel">取消</Button>,
    <Button key="save" type="primary">保存</Button>,
  ]}
>
  <Form layout="vertical">
    {/* 模型信息 */}
    <Descriptions column={1} bordered size="small">
      <Descriptions.Item label="模型ID">{model.id}</Descriptions.Item>
      <Descriptions.Item label="模型名称">{model.name}</Descriptions.Item>
    </Descriptions>
    
    <Divider />
    
    {/* 能力配置 */}
    <Form.Item 
      label={
        <Space>
          图片识别能力
          <Tooltip title="模型是否能够理解和分析图片内容">
            <QuestionCircleOutlined />
          </Tooltip>
        </Space>
      }
    >
      <Radio.Group value={supportsImage}>
        <Radio value={true}>
          <Space>
            <CheckCircleOutlined style={{ color: '#52c41a' }} />
            支持
          </Space>
        </Radio>
        <Radio value={false}>
          <Space>
            <CloseCircleOutlined style={{ color: '#ff4d4f' }} />
            不支持
          </Space>
        </Radio>
        <Radio value={null}>
          <Space>
            <QuestionCircleOutlined style={{ color: '#faad14' }} />
            未知
          </Space>
        </Radio>
      </Radio.Group>
    </Form.Item>
    
    <Form.Item 
      label={
        <Space>
          视频识别能力
          <Tooltip title="模型是否能够理解和分析视频内容">
            <QuestionCircleOutlined />
          </Tooltip>
        </Space>
      }
    >
      <Radio.Group value={supportsVideo}>
        <Radio value={true}>
          <Space>
            <CheckCircleOutlined style={{ color: '#52c41a' }} />
            支持
          </Space>
        </Radio>
        <Radio value={false}>
          <Space>
            <CloseCircleOutlined style={{ color: '#ff4d4f' }} />
            不支持
          </Space>
        </Radio>
        <Radio value={null}>
          <Space>
            <QuestionCircleOutlined style={{ color: '#faad14' }} />
            未知
          </Space>
        </Radio>
      </Radio.Group>
    </Form.Item>
    
    {/* 探测历史 */}
    {model.probe_source && (
      <Alert
        type="info"
        message={
          <Space direction="vertical" size={0}>
            <Text>最后探测时间: {model.probed_at}</Text>
            <Text>探测来源: {model.probe_source}</Text>
          </Space>
        }
        showIcon
      />
    )}
    
    {/* 快速预设 */}
    <Divider>快速预设</Divider>
    <Space wrap>
      <Button onClick={() => setPreset('gpt4o')}>
        GPT-4o (多模态)
      </Button>
      <Button onClick={() => setPreset('gpt4')}>
        GPT-4 (仅图片)
      </Button>
      <Button onClick={() => setPreset('claude3')}>
        Claude-3 (仅图片)
      </Button>
      <Button onClick={() => setPreset('gemini')}>
        Gemini (多模态)
      </Button>
      <Button onClick={() => setPreset('llava')}>
        LLaVA (仅图片)
      </Button>
      <Button onClick={() => setPreset('text')}>
        纯文本模型
      </Button>
    </Space>
  </Form>
</Modal>
```

---

## 🚀 推荐实现方案

### 综合方案（最佳体验）

结合三种方案的优点：

#### 1. 添加模型时

```
流程：
1. 用户输入模型ID和名称
2. 【可选】选择能力预设（留空=自动探测）
3. 点击"添加"
4. 系统自动探测（如果未选预设）
5. 显示探测结果并允许修改
6. 保存模型
```

#### 2. 模型列表界面

```
功能：
1. 显示所有模型及其能力状态
2. 单个模型：探测、编辑、删除
3. 批量操作：批量探测、批量设置
4. 筛选：按能力状态筛选
```

#### 3. 模型编辑界面

```
功能：
1. 手动设置能力
2. 自动探测按钮
3. 快速预设选项
4. 探测历史记录
```

---

## 📋 具体实现步骤

### 第一步：改进添加模型流程

**修改文件**: `RemoteModelManageModal.tsx`

**新增功能**：
1. 添加能力预设选择器
2. 自动探测逻辑
3. 结果显示和确认

### 第二步：优化模型列表界面

**新增功能**：
1. 批量选择和操作
2. 能力状态筛选
3. 快速探测按钮

### 第三步：完善能力编辑界面

**新增功能**：
1. 单独的能力配置模态框
2. 手动设置选项
3. 快速预设按钮
4. 探测历史展示

---

## 🎨 UI设计建议

### 能力状态标签

```
已检测且支持：
  ✅ 多模态（图片+视频）
  ✅ 视觉（仅图片）
  ✅ 视频（仅视频）

已检测但不支持：
  ❌ 纯文本

未检测：
  ⚠️ 未检测（需要探测）
```

### 探测状态显示

```
探测中：
  🔄 正在探测模型能力...

探测成功：
  ✅ 检测完成：支持图片、视频识别

探测失败：
  ❌ 探测失败：[错误原因]
     建议：手动设置能力或检查API配置
```

---

## 📊 数据流设计

### 添加模型流程

```
用户输入
  ↓
【可选】选择预设
  ↓
提交添加请求
  ↓
├─ 有预设 → 直接保存配置
└─ 无预设 → 自动探测 → 保存配置
  ↓
刷新模型列表
  ↓
显示结果
```

### 探测流程

```
触发探测
  ↓
发送测试请求
  ↓
├─ 图片测试
│   ├─ 成功 → supports_image = true
│   └─ 失败 → supports_image = false
└─ 视频测试
    ├─ 成功 → supports_video = true
    └─ 失败 → supports_video = false
  ↓
计算 supports_multimodal
  ↓
保存配置
  ↓
更新UI
```

---

## 💡 用户提示优化

### 添加模型时

```
💡 提示：
- 推荐选择"自动探测"，系统将自动识别模型能力
- 如果您已知模型能力，可直接选择预设
- 某些模型可能需要配置API密钥后才能探测
```

### 探测失败时

```
❌ 探测失败：API密钥未配置

建议操作：
1. 检查提供商API密钥配置
2. 确认模型ID正确
3. 或手动设置模型能力
```

---

## 🔄 与聊天功能的联动

### 实时更新

```typescript
// 在Chat页面监听模型变化
useEffect(() => {
  const handleModelChange = () => {
    // 重新获取模型能力
    fetchMultimodalCaps();
  };
  
  window.addEventListener('model-updated', handleModelChange);
  return () => window.removeEventListener('model-updated', handleModelChange);
}, []);
```

### 上传时的智能提示

```typescript
// 根据能力动态调整上传行为
const handleUpload = (file: File) => {
  if (!multimodalCaps.supportsMultimodal) {
    // 显示帮助信息
    Modal.confirm({
      title: '模型能力未检测',
      content: (
        <div>
          <p>当前模型的能力尚未检测，可能无法正确处理图片。</p>
          <p>建议前往"设置 → 模型管理"进行能力探测。</p>
        </div>
      ),
      okText: '前往设置',
      onOk: () => navigate('/settings/models'),
      cancelText: '继续上传',
    });
  }
};
```

---

## 📝 总结

### 核心改进点

1. **自动化** - 添加模型时自动探测，减少用户操作
2. **可视化** - 清晰的能力状态展示，一目了然
3. **灵活性** - 支持手动设置、快速预设、批量操作
4. **友好性** - 详细的过程提示和失败说明

### 优先级建议

1. **高优先级** - 添加模型时自动探测
2. **中优先级** - 完善能力编辑界面
3. **低优先级** - 批量操作功能

### 实施步骤

1. 改进添加模型流程（1-2天）
2. 优化模型列表显示（1天）
3. 完善编辑界面（1-2天）
4. 测试和优化（1天）

---

**下一步**：确认方案后，可以开始实施代码修改。
