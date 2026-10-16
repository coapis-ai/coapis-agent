# C2A 协议使用指南

> **版本：** `c2a-v1.0`（唯一规范版本，无 v2/v3 分叉）
> **受众：** 外部系统开发者（MCP 工具编写者）、AI Agent 开发者、前端集成者
> **核心原则：** **AI 只做展示 + 导航，不做业务执行。** 外部系统执行业务操作。

---

## 目录

1. [协议概览](#1-协议概览)
2. [消息结构](#2-消息结构-c2amessage)
3. [MCP 工具返回格式](#3-mcp-工具返回格式)
4. [Metadata 字段详解](#4-metadata-字段详解)
5. [Action Templates](#5-action-templates)
6. [Block 类型与数据结构](#6-block-类型与数据结构)
7. [行链接机制](#7-行链接机制)
8. [Buttons 导航按钮](#8-buttons-导航按钮)
9. [自动推断规则](#9-自动推断规则)
10. [完整数据示例](#10-完整数据示例)
11. [注意事项与常见问题](#11-注意事项与常见问题)

---

## 1. 协议概览

C2A（Chat-to-Action）是一个**交互式消息协议**，将 AI 对话中的结构化数据渲染为可交互的卡片（表格、按钮、链接等），实现"在 AI 对话中查看数据 → 跳转到外部系统执行业务操作"的闭环。

### 数据流

```
外部系统 API
    ↓
MCP 工具（返回结构化数据 + metadata）
    ↓
MCPC2AParser（解析数据，推断/使用 action_templates）
    ↓
C2AMessage（标准协议消息）
    ↓
C2A 前端渲染器（React 组件）
    ↓
用户看到卡片 → 点击链接/按钮 → 打开外部系统页面执行操作
```

### 边界原则

| AI 做什么 | 外部系统做什么 |
|-----------|---------------|
| 展示数据（表格、列表） | 审批、拒绝、删除等业务操作 |
| 给出摘要/建议（辅助决策） | 执行业务逻辑 |
| 提供导航入口（链接、按钮） | 处理页面交互 |

**关键规则：所有按钮都是纯 `<a href>` 导航链接，AI 不执行任何业务 API 调用。**

---

## 2. 消息结构 (C2AMessage)

一条 C2A 消息是 JSON 对象，结构如下：

```jsonc
{
  // ── 必需字段 ──
  "protocol_version": "c2a-v1.0",
  "message_id": "uuid-string",
  "context_ref": {
    "session_id": "session-uuid",
    "task_id": null,          // 可选
    "scene_id": "list"        // 可选，对应 metadata.resource_type
  },
  "blocks": [ /* 内容块，见 §6 */ ],
  "actions": [],              // 遗留字段，当前不使用（边界重构后已清空）
  "state": {
    "status": "rendered",     // idle | generating | rendered | interactive | completed | failed
    "error_code": null,
    "error_message": null
  },

  // ── 可选字段 ──
  "metadata": { /* 见 §4 */ },
  "suggestions": [ /* 快捷建议，见下方 */ ],
  "extensions": {}            // 扩展字段
}
```

### Suggestions（快捷建议）

卡片下方的快捷回复按钮，用于引导用户下一步操作：

```jsonc
"suggestions": [
  {
    "suggestion_id": "sug_export_list",
    "label": "📤 导出当前列表为Excel",
    "business_intent": "export_list_to_excel",
    "context_data": { "api_endpoint": "/api/v1/approvals/export" }
  },
  {
    "suggestion_id": "sug_more",
    "label": "📋 查看更多",
    "business_intent": "open_full_list",
    "context_data": { "url_template": "https://oa.example.com/approvals?page=1" }
  }
]
```

---

## 3. MCP 工具返回格式

MCP 工具是 C2A 数据的**主要来源**。工具的返回值需要遵循以下格式：

### 3.1 基本结构

```jsonc
{
  "content": [
    {
      "type": "text",
      "text": "<业务数据的 JSON 字符串>"  // 必须是合法 JSON
    }
  ],
  "isError": false,
  "metadata": { /* C2A 扩展字段，见 §4 */ }
}
```

### 3.2 `content[0].text` 的格式要求

- **必须是合法 JSON 字符串**（`json.loads` 能解析的）
- 支持三种数据形态：

| 形态 | 示例 | 说明 |
|------|------|------|
| 顶层 dict 包含列表 | `{"approvals": [...]}` | 最常见，key 可以是任意名称 |
| 顶层列表 | `[{"id":"A001", ...}, ...]` | 直接是数组 |
| 嵌套 dict | `{"data": {"result": {"items": [...]}}}` | 最多 3 层深度递归 |

### 3.3 数据项要求

列表中的每个元素必须是**扁平的 dict**（键值对），不支持嵌套 dict/list 作为字段值：

```jsonc
// ✅ 正确：扁平结构
{ "id": "A001", "名称": "采购申请", "金额": 5000, "状态": "审批中" }

// ❌ 错误：嵌套对象
{ "id": "A001", "详情": { "名称": "采购申请", "金额": 5000 } }
```

### 3.4 ID 字段

系统会自动识别 ID 字段并从表格列中隐藏（仅用于内部行链接逻辑）。

**识别优先级：**
1. 精确匹配：`id`、`approval_id`、`order_id`、`task_id`、`record_id`、`_id`
2. 启发式匹配：任何以 `_id` 结尾的字段名（如 `user_id`、`doc_id`）

**下划线前缀的字段**（如 `_internal`）也会自动从表格中隐藏。

### 3.5 URL 字段

系统会自动检测数据中的 URL 字段，用于生成行链接。

**检测优先级：**
1. 精确匹配候选名：`detail_url`、`view_url`、`page_url`、`url`、`link`、`detail_link`、`view_link`、`href`、`detail_href`
2. 启发式匹配：字段名包含 `url` / `link` / `href`，且值以 `http://` / `https://` / `/` 开头

**关键：URL 字段必须是完整 URL 或内部路径，相对路径（如 `approval/1`）无法点击。**

---

## 4. Metadata 字段详解

`metadata` 是 C2A 的**扩展字段**，放在 MCP 工具返回值的顶层（与 `content` 平级）：

```jsonc
{
  "content": [ ... ],
  "isError": false,
  "metadata": {
    "resource_type": "list",
    "external_system": "https://oa.example.com",
    "summary": "您有 2 条待审批事项。",
    "buttons": [ ... ],
    "action_templates": { ... }
  }
}
```

### 4.1 `resource_type`（string，可选）

展示模式标识，透传为 C2A 消息的 `context_ref.scene_id`。

| 值 | 含义 | 数据形态 |
|----|------|---------|
| `list` | 列表 | 多条记录 → 数据表格 |
| `record` | 单条详情 | 单条记录 → 单行表格 |

**这是自由字符串，无固定枚举。** 不传时默认 `default_scene`。目前仅作为语义标记，**不改变渲染**——卡片长什么样由数据形态自动推断决定（多条→表格，单条→单行表格）。

### 4.2 `external_system`（string，可选）

外部系统的 base URL，用于生成 `more` 模板的完整链接。

```json
"external_system": "https://oa.example.com"
```

不传时，`more` 模板的 `url_template` 为相对路径。

### 4.3 `summary`（string，可选）

**AI 辅助决策文本**，渲染在卡片表格上方。帮用户快速了解：
- 关键结论（"共 5 条待审批，其中 2 条即将超时"）
- 风险提示（"有 1 条超过 48h 未处理"）
- 下一步建议（"建议优先处理 P0 审批"）

**纯展示文本，不触发任何操作。** 支持换行（`\n`）。

### 4.4 `buttons`（array，可选）

纯导航按钮。详见 [§8 Buttons 导航按钮](#8-buttons-导航按钮)。

### 4.5 `action_templates`（object，可选）

显式声明操作模板。详见 [§5 Action Templates](#5-action-templates)。

---

## 5. Action Templates

`action_templates` 声明表格内的行级操作。当不提供时，系统根据数据结构**自动推断**（见 [§9 自动推断规则](#9-自动推断规则)）。

### 5.1 四种标准类型

| 类型 | 用途 | 适用场景 |
|------|------|---------|
| `row_link` | 表格行内超链接 | 多条记录列表，每行可跳转详情 |
| `view_detail` | 行级详情按钮 | 单条记录，显示"查看详情"按钮 |
| `export_list` | 导出列表 | 多条记录列表 |
| `more` | 查看更多 | 列表有分页时 |

### 5.2 `row_link` — 行内超链接

表格中指定列渲染为蓝色链接，点击新标签页打开外部页面。

```jsonc
"row_link": {
  "type": "row_link",
  "label": "查看详情",
  "url_template": "{detail_url}",   // {字段名} 会被替换为行数据
  "business_intent": "view_detail",
  "link_column": "detail_url"       // 指定哪一列渲染为链接（可选）
}
```

**字段说明：**

| 字段 | 必填 | 说明 |
|------|------|------|
| `type` | 是 | 固定 `"row_link"` |
| `label` | 否 | 链接文字，默认"查看详情" |
| `url_template` | 是 | URL 模板，`{field_name}` 占位符会被替换为该行对应字段的值 |
| `business_intent` | 否 | 业务意图标识 |
| `link_column` | 否 | 指定哪一列渲染为链接。不传时自动推断（优先匹配 名称/标题/title/subject 列，否则第一列） |

**`url_template` 占位符规则：**
- `{field_name}` → 替换为该行 `field_name` 字段的值
- 支持单花括号 `{field}`（C2A 标准）和双花括号 `{{field}}`（兼容旧版）
- 替换后值会自动 `encodeURIComponent` 编码
- **必须是完整 URL**（`https://...`），相对路径无法点击

### 5.3 `view_detail` — 单条详情按钮

适用于单条记录数据，在表格下方显示一个按钮。

```jsonc
"view_detail": {
  "type": "view_detail",
  "label": "查看详情",
  "url_template": "{detail_url}",
  "business_intent": "view_detail"
}
```

### 5.4 `export_list` — 导出列表

```jsonc
"export_list": {
  "type": "export_list",
  "label": "导出列表为Excel",
  "api_endpoint": "/api/v1/approvals/export",
  "business_intent": "export_list_to_excel"
}
```

### 5.5 `more` — 查看更多

```jsonc
"more": {
  "type": "more",
  "label": "查看更多",
  "url_template": "https://oa.example.com/approvals?page=1",
  "business_intent": "open_full_list",
  "context_data": {}
}
```

### 5.6 完整 action_templates 示例

```jsonc
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
    "url_template": "https://oa.example.com/approvals?page=1",
    "business_intent": "open_full_list",
    "context_data": {}
  }
}
```

---

## 6. Block 类型与数据结构

C2A 消息的 `blocks` 数组是卡片内容的主体。

### 6.1 支持的 Block 类型

| 类型 | 用途 | 主要使用场景 |
|------|------|-------------|
| `text_markdown` | Markdown 文本 | LLM 直接构造 |
| `data_table` | 数据表格 | MCP 数据自动转换（**最常用**） |
| `data_list` | 数据列表 | LLM 直接构造 |
| `form_definition` | 表单 | LLM 直接构造 |
| `custom_component` | 自定义组件 | 预留 |

> **注意：** MCP 工具数据目前只自动生成 `data_table` 块。其他类型由 LLM 直接构造 C2A 消息时使用。

### 6.2 `data_table` 块结构

```jsonc
{
  "block_id": "block_table_msg_001",
  "type": "data_table",
  "content": {
    // ── 必需 ──
    "data": {
      "headers": ["名称", "申请人", "金额", "状态"],
      "rows": [
        ["采购申请", "张三", "5000", "审批中"],
        ["报销申请", "李四", "3200", "待审批"]
      ]
    },

    // ── 行链接管道（有 ID 字段时自动生成）──
    "id_field": "id",
    "row_values": [
      { "id": "A001" },
      { "id": "A002" }
    ],

    // ── 行操作（有 URL 字段时自动生成）──
    "row_actions": {
      "view_detail": {
        "action_id": "btn_view_detail",
        "label": "查看详情",
        "style": "link",
        "business_intent": "view_detail",
        "url_template": "{detail_url}",
        "link_column": "detail_url"
      }
    }
  }
}
```

**字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `data.headers` | `string[]` | 列名（ID 字段和下划线前缀字段自动排除） |
| `data.rows` | `string[][]` | 行数据（所有值都是字符串） |
| `id_field` | `string` | 隐藏的 ID 字段名（用于行链接构建） |
| `row_values` | `Array<{id: value}>` | 每行的 ID 值（ID 列在表格中隐藏，但链接需要它） |
| `row_actions` | `object` | 行操作模板（row_link / view_detail） |

### 6.3 `text_markdown` 块结构

```jsonc
{
  "block_id": "block_text_001",
  "type": "text_markdown",
  "content": {
    "markdown": "## 审批摘要\n\n您有 **2** 条待审批事项。"
  }
}
```

### 6.4 `data_list` 块结构

```jsonc
{
  "block_id": "block_list_001",
  "type": "data_list",
  "content": {
    "items": [
      { "key": "item_1", "title": "采购申请", "subtitle": "张三 · ¥5,000" },
      { "key": "item_2", "title": "报销申请", "subtitle": "李四 · ¥3,200" }
    ]
  }
}
```

---

## 7. 行链接机制

行链接是 C2A 最核心的交互功能，允许用户从表格直接跳转到外部系统的详情页。

### 7.1 工作原理

```
1. MCP 数据中有 URL 字段（如 detail_url）
2. Parser 检测到此字段 → 生成 row_actions.row_link
3. 前端渲染时：
   a. 找到 link_column 指定的列（或自动推断的列）
   b. 将该列的单元格渲染为蓝色 <a> 链接
   c. 点击时用 row_values 中的 ID 值 + url_template 构建完整 URL
   d. 新标签页打开外部页面
```

### 7.2 数据要求

要生成行链接，MCP 数据必须同时满足：

1. **有 ID 字段**（`id` / `*_id` 等）
2. **有 URL 字段**（`detail_url` / `url` / `link` 等，值为完整 URL）

**缺少任何一个 → 不生成行链接，只显示纯表格。**

### 7.3 `link_column` 规则

| 情况 | 行为 |
|------|------|
| 显式指定 `link_column` | 只有该列的单元格渲染为链接 |
| 不指定，有匹配列 | 自动选择：列名包含 名称/标题/title/subject/summary/name |
| 不指定，无匹配列 | 回退到第一列 |
| 数据无 URL 字段 | **不生成 row_link**（不会生成假链接） |

### 7.4 `url_template` 占位符

```jsonc
"url_template": "{detail_url}"
```

- 单花括号 `{field_name}`：C2A 标准
- 双花括号 `{{field_name}}`：兼容旧版
- 替换值自动 `encodeURIComponent` 编码
- 缺少占位符值时，返回原始模板（容错，不崩溃）

---

## 8. Buttons 导航按钮

`metadata.buttons` 是卡片级的纯导航按钮，渲染在表格下方。

### 8.1 结构

```jsonc
"buttons": [
  {
    "id": "btn_approve",        // 唯一标识
    "label": "去审批",           // 显示文字
    "scope": "card",            // "card" | "row"
    "url_template": "https://oa.example.com/approvals",  // 目标 URL（必填）
    "style": "primary"          // 样式（可选）
  }
]
```

### 8.2 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | 是 | 按钮唯一标识 |
| `label` | string | 是 | 显示文字（如"去审批"、"查看详情"、"导出列表"） |
| `scope` | string | 是 | `"card"` = 卡片底部；`"row"` = 表格行级（本期只支持 card） |
| `url_template` | string | 是 | 目标 URL。**为空则按钮不渲染** |
| `style` | string | 否 | `primary` / `secondary` / `danger` / `success` / `warning` / `text`，默认 secondary |

### 8.3 关键规则

- **`url_template` 为空 → 按钮不渲染**（没有目的地 = 无法导航 = 无意义）
- **所有按钮都是 `<a target="_blank">`** — 打开外部系统页面，用户在那里操作
- **AI 不做业务执行** — 没有"同意"、"拒绝"、"删除"按钮，只有"去审批"、"查看详情"等导航按钮

### 8.4 完整示例

```jsonc
"buttons": [
  { "id": "btn_approve", "label": "去审批", "scope": "card", "url_template": "https://oa.example.com/approvals", "style": "primary" },
  { "id": "btn_list",    "label": "查看全部", "scope": "card", "url_template": "https://oa.example.com/approvals" },
  { "id": "btn_export",  "label": "导出列表", "scope": "card", "url_template": "https://oa.example.com/approvals/export" }
]
```

---

## 9. 自动推断规则

当 `metadata.action_templates` **未提供**时，系统根据数据结构自动推断操作模板：

| 数据结构 | 推断结果 |
|---------|---------|
| 多条记录 + 有 URL 字段 | `row_link` + `export_list` + `more` |
| 多条记录 + 无 URL 字段 | `export_list` + `more`（**无 row_link**） |
| 单条记录 + 有 URL 字段 | `view_detail` |
| 单条记录 + 无 URL 字段 | 无操作模板 |
| 无列表数据 | 无表格、无操作模板 |

### ID 字段识别

```
精确匹配（按优先级）: id → approval_id → order_id → task_id → record_id → _id
启发式匹配: 任何以 _id 结尾的字段名
```

### URL 字段检测

```
精确匹配（按优先级）: detail_url → view_url → page_url → url → link → detail_link → view_link → href → detail_href
启发式匹配: 字段名包含 url/link/href，且值以 http/https/ / 开头
```

### link_column 推断

```
1. 列名包含: 名称 / 标题 / title / subject / summary / name（不区分大小写）
2. 回退: 第一列
```

---

## 10. 完整数据示例

### 示例 1：审批列表 + 摘要 + 导航按钮（推荐完整形态）

**MCP 工具返回：**

```jsonc
{
  "content": [
    {
      "type": "text",
      "text": "{"approvals":[{"id":"A001","名称":"采购申请","申请人":"张三","日期":"2026-08-01","金额":5000,"状态":"审批中","detail_url":"https://oa.example.com/approval/A001"},{"id":"A002","名称":"报销申请","申请人":"李四","日期":"2026-08-02","金额":3200,"状态":"待审批","detail_url":"https://oa.example.com/approval/A002"}]}"
    }
  ],
  "isError": false,
  "metadata": {
    "resource_type": "list",
    "external_system": "https://oa.example.com",
    "summary": "您有 2 条待审批事项。\n• A001 采购申请（张三）：¥5,000，已等待 2 天\n• A002 报销申请（李四）：¥3,200，今日提交\n\n建议：A001 金额较大，建议优先处理。",
    "buttons": [
      { "id": "btn_approve", "label": "去审批", "scope": "card", "url_template": "https://oa.example.com/approvals", "style": "primary" },
      { "id": "btn_export", "label": "导出列表", "scope": "card", "url_template": "https://oa.example.com/approvals/export" }
    ],
    "action_templates": {
      "row_link": {
        "type": "row_link",
        "label": "查看详情",
        "url_template": "{detail_url}",
        "business_intent": "view_detail",
        "link_column": "detail_url"
      }
    }
  }
}
```

**生成的 C2A 消息：**

```jsonc
{
  "protocol_version": "c2a-v1.0",
  "message_id": "abc-123",
  "context_ref": {
    "session_id": "sess-001",
    "scene_id": "list"
  },
  "metadata": {
    "generated_by": "mcp-tool-parser",
    "source_system": "https://oa.example.com",
    "summary": "您有 2 条待审批事项。\n• A001 采购申请（张三）：¥5,000，已等待 2 天\n• A002 报销申请（李四）：¥3,200，今日提交\n\n建议：A001 金额较大，建议优先处理。",
    "buttons": [
      { "id": "btn_approve", "label": "去审批", "scope": "card", "url_template": "https://oa.example.com/approvals", "style": "primary" },
      { "id": "btn_export", "label": "导出列表", "scope": "card", "url_template": "https://oa.example.com/approvals/export", "style": "secondary" }
    ]
  },
  "blocks": [
    {
      "block_id": "block_table_abc-123",
      "type": "data_table",
      "content": {
        "data": {
          "headers": ["名称", "申请人", "日期", "金额", "状态", "detail_url"],
          "rows": [
            ["采购申请", "张三", "2026-08-01", "5000", "审批中", "https://oa.example.com/approval/A001"],
            ["报销申请", "李四", "2026-08-02", "3200", "待审批", "https://oa.example.com/approval/A002"]
          ]
        },
        "id_field": "id",
        "row_values": [
          { "id": "A001" },
          { "id": "A002" }
        ],
        "row_actions": {
          "view_detail": {
            "action_id": "btn_view_detail",
            "label": "查看详情",
            "style": "link",
            "business_intent": "view_detail",
            "url_template": "{detail_url}",
            "link_column": "detail_url"
          }
        }
      }
    }
  ],
  "actions": [],
  "state": { "status": "rendered" },
  "suggestions": []
}
```

**前端渲染效果：**
1. 📋 **摘要区**（表格上方）：展示 summary 文本
2. **数据表格**：名称/申请人/日期/金额/状态/detail_url 列，detail_url 列渲染为蓝色链接
3. **按钮区**（表格下方）：「去审批」（primary）+「导出列表」（secondary）

**用户交互：**
- 点击 "detail_url" 列的链接 → 新标签页打开 `https://oa.example.com/approval/A001`
- 点击 "去审批" → 新标签页打开 `https://oa.example.com/approvals`
- 点击 "导出列表" → 新标签页打开导出页面

### 示例 2：审批列表（无 URL 字段，不传 action_templates）

**MCP 工具返回：**

```jsonc
{
  "content": [
    {
      "type": "text",
      "text": "{"orders":[{"id":1001,"商品":"笔记本","数量":2,"金额":12000},{"id":1002,"商品":"显示器","数量":1,"金额":3500}]}"
    }
  ],
  "isError": false,
  "metadata": {
    "resource_type": "list"
  }
}
```

**系统自动推断：**
- 没有 URL 字段 → **不生成 row_link**
- 生成 `export_list` + `more`（`more` 的 URL 为 `/orders?page=1`，无 external_system 时为相对路径）
- 表格显示商品、数量、金额列（ID 隐藏）

### 示例 3：单条记录（有 URL 字段）

**MCP 工具返回：**

```jsonc
{
  "content": [
    {
      "type": "text",
      "text": "{"record":{"id":"A001","名称":"采购申请","申请人":"张三","状态":"审批中","detail_url":"https://oa.example.com/approval/A001"}}"
    }
  ],
  "isError": false,
  "metadata": {
    "resource_type": "record",
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

**生成的 C2A 卡片：**
- 单行数据表格（名称/申请人/状态/detail_url 列）
- 底部"查看详情"按钮 → 打开 `https://oa.example.com/approval/A001`
- Suggestions: "👁️ 查看 A001 详情"

### 示例 4：顶层列表（无外层 dict 包裹）

**MCP 工具返回：**

```jsonc
{
  "content": [
    {
      "type": "text",
      "text": "[{"id":"T001","标题":"紧急修复","优先级":"P0","detail_url":"https://oa.example.com/task/T001"},{"id":"T002","标题":"功能优化","优先级":"P2","detail_url":"https://oa.example.com/task/T002"}]"
    }
  ],
  "isError": false,
  "metadata": {
    "resource_type": "list"
  }
}
```

**系统自动推断：**
- 顶层列表 → 多条记录
- 有 URL 字段（detail_url）→ 生成 row_link
- `link_column` 自动推断为 `标题`（匹配"标题"模式）

### 示例 5：嵌套数据（深层结构）

**MCP 工具返回：**

```jsonc
{
  "content": [
    {
      "type": "text",
      "text": "{"data":{"result":{"items":[{"id":"U001","名称":"王五","邮箱":"wangwu@example.com","profile_url":"https://hr.example.com/user/U001"}]}}}"
    }
  ],
  "isError": false,
  "metadata": {
    "resource_type": "record"
  }
}
```

**系统自动推断：**
- 递归查找（最多 3 层）→ 找到 `data.result.items`
- 单条记录 → 生成 `view_detail`（有 URL 字段 profile_url）

### 示例 6：纯数据表格（无任何操作）

**MCP 工具返回：**

```jsonc
{
  "content": [
    {
      "type": "text",
      "text": "{"statistics":[{"月份":"2026-06","销售额":1250000,"订单数":342},{"月份":"2026-07","销售额":1380000,"订单数":389},{"月份":"2026-08","销售额":1120000,"订单数":298}]}"
    }
  ],
  "isError": false,
  "metadata": {
    "resource_type": "list"
  }
}
```

**系统自动推断：**
- 3 条记录，无 ID 字段，无 URL 字段
- 不生成 row_link
- 生成 `export_list` + `more`
- 表格显示月份、销售额、订单数列（纯数据展示）

---

## 11. 注意事项与常见问题

### 11.1 必须遵守

| # | 规则 | 违反后果 |
|---|------|---------|
| 1 | `content[0].text` 必须是合法 JSON 字符串 | 解析失败，卡片不渲染 |
| 2 | URL 字段必须是完整 URL（`https://...`） | 行链接无法点击 |
| 3 | `link_column` 必须是 `headers` 中存在的列名 | 链接不显示 |
| 4 | `action_templates` 中的 value 必须是对象 | 非对象值被跳过 |
| 5 | `buttons` 中 `url_template` 不能为空 | 空 URL 的按钮不渲染 |
| 6 | 数据项必须是扁平 dict（键值对） | 嵌套对象无法正确渲染为表格列 |

### 11.2 常见问题

**Q: 表格中没有显示行链接？**
- 检查数据中是否有 URL 字段（`detail_url`/`url`/`link` 等）
- 检查 URL 字段的值是否是完整 URL（`https://...`）
- 检查 `link_column` 是否指向了实际存在的列

**Q: 按钮没有显示？**
- 检查 `url_template` 是否为空（空 URL = 不渲染）
- 检查 `scope` 是否为 `"card"`（当前只支持 card）

**Q: 表格列