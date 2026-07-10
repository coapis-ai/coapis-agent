<div align="center">

# CoApis

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/Version-0.9.11-green.svg)](CHANGELOG.md)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://hub.docker.com/r/coapis/server)
[![i18n](https://img.shields.io/badge/i18n-ZH%20%7C%20EN%20%7C%20JA%20%7C%20RU-orange.svg)](#)

**中文** | [English](./README_en.md)

<img src="https://img.icons8.com/color/96/bee.png" alt="CoApis Logo" width="120">

# 企业级多用户 AI 协作平台

> 🚀 **服务端常驻 · 多用户共享 · 多智能体协作 · 越用越聪明**
>
> 在服务器端运行和管理多个 AI 智能体，为企业提供安全可控、持续进化的 AI 工作空间。

[官网](https://coapis.cn) · [核心优势](#-核心优势) · [架构设计](#-架构设计) · [快速开始](#-快速开始)

---

</div>

## 🎯 一句话说清楚

**CoApis = 企业私有化部署的 AI 助手团队**

与 ChatGPT / Claude 等个人工具不同，CoApis 让你：
- 🔒 **数据不出门** — 完全私有化部署，数据留在自己服务器
- 👥 **多人共享** — 团队共用一套 AI 智能体，每人独立工作空间
- 🧠 **越用越聪明** — 四层记忆 + 技能进化，Agent 持续成长
- 🛡️ **企业级安全** — 七层纵深防御 + 完整审计链路

---

## 🏆 核心优势

### 1. 🏢 企业级多用户架构

| 能力 | 说明 |
|------|------|
| **服务端常驻** | Agent 7×24 在线，关掉浏览器任务继续跑 |
| **多用户共享** | 团队成员共享 AI 智能体，独立工作空间 |
| **数据隔离** | 每人独立的 Agent、文件、记忆空间，互不可见 |
| **RBAC 权限** | 四级角色（guest/user/advanced/admin），精细权限控制 |
| **Token 配额** | 按角色分配月度用量，成本可控 |

### 2. 🧠 四层记忆体系 — 真正的"越用越聪明"

| 记忆层 | 用途 | 生命周期 |
|--------|------|---------|
| `short_term` | 当前对话上下文 | 会话内 |
| `long_term` | 跨会话的用户偏好、经验沉淀 | 永久 |
| `core` | Agent 的核心价值观和思考模式 | 永久 |
| `ephemeral` | 临时数据、中间推理 | 临时 |

**关键优势：**
- ✅ Agent 在每次交互中**自动提取有价值信息**写入长期记忆
- ✅ 语义检索能力，从历史记忆中**精准召回**相关信息
- ✅ 用户偏好、工作习惯、项目上下文 — **永不遗忘**

### 3. 🌱 技能进化引擎 — 自我学习的智能体

```
用户需求 → 自动创建技能 → 五维评估 → 晋升/淘汰
    ↑                                        ↓
    └──── 持续优化 ←─────── 使用反馈 ←───────┘
```

**进化机制：**
- 🔄 **自动生成** — Agent 根据用户需求自动创建新技能
- 📊 **五维评估** — 精确度、可靠性、有效率、满意度、稳健性
- ⬆️ **自动晋升** — 高效技能升级到更高层级（全局/用户/智能体）
- ⬇️ **自动淘汰** — 低效技能降级或移除
- 🌐 **跨 Agent 传播** — 一个 Agent 验证有效的技能可推广给其他 Agent

### 4. 🛡️ 七层安全纵深 — 企业级安全防护

```
┌─────────────────────────────────────────────────┐
│  Layer 7: 审计合规    所有操作可追溯、可导出       │
│  Layer 6: Docker 加固  资源限制 + 网络隔离         │
│  Layer 5: 环境最小化   仅暴露 4 个必要变量         │
│  Layer 4: 工具防护     29 条规则 + 65 个敏感路径   │
│  Layer 3: 沙箱隔离     进程隔离 + namespace 挂载   │
│  Layer 2: 行为监控     危险操作自动封禁            │
│  Layer 1: 命令风险分类  17 类命令 × 4 级权限       │
└─────────────────────────────────────────────────┘
```

### 5. 🌐 多语言 & 多渠道

**界面语言：** 中文 · English · 日本語 · Русский（右上角一键切换）

**接入渠道：** 企业微信 · 钉钉 · 飞书 · Telegram · Discord · QQ · 微信

### 6. 🛠️ 29 个精炼工具

从 108+ 工具精炼为 29 个高频实用工具，覆盖：

| 场景 | 工具 |
|------|------|
| 📁 文件操作 | 读写、编辑、搜索、版本管理 |
| 💻 Shell 执行 | 命令执行、环境管理 |
| 🌐 浏览器自动化 | Playwright 集成、网页抓取 |
| 📄 文档处理 | PDF、Word、Excel、PPT 生成与解析 |
| 🔍 网络搜索 | Tavily、Exa 搜索引擎 |
| 📧 邮件管理 | IMAP/SMTP 收发 |
| 🧠 记忆检索 | 语义搜索历史记忆 |
| 🤖 智能体协作 | 跨 Agent 通信、任务分发 |

---

## 🏗️ 架构设计

### 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | React 18 + TypeScript + Ant Design 5 + Vite 5 |
| 后端 | Python 3.11+ + FastAPI + SQLite/JSON |
| 部署 | Docker + Docker Compose + Nginx |
| LLM | 任意 OpenAI 兼容 API（OpenAI / Ollama / vLLM / LM Studio 等） |

### 与同类产品的区别

| 维度 | 个人 AI 助手 (ChatGPT/Claude) | CoApis |
|------|------------------------------|--------|
| 🏠 **部署** | 本地客户端，绑定个人电脑 | 服务端常驻，团队共享 |
| 👥 **用户** | 1 人独享 | 多人同时使用，数据隔离 |
| 🧠 **记忆** | 会话内有效，关闭即丢失 | 四层记忆，跨会话永久保存 |
| 🤖 **智能体** | 单一助手 | 三层体系（全局/用户/智能体），技能进化 |
| 🛡️ **安全** | 基础过滤 | 七层纵深防御，完整审计链路 |
| 🏢 **合规** | 无 | RBAC 权限 + 审计日志 + Token 配额 |
| 🔧 **扩展** | 插件市场 | 自定义技能 + 多渠道接入 |

---

## 🚀 快速开始

### 前置要求

- Docker & Docker Compose
- 任意 OpenAI 兼容的 LLM API（OpenAI / Ollama / vLLM / LM Studio 等）

### 方式一：Docker 部署（推荐）

```bash
mkdir -p /opt/coapis && cd /opt/coapis

wget https://raw.githubusercontent.com/coapis/coapis/main/docker-compose.yml
wget https://raw.githubusercontent.com/coapis/coapis/main/.env.example -O .env

nano .env  # 填写 LLM API Key

docker compose up -d
```

### 方式二：从源码安装

```bash
git clone https://github.com/coapis-ai/coapis-agent.git
cd coapis-agent

# 安装前端依赖并构建
cd client && npm ci && npm run build && cd ..

# 配置环境变量
cp docker/.env.example docker/.env
# 编辑 docker/.env 填写 API Key

# 从源码构建并启动
docker compose -f docker/docker-compose.build.yml up -d --build
```

### 访问服务

打开浏览器访问 `http://<server-ip>:4200`

- 默认管理员：`admin` / `admin123`
- ⚠️ 首次登录后请立即修改默认密码

---

## 📚 文档

| 文档 | 说明 |
|------|------|
| [官网](https://coapis.cn) | 产品介绍、版本对比、在线体验 |
| [快速入门](https://coapis.cn/docs/#/help/guide) | 30 秒上手指南 |
| [安装部署](https://coapis.cn/docs/#/help/install) | Docker 部署、手动部署、源码安装 |
| [配置指南](https://coapis.cn/docs/#/help/config) | 环境变量、Agent 配置、Provider 配置 |
| [使用说明](https://coapis.cn/docs/#/help/direction) | 聊天、频道、工作区、设置模块 |
| [常见问题](https://coapis.cn/docs/#/help/faq) | 安装、配置、使用 FAQ |
| [源码安装手册](./docs/SOURCE_INSTALL_MANUAL.md) | 从源码编译部署详解 |
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
