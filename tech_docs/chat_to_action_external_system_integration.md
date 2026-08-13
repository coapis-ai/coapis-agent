# Chat-to-Action：外部系统对接与交互式消息卡片实施方案

## 一、 背景与目标

在以 AI 为底座的企业级智能体平台（如 CoApis）中，用户不仅需要获取文本回复，更期望通过对话**“唤醒”外部系统的特定功能**，并在对话界面中看到结构化的数据摘要以及操作入口按钮（如“查询详细报表”、“点击查看详情跳转至外部系统”等）。

这种交互模式在业界被称为 **“Chat-to-Action（对话即操作）”** 或 **“交互式消息卡片（Interactive Message Cards / Rich Messages）”**。本方案旨在提供完整的技术可行性分析与合理的解决方案，涵盖前端对话显示方式、多频道/多端显示方式，以及底层 AI 底座与外部系统的集成机制。

---

## 二、 技术可行性分析

### 1. LLM 意图识别与工具调用（Function Calling / Tool Use）
现代大语言模型具备强大的 Function Calling / Tool Use 能力。当用户在对话中提出“查询某某数据”或“查看某审批流程”时，LLM 能够：
- 准确识别用户意图。
- 自动选择并调用预定义的外部系统 API/Tool（如 `query_external_data`, `get_approval_status`）。
- 将外部系统的返回结果转化为结构化的 JSON 对象。

### 2. 结构化输出与卡片协议（Structured Output / Card Schema）
后端可以将 AI 的执行结果和外部系统的操作入口，封装成标准的 **交互卡片 JSON 数据结构**（包含按钮文本、链接 URL、数据摘要等字段），并通过 SSE/WebSocket 流式推送给前端。

### 3. 前端富消息渲染能力
在前端聊天界面中，现代 Web 框架（如 React + Ant Design）支持自定义消息类型解析。将 LLM 返回的特定 JSON 结构或标记语言转换为 UI 组件（如带有“查询数据”、“查看详情”等按钮的消息卡片），并绑定前端的事件处理函数。

### 4. 外部系统对接与 SSO 单点登录能力
当用户点击“查看详情”按钮时，后端可以生成带有有效 SSO Token 或 Session 的深链接（Deep Link）。利用现有的 `/api/external/login?token=签名&username=...&redirect=/target-page` 机制，实现无缝、安全的外部系统自动登录与数据查看。

---

## 三、 核心架构设计

整体架构涉及 **LLM -> 后端 API/服务 -> 前端 UI / 多端频道** 的三方协同：

1. **AI 底座层（意图唤醒）**：LLM 在 ReAct 循环或规划阶段，识别到需要外部系统数据时，调用对应的 MCP Tool 或 Builtin Tool。
2. **后端服务层（卡片协议与 SSO 链接生成）**：工具执行完毕后，后端不仅返回纯文本结果，还生成**交互卡片 JSON（Card Payload）**，并为“查看详情”等操作生成带有安全凭证的 Deep Link。
3. **前端/频道展示层（富消息渲染）**：
   - **Web 对话界面**：解析并渲染 `interactive_card` JSON，生成带按钮和链接的 UI 卡片组件。
   - **多端频道（企业微信、钉钉等）**：将标准 Card JSON 转换为各平台原生的富消息/卡片格式（如企微 Markdown 卡片、钉钉 ActionCard、Slack Block Kit）。

---

## 四、 后端实施方案

### 4.1 交互卡片协议定义（Card Protocol）
后端需定义一套标准的“卡片 JSON Schema”，用于承载外部系统的入口和链接信息。示例如下：

```json
{
  "type": "interactive_card",
  "variant": "data_summary",
  "title": "销售数据概览",
  "summary": "本月销售额为 150,000 元，已完成目标 85%。",
  "actions": [
    {
      "id": "action_query_report",
      "text": "查询详细报表",
      "type": "button_primary",
      "action_type": "query_report",
      "url": "/api/external/reports/sales?month=2026-08"
    },
    {
      "id": "action_view_details_external",
      "text": "查看详情 -> 跳转至外部系统",
      "type": "button_secondary",
      "action_type": "view_details_external",
      "deep_link": "https://external-system.com/details?id=12345&token=SSO_TOKEN_XXX"
    }
  ]
}
```

### 4.2 Tool Calling / Function Calling 设计
- 在 `server/coapis/agents/tools/` 或 MCP Gateway 中，定义外部系统功能的 Tools（如 `query_external_data`, `get_approval_status`, `submit_approval_flow`）。
- LLM 在执行完业务逻辑后，主动调用这些工具获取数据，并将结果与操作指令组装成 Card JSON。
- 对于涉及状态修改的操作（如提交审批），Tool 返回的卡片应包含“确认/取消”按钮，LLM 在生成卡片时应提示用户“点击确认后将在 OA 系统中发起流程”。

### 4.3 SSO Deep Link 生成机制
- 利用现有的 `external_login.py` 中的 SSO Token 签名机制，为“查看详情”等外部跳转生成带有有效身份凭证的安全 URL。
- 后端 API 提供接口如 `/api/external/generate_deep_link?system=oa&target=/approval/12345&username={user}`，返回带签名的 `token` 和完整的 `deep_link`。

---

## 五、 前端实施方案

### 5.1 Web 对话界面显示方式（Interactive Card Component）
- **组件开发**：在前端 `client/src/pages/Messages/components/` 或消息渲染模块中，开发 `InteractiveCard.tsx`、`ActionButtons.tsx` 等组件。使用 Ant Design 的 `Card`、`Button`、`Space` 等基础 UI 元素构建卡片布局。
- **消息解析器增强**：修改前端 SSE/WebSocket 消息解析引擎，使其能够识别 LLM 回复或 Tool 输出中的 `type: interactive_card` JSON 结构。当检测到该类型时，切换为卡片渲染模式，而非纯文本/Markdown 气泡展示。
- **按钮事件绑定**：用户点击“查询详细报表”时，前端拦截该事件，验证权限后发起新的 API 请求（如调用 `/api/external/reports/sales`）；点击“查看详情 -> 跳转至外部系统”时，触发 SSO Deep Link 跳转（在新标签页或嵌入浮窗 iframe 中打开）。

### 5.2 频道/多端显示方式（Channel Adapter for Rich Messages）
当对话通过企业微信、钉钉、Slack 等频道发送时，需将标准 Card JSON 转换为各平台原生的富消息格式：

- **企业微信 / 钉钉**：
  - 企微支持 Markdown 卡片和图文卡片。后端可将 `summary` 转化为 Markdown 文本，并将 `actions` 映射为企微的“菜单按钮”或“跳转链接”。
  - 钉钉支持 ActionCard（操作卡片）和 FeedCard（信息流卡片）。后端需将 Card JSON 转换为钉钉 API 要求的 `action_card` 或 `link_card` 格式。
- **Slack / Teams**：
  - Slack 使用 Block Kit 格式。后端可将 Card JSON 映射为 `section`、`actions` (button elements) 等 Block 结构。
  - Microsoft Teams 支持 Adaptive Cards。后端将标准 Card JSON 转换为 Adaptive Cards JSON Schema，通过 Teams Bot API 发送。

---

## 六、 安全与体验保障

### 1. 权限校验（防越权）
所有通过 LLM 触发的外部系统 API 调用或卡片渲染指令，必须经过后端的 `@require_permission` 装饰器验证，确保当前用户有权限访问该数据或执行对应操作。

### 2. XSS / CSRF 防护（链接白名单校验）
前端在解析 LLM 返回的“链接 URL”或“deep_link”时，必须进行域名白名单校验（如仅允许内部域名 `*.coapis.com` 或已信任的外部系统域名 `*.oa-system.com`），防止恶意链接注入导致 XSS 或 CSRF 攻击。

### 3. 用户确认机制
对于涉及外部系统的“唤醒/执行操作”（如提交审批、删除数据），UI 卡片上应提供“确认/取消”按钮，LLM 在生成卡片时应明确提示用户操作后果（例如：“点击【确认发起】后将在 OA 系统中创建审批单”）。

---

## 七、 实施步骤与里程碑

### Phase 1：后端协议与工具设计（预计 3-5 个工作日）
- 定义标准交互卡片 JSON Schema（`interactive_card` protocol）。
- 在 MCP Gateway / Builtin Tools 中增加外部系统数据查询 Tool（如 `query_external_data`）。
- 实现 SSO Deep Link 生成 API（`/api/external/generate_deep_link`）。

### Phase 2：前端 Web 对话界面富消息渲染（预计 3-5 个工作日）
- 开发 `InteractiveCard.tsx` 组件，支持标题、摘要展示与多按钮布局。
- 增强前端消息解析引擎，识别并渲染 `interactive_card` JSON 结构。
- 实现按钮事件绑定与安全跳转逻辑（含 SSO Token 传递）。

### Phase 3：多端频道适配器开发（预计 5-7 个工作日）
- 实现企业微信 / 钉钉富消息/卡片格式的转换适配逻辑。
- 实现 Slack Block Kit / Teams Adaptive Cards 的转换适配逻辑。
- 联调测试各频道的卡片渲染与按钮点击事件。

### Phase 4：安全验证与体验优化（预计 2-3 个工作日）
- 实施权限校验拦截与链接白名单校验机制。
- 优化 LLM Prompt，确保 Tool Calling 生成结构化 Card JSON 的准确率。
- 用户确认机制 UI 完善（针对高风险操作增加二次确认卡片）。

---

## 八、 总结

以 AI 为底座集成外部系统并显示入口按钮/查看详情链接的技术可行性**极高**。通过 **LLM Structured Output / Tool Calling + 后端标准 Card JSON 协议 + 前端 Rich Message 组件渲染 + SSO Deep Linking**，完全可以实现流畅、安全且具备业务价值的“对话即操作（Chat-to-Action）”体验。

本方案为 CoApis 平台提供了完整的技术路径与实施框架，可作为企业级 AI Agent 集成外部业务系统的标准参考文档。