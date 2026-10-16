# CoApis C2A (Chat-to-Action) Protocol & SDK

## 概述

**CoApis C2A** 是一个独立的协议与 SDK 项目，提供 **Chat-to-Action (C2A)** 交互式消息协议的标准化实现。该协议桥接了 LLM Agent 输出与交互式用户界面渲染引擎之间的差距，使 AI 智能体能够生成结构化的 UI 指令（如数据表格、操作按钮、表单等），并在 Web Chat、企业微信、钉钉、Slack 等多端环境中统一渲染与执行。

本项目作为 CoApis 产品的独立依赖模块，提供：
- **核心协议定义**：JSON Schema 校验与数据类型模型。
- **Python SDK**：用于后端 LLM Agent 生成与验证 C2A 消息。
- **TypeScript/React UI 组件库**：用于前端 Web Chat 界面的富媒体渲染。
- **企业频道适配器**：将 C2A 协议转换为企微、钉钉、Slack 等平台的富媒体卡片格式。

---

## 项目结构

```
coapis-c2a/
├── schemas/                      # JSON Schema 校验文件
│   └── c2a-message-v1.jsonschema
│
├── python/                       # Python SDK
│   ├── c2a_protocol/             # 核心协议模型与验证器
│   │   ├── pyproject.toml
│   │   └── src/c2a_protocol/
│   │       ├── __init__.py
│   │       ├── models.py
│   │       └── validator.py
│   └── c2a_adapters/             # 企业频道适配器 (WeCom, DingTalk, Slack)
│       ├── pyproject.toml
│       └── src/c2a_adapters/
│           ├── __init__.py
│           ├── wecom.py
│           ├── dingtalk.py
│           └── slack.py
│
├── typescript/                   # TypeScript/React 前端组件库
│   ├── c2a-core-types/           # TypeScript 类型定义与 Schema 校验工具
│   │   ├── package.json
│   │   └── src/index.ts
│   └── c2a-renderer-react/       # React 渲染组件库
│       ├── package.json
│       └── src/
│           ├── types.ts
│           └── C2ARenderer.tsx
│
└── README.md
```

---

## CoApis 产品依赖方式

### 后端 (Python) - `server/coapis`
在 CoApis 后端服务中，通过安装 `c2a_protocol` 和 `c2a_adapters` 模块来生成与转换 C2A 消息：

```bash
# 安装核心协议与适配器
pip install ./python/c2a_protocol
pip install ./python/c2a_adapters
```

### 前端 (TypeScript/React) - `client`
在 CoApis 前端服务中，通过引入 `@coapis/c2a-core-types` 和 `@coapis/c2a-renderer-react` 来渲染 C2A 消息：

```bash
# 安装 TypeScript 类型与 React 组件库
npm install @coapis/c2a-core-types
npm install @coapis/c2a-renderer-react
```

---

## 协议标准文档

完整的 C2A 协议技术白皮书与实施计划请参考：
- [C2A 交互式消息协议标准 v1.0](./tech_docs/design/C2A_INTERACTIVE_MESSAGE_PROTOCOL_STANDARD.md)
- [企业频道适配与 UI 组件库实施计划](./tech_docs/design/C2A_IMPLEMENTATION_ROADMAP_AND_ADAPTERS.md)

---

## License

Apache-2.0
