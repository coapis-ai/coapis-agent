# C2A 展示模式

> 卡片长什么样由**数据形态自动推断**决定。`metadata.resource_type` 就是这类展示模式的名字——透传为 `context_ref.scene_id`，**不改变渲染**，不填默认 `default_scene`。

## 展示模式（2 种）

| resource_type | 展示模式 | 数据形态 | 渲染效果 |
|---|---|---|---|
| `list` | 列表 | 多条记录 | 数据表格；每行带 URL 字段则该行可点击跳转，否则纯展示；底部带「导出 / 更多」 |
| `record` | 单条详情 | 单条记录 | 单行表格；带 URL 字段则出「查看详情」按钮，否则纯展示 |

## 要点

- **可点击与否只看数据里有没有 URL 字段**（`detail_url`/`url`/`link` 等，或值以 `http` 开头），与 `resource_type` 无关。
- **ID 字段**（`id` / `*_id`）自动隐藏出表格，仅用于生成行链接。
- **表单 / 富文本**是协议支持的块类型，由 LLM 直接构造 C2A 消息产生，不走 MCP 数据自动推断，无需 `resource_type`。
- `resource_type` 目前仅作语义标记（供未来按场景路由 / 权限用）；新增业务无需改代码。

## 最小示例

```jsonc
"metadata": {
  "resource_type": "list"   // 多条用 list；单条用 record
}
```
