<div align="center">

# CoApis

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/Version-0.9.11-green.svg)](CHANGELOG.md)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://hub.docker.com/r/coapis/server)

**中文** | [English](./README_en.md)

<img src="https://img.icons8.com/color/96/bee.png" alt="CoApis Logo" width="120">

# 企业级 AI Agent Harness 平台

> 让企业安全、可控地部署和管理 AI 智能体，为全团队提供 AI 能力

[官网](https://coapis.cn) · [什么是 Harness](#-什么是-ai-agent-harness) · [快速开始](#-快速开始)

---

</div>

## 🎯 什么是 AI Agent Harness？

**Harness**（驾驭系统）是为 AI 智能体提供运行基础设施的框架：

- **运行环境** — 让 Agent 在服务器端持续运行
- **工具能力** — 提供 Shell、浏览器、文档处理等工具
- **记忆系统** — 管理上下文、沉淀经验
- **安全边界** — 约束 Agent 行为，防止危险操作
- **监控审计** — 追踪所有操作，确保合规

**CoApis 就是企业级 Harness** — 一套部署，全团队可用，每人独立空间。

---

## 🏆 核心价值

### 企业装一套，全体可用

IT 部门部署一次，全团队立即开始使用。无需每个人都懂 AI、懂部署。

### 服务端常驻运行

Agent 在服务器端 7×24 小时运行。关掉浏览器，任务继续执行。

### 多用户协作，独立空间

团队成员共享智能体基础设施，但每人有独立的工作空间——对话、文件、记忆，互不可见。

### 智能体持续进化

Agent 记住你的偏好，自动识别可复用模式，沉淀为技能。用得越多，越懂你。

### 企业级安全与审计

完整的数据隔离、权限控制、危险操作审批、审计日志追溯。

---

## 🏗️ 适用场景

| 场景 | 说明 |
|------|------|
| **研发团队** | 代码审查、文档生成、技术调研、自动化测试 |
| **运营团队** | 数据分析、内容创作、自动化流程、报告生成 |
| **客服团队** | 知识库问答、工单处理、话术建议、情绪分析 |
| **行政团队** | 会议纪要、邮件起草、日程管理、合同审查 |

---

## 🚀 快速开始

### Docker 部署（推荐）

```bash
mkdir -p /opt/coapis && cd /opt/coapis
wget https://raw.githubusercontent.com/coapis/coapis/main/docker-compose.yml
wget https://raw.githubusercontent.com/coapis/coapis/main/.env.example -O .env
nano .env  # 填写 LLM API Key
docker compose up -d
```

### 访问服务

- 地址：`http://<server-ip>:4200`
- 账号：`admin` / `admin123`
- ⚠️ 首次登录后请立即修改默认密码

### 从源码安装

详见 [源码安装手册](./docs/SOURCE_INSTALL_MANUAL.md)

---

## 💡 为什么选择 CoApis？

### 对于企业管理者

- **成本可控** — 按角色分配 Token 配额，用量透明
- **安全合规** — 数据不离开企业网络，完整审计日志
- **降低门槛** — 无需为每个员工单独购买和配置 AI 工具

### 对于 IT 部门

- **一键部署** — Docker 容器化，5 分钟完成部署
- **权限管理** — 四级角色权限，精细控制访问
- **易于维护** — 统一管理，集中升级

### 对于团队成员

- **开箱即用** — 无需安装客户端，浏览器直接访问
- **个性空间** — 每人独立的对话、文件、记忆
- **持续进化** — Agent 越用越懂你

---

## 🔧 Harness 能力

| 能力 | 说明 |
|------|------|
| **工具系统** | Shell 执行、浏览器自动化、文档处理、网络搜索等 29 个内置工具 |
| **记忆管理** | 多层记忆体系、语义检索、自动沉淀经验 |
| **安全边界** | 命令风险分类、危险操作拦截、沙箱隔离 |
| **约束机制** | RBAC 权限、Token 配额、操作审批 |
| **监控审计** | 完整审计链路、行为监控、日志导出 |

---

## 📚 文档

| 文档 | 说明 |
|------|------|
| [官网](https://coapis.cn) | 产品介绍、版本对比、在线体验 |
| [快速入门](https://coapis.cn/docs/#/help/guide) | 30 秒上手指南 |
| [安装部署](https://coapis.cn/docs/#/help/install) | Docker 部署、源码安装 |
| [配置指南](https://coapis.cn/docs/#/help/config) | 环境变量、模型配置 |
| [使用说明](https://coapis.cn/docs/#/help/direction) | 功能模块详解 |
| [常见问题](https://coapis.cn/docs/#/help/faq) | 安装、配置、使用 FAQ |
| [源码安装手册](./docs/SOURCE_INSTALL_MANUAL.md) | 从源码编译部署 |
| [二次开发指南](./docs/developer/二次开发指南.md) | 开发者必读 |

---

## 🗺️ 路线图

- 🏗️ Docker 非 root 运行
- 💬 群聊模式
- 🧠 上下文智能压缩
- 🛒 技能市场

---

## 参与贡献

欢迎贡献代码、文档、Bug 报告。请参阅 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 社区

| 渠道 | 链接 |
|------|------|
| 官网 | [coapis.cn](https://coapis.cn) |
| Gitee | [ouerlai/coapis-agent](https://gitee.com/ouerlai/coapis-agent) |
| GitHub | [coapis-ai/coapis-agent](https://github.com/coapis-ai/coapis-agent) |
| 安全漏洞报告 | [SECURITY.md](SECURITY.md) |

---

## 🙏 特别鸣谢

CoApis 的前端聊天组件基于 [agentscope-ai](https://github.com/modelscope/agentscope) 项目构建，感谢阿里巴巴达摩院 ModelScope 团队的开源贡献。

---

## 许可证

Apache License 2.0 · Copyright 2026 蜜蜂 & CoApis Contributors

---

**为什么叫 CoApis？** — Eater（探索者）+ Claw（爪子）。一只什么都想试、什么都能抓的蜜蜂。🐝
