<div align="center">

# CoApis

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/Docker-GHCR-green)](https://ghcr.io/coapis/server)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue)](https://www.python.org/)
[![React](https://img.shields.io/badge/React-18-blue)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Latest-green)](https://fastapi.tiangolo.com/)
[![i18n](https://img.shields.io/badge/i18n-EN%20%7C%20ZH%20%7C%20JA%20%7C%20RU-orange)](./docs/help/)

**中文** | [English](./README_en.md)

<img src="https://img.icons8.com/color/96/crab.png" alt="CoApis Logo" width="100">

**企业级多用户 AI 协作平台**

> 多用户共享 · 多智能体团队协作 · 56+ 精炼工具 · 四层记忆体系 · 技能进化引擎 · 七层安全纵深
>
> 在服务器端运行和管理多个 AI 智能体，为企业提供安全可控、越用越聪明的 AI 工作空间。

[快速开始](#快速开始) · [核心特性](#核心特性) · [安全特性](#安全特性) · [文档](#文档) · [常见问题](#常见问题)

</div>

---

## 新闻

- [2026-06-13] **v0.8.0 — 七层安全纵深体系** | 系统级安全加固全面落地。

  | 亮点 | 更新内容 |
  |------|----------|
  | **命令风险分类器** | 新增 CommandRiskClassifier，17 种命令类别 × 4 级角色，三级风险分级（自动放行 / 审批确认 / 硬拒绝）。 |
  | **行为监控与自动封禁** | ToolCallMonitor 新增阻断能力，连续危险操作自动封禁。 |
  | **环境变量最小化** | 子进程仅暴露 4 个必要变量，杜绝身份信息泄露。 |
  | **Docker 安全加固** | 资源限制 + 内部网络隔离 + tmpfs 挂载。 |
  | **安全文档套件** | 新增安全加固指南、运维手册、架构开发者指南三份文档。 |

  另有：白名单语义匹配优化、ImportSandbox/ASTSandbox 集成、敏感文件列表补全、审批消息入记忆。[v0.8.0 更新日志 →](./CHANGELOG.md)

- [2026-06-11] **v0.7.1 — 审计日志统一** | 三套审计日志合并为 SQLite 统一存储。

- [2026-06-08] **v0.7.0 — 多级智能体协作** | 主 Agent 调度 + 子 Agent 并行执行 + 跨 Agent 通信。

---

## 导航

> **我是新用户，想快速试用**：[快速开始](#快速开始) → 三条命令跑起来 → [配置模型](#配置模型) → 在控制台对话
>
> **我想接入企业微信 / 钉钉**：完成快速开始 → [频道配置](./docs/help/)
>
> **我想了解安全机制**：[安全特性](#安全特性) → [安全加固指南](./docs/security-hardening-guide.md)
>
> **我是运维，需要排查问题**：[运维操作手册](./docs/ops-security-manual.md)
>
> **我是开发者，想了解架构**：[安全架构指南](./docs/security-architecture.md)
>
> **我不想用 Docker**：[源码安装](#从源码安装)

---

## 与同类产品的区别

CoApis 定位为企业级多用户 AI 协作平台，与常见的单用户 AI 助手有本质区别：

| 维度 | 单用户 AI 助手 | CoApis |
|------|--------------|-----------|
| 部署方式 | 本地客户端，绑定个人电脑 | 服务端常驻，团队共享 |
| 用户规模 | 1 人独享 | 多人同时使用，数据隔离 |
| 使用门槛 | 需要本地安装、配置环境 | 开箱即用，非技术人员也能上手 |
| 记忆能力 | 会话内有效，关闭即丢失 | 四层记忆，跨会话永久保存 |
| 智能体 | 平行多智能体 | 三层智能体体系（全局/用户/智能体），支持机构级多部门团队协作，技能多级进化 |
| 安全防护 | 基础过滤 | 七层纵深防御，完整审计链路 |
| 企业合规 | 无 | RBAC 权限 + 审计日志 + Token 配额 |

---

## 快速开始

### 前置要求

- Docker & Docker Compose
- 任意 OpenAI 兼容的 LLM API（OpenAI / Ollama / vLLM / LM Studio 等）

### 方式一：一键安装（推荐）

```bash
curl -fsSL https://raw.githubusercontent.com/coapis/coapis/main/install.sh | bash
```

### 方式二：手动 Docker 部署

```bash
mkdir -p /opt/coapis && cd /opt/coapis

wget https://raw.githubusercontent.com/coapis/coapis/main/docker-compose.yml
wget https://raw.githubusercontent.com/coapis/coapis/main/.env.example -O .env

nano .env  # 填写 LLM API Key

docker compose up -d
```

> 从源码安装请参考 [从源码安装](#从源码安装) 章节。

### 访问服务

打开浏览器访问 `http://<server-ip>:4200`

- 默认管理员：`admin` / `admin123`
- ⚠️ 首次登录后请立即修改默认密码

---

## 配置模型

首次使用需要配置 LLM API Key，CoApis 支持任意 OpenAI 兼容的 API：

1. 登录后进入 **设置 → 模型**
2. 选择提供商（OpenAI / Ollama / vLLM / LM Studio 等）
3. 填写 API Key 和 Base URL
4. 启用该提供商与模型

也可通过环境变量配置：在 `.env` 文件中设置 `OPENAI_API_KEY`。

> 使用 Ollama / LM Studio 等本地模型时无需 API Key，详见 [配置指南](./docs/CONFIGURATION_zh.md)。

---

## 核心特性

<details>
<summary><b>🏢 企业级多用户</b></summary>

<br>

CoApis 的智能体常驻服务器，7×24 小时在线。用户关掉浏览器后，任务继续跑、记忆不丢失。组织内多名用户共享同一套平台，每人拥有独立的工作空间和 Agent 实例，数据完全隔离。支持跨会话记忆保持和异步执行，定时任务到点自动触发，无需人工盯守。

</details>

<details>
<summary><b>🤖 三层智能体团队协作</b></summary>

<br>

CoApis 采用三层智能体体系：全局智能体 → 用户智能体 → 任务智能体，逐层覆盖、灵活定制。主 Agent 负责理解意图、拆解任务，将子任务分发给专业子 Agent 并行执行，完成后汇总结果统一交付。子 Agent 自动继承父 Agent 的权限边界，确保协作安全可控。支持机构级多部门团队协作，不同部门可共享或隔离智能体资源。

</details>

<details>
<summary><b>🧠 四层记忆体系</b></summary>

<br>

| 记忆层 | 用途 | 生命周期 |
|--------|------|---------|
| `short_term` | 当前对话上下文 | 会话内 |
| `long_term` | 跨会话的用户偏好、经验沉淀 | 永久 |
| `core` | Agent 的核心价值观和思考模式 | 永久 |
| `ephemeral` | 临时数据、中间推理 | 临时 |

Agent 在每次交互中自动提取有价值的信息写入长期记忆。配合语义检索能力，Agent 可以从历史记忆中精准召回相关信息。

</details>

<details>
<summary><b>🌱 技能进化引擎</b></summary>

<br>

Agent 具备自我学习能力，可根据用户需求自动创建新技能，并通过五维指标（精确度、可靠性、有效率、满意度、稳健性）持续评估技能质量。达标技能自动晋升，低效技能自动淘汰。一个 Agent 验证有效的技能可推广给其他 Agent。技能体系分为全局、用户、智能体三级，逐层覆盖。

</details>

<details>
<summary><b>🌐 多语言 & 多渠道</b></summary>

<br>

**界面语言：** 中文 · English · 日本語 · Русский（右上角一键切换）

**接入渠道：** 企业微信 · 钉钉 · Slack · Telegram · Webhook

</details>

<details>
<summary><b>🛠️ 56+ 精炼工具</b></summary>

<br>

CoApis 从早期 108+ 工具出发，经过深度合并优化，精炼为 56+ 个高频实用工具，覆盖文件操作、Shell 执行、浏览器自动化、文档处理、多媒体分析、网络搜索、邮件管理、记忆检索、智能体协作、安全审计等场景。所有工具均受七层安全防护保护。

</details>

<details>
<summary><b>🏗️ 企业级能力</b></summary>

<br>

四级 RBAC 权限（guest → user → advanced → admin）、按等级分配的月度 Token 配额、积分激励体系、完整审计日志（支持按用户/事件类型/风险等级查询）、文件版本管理与 409 冲突保护、Cron 定时任务、一键备份恢复。

</details>

---

## 安全特性

CoApis 内置七层纵深防御架构，从工作区守卫到审计合规，每层独立拦截、层层互补：

- **命令风险分类** — 17 种命令类别 × 4 级角色权限，危险命令弹窗审批或直接拒绝
- **行为监控与自动封禁** — 连续危险操作自动封禁，冷却期防误判
- **沙箱隔离** — 进程隔离、namespace 挂载隔离、CPU/内存资源限制
- **环境变量最小化** — 子进程仅暴露 4 个必要变量
- **工具防护引擎** — 29 条 YAML 规则、65 个敏感文件路径保护
- **完整审计链路** — 所有操作（含被拒绝的）写入 SQLite，可追溯、可导出
- **Docker 安全加固** — 资源限制 + 内部网络隔离 + tmpfs 挂载

详见 [安全加固指南](./docs/security-hardening-guide.md) · [安全架构指南](./docs/security-architecture.md) · [运维操作手册](./docs/ops-security-manual.md)

---

## 常见问题

更多常见问题和故障排查，请访问 [帮助文档 · 常见问题](./docs/help/05-常见问题.md)。

---

## 文档

| 主题 | 说明 |
|------|------|
| [帮助文档](./docs/help/) | 产品文档（安装、配置、模块帮助、常见问题） |
| [安全加固指南](./docs/security-hardening-guide.md) | P0-P3 安全加固总览、环境变量参考、FAQ |
| [安全架构指南](./docs/security-architecture.md) | 七层架构、执行链路、扩展指南 |
| [运维操作手册](./docs/ops-security-manual.md) | 白名单维护、封禁处理、告警排查 |
| [部署指南](./docs/DEPLOYMENT_zh.md) | 生产环境部署 |
| [API 参考](./docs/API-REFERENCE_zh.md) | API 接口文档 |
| [配置指南](./docs/CONFIGURATION_zh.md) | 环境变量、Agent 配置详解 |

完整文档见本仓库 [docs/](./docs/) 目录。

---

## 路线图

| 方向 | 事项 | 状态 |
|------|------|------|
| **安全加固** | Docker 非 root 运行 | 计划中 |
| **安全加固** | 内核级 seccomp/AppArmor 沙箱 | 计划中 |
| **智能体协作** | 群聊模式 | 计划中 |
| **智能体协作** | HiClaw 企业级能力 | 计划中 |
| **技能生态** | 技能市场（ClawHub 风格） | 征集中 |
| **频道扩展** | 飞书、QQ 频道 | 征集中 |
| **Coding 能力** | LSP、工作区版本控制 | 计划中 |
| **上下文管理** | 上下文智能压缩 | 进行中 |

_状态说明：**进行中** — 正在积极开发；**计划中** — 已排队或设计中；**征集中** — 欢迎社区参与。_

---

## 版本策略

| 版本 | 定位 | 许可证 |
|------|------|--------|
| CE (社区版) | 开源免费 | Apache 2.0 |
| EE (企业版) | 商业增强 | Commercial License |
| CD (云版) | SaaS 服务 | Subscription |

---

## 从源码安装

```bash
git clone https://github.com/coapis/coapis.git
cd coapis

# 安装前端依赖并构建
cd client && npm ci && npm run build && cd ..

# 配置环境变量
cp docker/.env.example docker/.env
# 编辑 docker/.env 填写 API Key

# 从源码构建并启动
docker compose -f docker/docker-compose.build.yml up -d --build
```

- **开发模式**（测试、格式化）：参照 [CONTRIBUTING.md](CONTRIBUTING.md) 安装开发依赖
- **版本更新**：`git pull` 后重新构建前端、重启服务

> **注意**：快速开始中的"方式三"已合并至此处，避免维护两份相同内容。

---

## 参与贡献

欢迎贡献代码、文档、Bug 报告等。请参阅 [CONTRIBUTING.md](CONTRIBUTING.md) 了解详细的贡献流程。

## 社区

| 渠道 | 链接 |
|------|------|
| Gitee | [ouerlai/coapis](https://gitee.com/ouerlai/coapis) |
| GitHub | [coapis/coapis](https://github.com/coapis/coapis) |
| 安全漏洞报告 | [SECURITY.md](SECURITY.md) |

---

## 为什么叫 CoApis？

CoApis — Eater（吃货/探索者）+ Claw（爪子）。一只什么都想试试、什么都能抓得住的螃蟹，是你的 AI 工作伙伴。

---

## 许可证

Copyright 2026 以太吃虾 & CoApis Contributors

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

---

</div>
