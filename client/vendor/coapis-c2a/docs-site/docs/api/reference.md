# API Reference - C2A Protocol Specification

## 协议版本

当前协议版本：`c2a-v1.0`

## 核心数据模型

### C2AMessage

C2A 消息的主体结构，包含协议版本、消息ID、上下文引用、元数据、区块列表、动作列表、状态和扩展字段。

```typescript
interface C2AMessage {
  protocol_version: string;           // "c2a-v1.0"
  message_id: string;                 // UUID格式的唯一标识
  context_ref: ContextRef;            // 上下文引用
  metadata: Metadata;                 // 元数据
  blocks: Block[];                    // 区块列表
  actions: Action[];                  // 动作列表
  state: State;                       // 状态机
  extensions?: Record<string, any>;   // 扩展字段
}
```

### ContextRef

上下文引用，用于关联消息与特定的会话或任务。

```typescript
interface ContextRef {
  session_id: string;                 // 会话ID
  task_id?: string;                   // 任务ID（可选）
}
```

### Metadata

元数据信息，包含生成者、生成时间和有效期。

```typescript
interface Metadata {
  generated_by: string;               // 生成者标识
  generated_at: string;               // ISO 8601 格式的时间戳
  ttl_seconds?: number;               // 消息有效时间（秒）
}
```

### Block

区块定义，支持多种类型：`text_markdown`, `data_table`, `data_list`, `form_definition`, `custom_component`。

```typescript
interface Block {
  block_id: string;                   // 区块唯一标识
  type: 'text_markdown' | 'data_table' | 'data_list' | 'form_definition' | 'custom_component';
  content: BlockContent;              // 区块内容
}
```

### Action

交互动作定义，支持多种意图：`api_call`, `function_invoke`, `web_redirect`, `workflow_trigger`, `form_submit`, `custom_extension`。

```typescript
interface Action {
  action_id: string;                  // 动作唯一标识
  label: string;                      // 按钮标签文本
  icon?: string;                      // 图标（可选）
  style: 'primary' | 'secondary' | 'danger' | 'success' | 'warning' | 'text';
  disabled: boolean;                  // 是否禁用
  intent: 'api_call' | 'function_invoke' | 'web_redirect' | 'workflow_trigger' | 'form_submit' | 'custom_extension';
  payload: Record<string, any>;       // 动作载荷
  security: ActionSecurity;           // 安全策略
}
```

### State

状态机模型，支持以下状态：`idle`, `generating`, `rendered`, `interactive`, `executing`, `completed`, `failed`。

```typescript
interface State {
  status: 'idle' | 'generating' | 'rendered' | 'interactive' | 'executing' | 'completed' | 'failed';
  error_code?: string;                // 错误代码（失败状态时）
  error_message?: string;             // 错误消息（失败状态时）
}
```

## JSON Schema 校验

完整的 C2A 消息协议 JSON Schema 定义位于：`schemas/c2a-message-v1.jsonschema`

使用 Python SDK 进行验证：

```python
from c2a_protocol.validator import validate_c2a_message

is_valid, errors = validate_c2a_message(c2a_message_dict)
if not is_valid:
    print(f"Validation errors: {errors}")
```
