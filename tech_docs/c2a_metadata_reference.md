# C2A Metadata 数据结构参考

> MCP 工具返回的 `metadata` 字段是 C2A 卡片渲染的数据源。
> 本文档是开发者编写 MCP 工具时的 metadata 规范参考。

## 整体结构

```jsonc
{
  // ── MCP 标准字段 ──
  "content": [
    { "type": "text", "text": "<业务数据的 JSON 字符串>" }
  ],
  "isError": false,

  // ── C2A 扩展字段 ──
  "metadata": {
    "resource_type": "approval",              // 资源类型（用于 scene_id）
    "external_system": "https://oa.example.com", // 外部系统 base URL
    "summary": "您有 1 条待审批事项。",       // 可选：AI 辅助决策摘要
    "buttons": [                              // 可选：纯导航按钮（label + url + scope）
      { "id": "btn_1", "label": "去审批", "scope": "card", "url_template": "https://oa.example.com/approval/A001" }
    ],
    "action_templates": {                     // 可选：显式声明操作模板
      "row_link": { ... },
      "export_list": { ... },
      "more": { ... }
    }
  }
}
```

## 边界原则

> **AI 只做展示 + 导航，不做业务执行。**

- AI 帮你*决策*（展示数据、给出摘要/建议、提供入口按钮）
- 外部系统*执行*（审批、拒绝、导出、删除等业务操作）
- 所有 `buttons` 都是纯 `<a href>` 链接 — 点击打开外部系统页面，用户在那里操作
- 无 `url_template` 的按钮**不会渲染**（没有目的地 = 无法导航 = 无意义）

## 字段说明

### `metadata.summary` (string, 可选)

AI 辅助决策文本。在卡片表格上方展示，帮用户快速了解：
- 关键结论（"共 5 条待审批，其中 2 条即将超时"）
- 风险提示（"有 1 条超过 48h 未处理"）
- 下一步建议（"建议优先处理 P0 审批"）

**纯展示文本，不触发任何操作。** 支持换行（`\n`）。

### `metadata.buttons` (array, 可选)

纯导航按钮。每个按钮 = 一个 `<a href>` 链接，点击在新标签页打开外部系统。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 按钮唯一标识 |
| `label` | string | 按钮显示文字（如"去审批"、"查看详情"、"导出列表"） |
| `scope` | `"card"` \| `"row"` | `card` = 卡片底部按钮；`row` = 表格行级按钮（本期只支持 card） |
| `url_template` | string | 目标 URL（必填，否则不渲染）。`card` 用完整 URL，`row` 可用 `{field}` 占位符 |
| `style` | string | 按钮样式：`primary` / `secondary` / `danger` / `success`（默认 secondary） |

**关键规则：**
- `url_template` 为空 → 按钮**不渲染**（AI 不能执行业务，没有目的地 = 无用）
- 所有按钮都是 `<a target="_blank">` — 打开外部系统页面，用户在那里操作
- 与 `action_templates` 的区别：`action_templates` 控制表格内的行链接/操作列，`buttons` 是卡片级的操作入口

```jsonc
"buttons": [
  { "id": "btn_approve", "label": "去审批", "scope": "card", "url_template": "https://oa.example.com/approval/A001" },
  { "id": "btn_list",    "label": "查看全部", "scope": "card", "url_template": "https://oa.example.com/approvals" },
  { "id": "btn_export",  "label": "导出列表", "scope": "card", "url_template": "https://oa.example.com/approvals/export" }
]
```

### `metadata.resource_type` (string, 可选)

资源类型标识，会作为 C2A 消息的 `context_ref.scene_id`。

**关键点：协议层无固定枚举，是自由字符串。** 它本质是**展示模式**的名字
（透传为 `scene_id`，不改变渲染）。取值与展示模式对应见专门文档
→ [c2a_resource_type_reference.md](./c2a_resource_type_reference.md)。

常用：`list`（列表）、`record`（单条详情）。不传时默认为 `default_scene`。

### `metadata.external_system` (string, 可选)

外部系统的 base URL，用于生成 `more` 模板的完整链接。

```json
"external_system": "https://oa.example.com"
```

不传时，`more` 模板的 `url_template` 为相对路径。

### `metadata.action_templates` (object, 可选)

**显式声明**操作模板。不传时系统会根据数据结构自动推断。

支持 4 种标准类型：

| type | 用途 | 适用场景 |
|------|------|---------|
| `row_link` | 表格行内超链接 | 多条记录列表，每行可跳转详情 |
| `view_detail` | 行级详情按钮 | 单条记录，显示"查看详情"按钮 |
| `export_list` | 导出列表 | 多条记录列表 |
| `more` | 查看更多 | 列表页有分页时 |

## action_templates 各类型详解

### 1. `row_link` — 行内超链接

表格中指定列渲染为蓝色 `<a>` 链接，点击新标签页打开。

```jsonc
{
  "row_link": {
    "type": "row_link",
    "label": "查看详情",           // 按钮/链接文字
    "url_template": "{detail_url}", // URL 模板，{字段名} 会被替换为行数据
    "business_intent": "view_detail", // 业务意图标识
    "link_column": "detail_url"    // 指定哪一列渲染为链接（可选）
  }
}
```

**`link_column` 规则：**
- 传了 → 只有该列的单元格渲染为链接
- 不传 → 系统自动推断（优先匹配 `名称/标题/title/subject/name` 列，否则第一列）
- **P1-B 规则：数据中没有 URL 字段时，系统不会自动生成 row_link**

**`url_template` 规则：**
- `{field_name}` 占位符会被替换为该行对应字段的值
- 示例：`{detail_url}` → 如果该行 `detail_url = "https://oa.example.com/detail/1"`，则链接为该 URL
- 示例：`{id}` → 如果该行 `id = "A001"`，则链接为 `A001`（注意：需要是完整 URL 才能点击）

### 2. `view_detail` — 行级详情按钮

表格下方显示一个按钮，点击打开详情（仅适用于单条记录）。

```jsonc
{
  "view_detail": {
    "type": "view_detail",
    "label": "查看详情",
    "url_template": "{detail_url}",
    "business_intent": "view_detail"
  }
}
```

### 3. `export_list` — 导出列表

```jsonc
{
  "export_list": {
    "type": "export_list",
    "label": "导出列表为Excel",
    "api_endpoint": "/api/v1/approvals/export",
    "business_intent": "export_list_to_excel"
  }
}
```

### 4. `more` — 查看更多

```jsonc
{
  "more": {
    "type": "more",
    "label": "查看更多",
    "url_template": "/approvals?page=1",
    "business_intent": "open_full_list",
    "context_data": {}
  }
}
```

## 完整示例

### 场景 0：审批列表 + 辅助摘要 + 导航按钮（推荐）

**MCP 工具返回：**

```jsonc
{
  "content": [
    {
      "type": "text",
      "text": "{\"approvals\":[{\"id\":\"A001\",\"名称\":\"采购申请\",\"申请人\":\"张三\",\"金额\":5000,\"状态\":\"审批中\",\"detail_url\":\"https://oa.example.com/approval/A001\"},{\"id\":\"A002\",\"名称\":\"报销申请\",\"申请人\":\"李四\",\"金额\":3200,\"状态\":\"待审批\",\"detail_url\":\"https://oa.example.com/approval/A002\"}]}"
    }
  ],
  "isError": false,
  "metadata": {
    "resource_type": "approval",
    "external_system": "https://oa.example.com",
    "summary": "您有 2 条待审批事项。\n• A001 采购申请（张三）：¥5,000，已等待 2 天\n• A002 报销申请（李四）：¥3,200，今日提交\n\n建议：A001 金额较大，建议优先处理。",
    "buttons": [
      { "id": "btn_approve", "label": "去审批", "scope": "card", "url_template": "https://oa.example.com/approvals" },
      { "id": "btn_export", "label": "导出列表", "scope": "card", "url_template": "https://oa.example.com/approvals/export" }
    ],
    "action_templates": {
      "row_link": {
        "type": "row_link",
        "label": "查看详情",
        "url_template": "{detail_url}",
        "business_intent": "view_detail"
      }
    }
  }
}
```

**生成的 C2A 卡片效果：**
1. 📋 **摘要区**（表格上方）：展示 summary 文本，帮用户快速决策
2. **数据表格**：名称/申请人/金额/状态 列 + 行内链接
3. **按钮区**（表格下方）："去审批" + "导出列表" → 打开外部系统页面

**边界：** AI 没有"同意"/"拒绝"按钮。用户点击"去审批"→ 打开 OA 审批页面 → 在 OA 里操作。

### 场景 1：审批列表（带 URL 字段）

**MCP 工具返回：**

```jsonc
{
  "content": [
    {
      "type": "text",
      "text": "{\"approvals\":[{\"id\":\"A001\",\"名称\":\"采购申请\",\"申请人\":\"张三\",\"日期\":\"2026-08-01\",\"金额\":5000,\"状态\":\"审批中\",\"detail_url\":\"https://oa.example.com/approval/A001\"},{\"id\":\"A002\",\"名称\":\"报销申请\",\"申请人\":\"李四\",\"日期\":\"2026-08-02\",\"金额\":3200,\"状态\":\"已通过\",\"detail_url\":\"https://oa.example.com/approval/A002\"}]}"
    }
  ],
  "isError": false,
  "metadata": {
    "resource_type": "approval",
    "external_system": "https://oa.example.com",
    "action_templates": {
      "row_link": {
        "type": "row_link",
        "label": "查看详情",
        "url_template": "{detail_url}",
        "business_intent": "view_detail",
        "link_column": "detail_url"
      },
      "export_list": {
        "type": "export_list",
        "label": "导出列表为Excel",
        "api_endpoint": "/api/v1/approvals/export",
        "business_intent": "export_list_to_excel"
      },
      "more": {
        "type": "more",
        "label": "查看更多",
        "url_template": "/approvals?page=1",
        "business_intent": "open_full_list",
        "context_data": {}
      }
    }
  }
}
```

**生成的 C2A 卡片效果：**
- 数据表格：4 列（名称、申请人、日期、金额、状态）+ 行内链接（detail_url 列）
- 底部按钮：导出列表、查看更多
- 点击"采购申请"行 → 新标签页打开 `https://oa.example.com/approval/A001`

### 场景 2：审批列表（无 URL 字段，不传 action_templates）

**MCP 工具返回：**

```jsonc
{
  "content": [
    {
      "type": "text",
      "text": "{\"orders\":[{\"id\":1001,\"商品\":\"笔记本\",\"数量\":2,\"金额\":12000},{\"id\":1002,\"商品\":\"显示器\",\"数量\":1,\"金额\":3500}]}"
    }
  ],
  "isError": false,
  "metadata": {
    "resource_type": "order"
  }
}
```

**系统自动推断：**
- 没有 URL 字段 → **不生成 row_link**
- 生成 export_list + more
- 表格显示商品、数量、金额列

### 场景 3：单条记录

**MCP 工具返回：**

```jsonc
{
  "content": [
    {
      "type": "text",
      "text": "{\"record\":{\"id\":\"A001\",\"名称\":\"采购申请\",\"申请人\":\"张三\",\"状态\":\"审批中\",\"detail_url\":\"https://oa.example.com/approval/A001\"}}"
    }
  ],
  "isError": false,
  "metadata": {
    "resource_type": "approval",
    "action_templates": {
      "view_detail": {
        "type": "view_detail",
        "label": "查看详情",
        "url_template": "{detail_url}",
        "business_intent": "view_detail"
      }
    }
  }
}
```

**生成的 C2A 卡片效果：**
- 单行数据表格
- 底部"查看详情"按钮 → 打开 `https://oa.example.com/approval/A001`

### 场景 4：顶层列表（无外层 dict 包裹）

**MCP 工具返回：**

```jsonc
{
  "content": [
    {
      "type": "text",
      "text": "[{\"id\":\"T001\",\"标题\":\"紧急修复\",\"优先级\":\"P0\",\"detail_url\":\"https://oa.example.com/task/T001\"},{\"id\":\"T002\",\"标题\":\"功能优化\",\"优先级\":\"P2\",\"detail_url\":\"https://oa.example.com/task/T002\"}]"
    }
  ],
  "isError": false,
  "metadata": {
    "resource_type": "task"
  }
}
```

**系统自动推断：**
- 顶层列表 → 识别为多条记录
- 有 URL 字段（detail_url）→ 生成 row_link
- `link_column` 自动推断为 `标题`（匹配"标题"模式）

### 场景 5：嵌套数据（深层结构）

**MCP 工具返回：**

```jsonc
{
  "content": [
    {
      "type": "text",
      "text": "{\"data\":{\"result\":{\"items\":[{\"id\":\"U001\",\"名称\":\"王五\",\"邮箱\":\"wangwu@example.com\",\"profile_url\":\"https://hr.example.com/user/U001\"}]}}}"
    }
  ],
  "isError": false,
  "metadata": {
    "resource_type": "user"
  }
}
```

**系统自动推断：**
- 递归查找（最多 3 层）→ 找到 `data.result.items`
- 单条记录 → 生成 view_detail（有 URL 字段 profile_url）

## 自动推断规则总结

当 `metadata.action_templates` 未提供时，系统按以下规则推断：

| 数据结构 | 推断结果 |
|---------|---------|
| 多条记录 + 有 URL 字段 | row_link + export_list + more |
| 多条记录 + 无 URL 字段 | export_list + more（**无 row_link**） |
| 单条记录 + 有 URL 字段 | view_detail |
| 单条记录 + 无 URL 字段 | 无操作模板 |
| 无列表数据 | 无表格、无操作模板 |

**URL 字段检测优先级：**
1. 字段名包含 `url` 或 `link`（如 `detail_url`, `page_link`）
2. 字段值以 `http://` 或 `https://` 开头

**`link_column` 推断优先级：**
1. 列名包含 `名称/标题/title/subject/summary/name`（不区分大小写）
2. 回退到第一列

## 注意事项

1. **`content[0].text` 必须是合法 JSON 字符串**，否则会被静默丢弃
2. **URL 字段必须是完整 URL**（`https://...`），相对路径无法点击
3. **`link_column` 必须是 `headers` 中存在的列名**，否则链接不显示
4. **`action_templates` 中的 value 必须是对象**，非对象值会被跳过
5. **ID 字段**（`id`, `approval_id`, `order_id` 等）会从表格列中排除，仅用于内部逻辑
