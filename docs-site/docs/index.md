---
outline: deep
---

# Chat-to-Action (C2A) 交互式消息协议

**CoApis C2A** 是一个独立的协议与 SDK 项目，提供 **Chat-to-Action (C2A)** 交互式消息协议的标准化实现。该协议桥接了 LLM Agent 输出与交互式用户界面渲染引擎之间的差距，使 AI 智能体能够生成结构化的 UI 指令（如数据表格、操作按钮、表单等），并在 Web Chat、企业微信、钉钉、Slack 等多端环境中统一渲染与执行。

## 🌟 核心特性

- **协议标准化**：JSON Schema 校验与数据类型模型，确保消息格式一致性
- **多语言 SDK**：Python SDK（后端生成与验证）+ TypeScript/React UI 组件库（前端渲染）
- **企业频道适配**：将 C2A 协议转换为企微、钉钉、Slack 等平台的富媒体卡片格式
- **状态机驱动**：支持 `idle`, `generating`, `rendered`, `interactive`, `executing`, `completed`, `failed` 完整生命周期

## 📦 项目结构

```
coapis-c2a/
├── schemas/                      # JSON Schema 校验文件
│   └── c2a-message-v1.jsonschema
│
├── python/                       # Python SDK
│   ├── c2a_protocol/             # 核心协议模型与验证器
│   └── c2a_adapters/             # 企业频道适配器 (WeCom, DingTalk, Slack)
│
├── typescript/                   # TypeScript/React UI 组件库
│   ├── c2a-core-types/           # TypeScript 类型定义与 Schema 校验工具
│   └── c2a-renderer-react/       # React 渲染组件库
│
└── docs-site/                    # VitePress 文档站点
```

## 🚀 快速开始

### 后端 (Python) - `c2a_protocol` & `c2a_adapters`

```bash
# 安装核心协议与适配器
pip install c2a-protocol
pip install c2a-adapters
```

### 前端 (TypeScript/React) - `@coapis/c2a-core-types` & `@coapis/c2a-renderer-react`

```bash
# 安装 TypeScript 类型与 React 组件库
npm install @coapis/c2a-core-types
npm install @coapis/c2a-renderer-react
```

## 📚 文档导航

- [API Reference](/api/reference) - 协议规范与数据模型定义
- [Integration Guide](/integration/guide) - 集成指南与示例代码
- [Enterprise Channels](/integration/channels) - 企业频道适配说明

---

*License: Apache-2.0 | © 2024 CoApis Architecture Team*
