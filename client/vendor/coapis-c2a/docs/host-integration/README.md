# C2A × coapis-agent 宿主集成说明

C2A 是独立项目（本仓库）。coapis-agent 侧只做最小胶水接入，共 3 个集成点：

## 1. 前端卡片渲染器（React）

- 源文件：[`typescript/c2a-renderer-react/src/C2ACardRenderer.tsx`](../../typescript/c2a-renderer-react/src/C2ACardRenderer.tsx)
- 职责：渲染后端下发的 `type="c2a_protocol"` 消息（text_markdown / data_table + row_actions / suggestions）。
- 接入方式：在 coapis-agent 的 `client/src/pages/Chat/` 下复制一份，通过
  `customCardRenderConfig` 注册到 AgentScopeRuntimeWebUI。
- 注意：本仓库版本已去掉宿主 CSS Module 依赖，改用普通类名（`c2aCard`、`c2aRowActions` 等），
  样式由宿主自行提供。

## 2. 企微通道 C2A 卡片注册（Python）

- 补丁：[`coapis_wecom_dispatcher.patch`](./coapis_wecom_dispatcher.patch)
- 作用于 coapis-agent `server/coapis/app/channels/wecom/cards/dispatcher.py`，
  在 `WecomCardHandler.__init__` 中注册 C2A 扩展卡片（CardKind）。
- 应用：`git apply coapis_wecom_dispatcher.patch`（在 coapis-agent 仓库内）。

## 3. C2A 卡片工具（Python）

- 源文件：[`server/c2a_tools/src/c2a_tools/integrations/card_renderer.py`](../../server/c2a_tools/src/c2a_tools/integrations/card_renderer.py)
- 职责：`c2a_render_card` 工具 —— 解析并验证 C2A payload，发现可渲染方式与交互意图。
- 接入方式：复制到 coapis-agent `server/coapis/agents/tools/` 下，依赖宿主的
  `registry.register_tool`；脱离宿主时注册自动降级为 no-op。

## 解耦原则

coapis-agent 主干不应包含 C2A 业务代码；以上 3 个点均为"宿主侧薄胶水"，
升级 C2A 协议时只需同步本仓库文件，不动 coapis-agent 业务逻辑。
