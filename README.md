<div align="center">

# CoApis

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/Version-0.9.11-green.svg)](CHANGELOG.md)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://hub.docker.com/r/coapis/server)
[![i18n](https://img.shields.io/badge/i18n-ZH%20%7C%20EN%20%7C%20JA%20%7C%20RU-orange.svg)](#)

**中文** | [English](./README_en.md)

<img src="https://img.icons8.com/color/96/bee.png" alt="CoApis Logo" width="120">

# 你的团队，值得拥有自己的 AI 助手

> CoApis 是一个私有化部署的 AI 协作平台。它跑在你自己的服务器上，团队多人共享，数据不出门，越用越聪明。

[它能做什么](#-它能做什么) · [为什么选它](#-为什么选它) · [开始使用](#-开始使用)

</div>

---

## 🤔 它能做什么？

### 团队共享的 AI 助手

不再是每个人自己开 ChatGPT 账号。CoApis 部署在公司服务器上，**所有人共用一套 AI 智能体**，但每个人有自己独立的工作空间——你的对话、你的文件、你的记忆，别人看不到。

Agent 7×24 小时在线。你关掉浏览器，它还在跑。定时任务到点自动触发，不用人盯。

### 真正的"越用越聪明"

普通 AI 助手每次对话都是"失忆"的。CoApis 的智能体有**四层记忆**：

- 它记得你上次聊了什么
- 它知道你的工作习惯和偏好
- 它会从每次交互中学习，自动沉淀经验
- 时间越久，它越懂你

### 自己会长出新技能

Agent 发现你反复做某件事？它会**自动创建一个新技能**来处理。用得好的技能自动升级，用得不好的自动淘汰。一个 Agent 摸索出来的经验，还能分享给其他 Agent。

### 企业级安全

数据**完全留在你自己的服务器**，不会发送到任何第三方。内置七层安全防护——危险操作会弹窗确认，异常行为自动封禁，所有操作都有审计日志可追溯。

### 多渠道接入

不只是网页聊天。CoApis 支持接入**企业微信、钉钉、飞书、Telegram、Discord、QQ** 等多平台，在你日常用的工具里直接和 AI 对话。

### 界面多语言

支持中文、English、日本語、Русский 四种语言界面。

---

## 💡 为什么选它？

| | ChatGPT / Claude 等个人工具 | CoApis |
|--|---------------------------|--------|
| **数据在哪** | 在别人服务器上 | 在你自己的服务器上 |
| **谁能用** | 一个人 | 整个团队 |
| **关掉浏览器** | 对话结束 | Agent 继续工作 |
| **记忆** | 每次重新开始 | 越用越懂你 |
| **安全** | 基础保护 | 七层纵深防御 + 审计日志 |
| **企业合规** | 无 | 权限管理 + 用量配额 |

---

## 🚀 开始使用

### Docker 部署

```bash
mkdir -p /opt/coapis && cd /opt/coapis
wget https://raw.githubusercontent.com/coapis/coapis/main/docker-compose.yml
wget https://raw.githubusercontent.com/coapis/coapis/main/.env.example -O .env
nano .env  # 填写你的 LLM API Key
docker compose up -d
```

### 从源码安装

```bash
git clone https://github.com/coapis/coapis.git
cd coapis
cd client && npm ci && npm run build && cd ..
cp docker/.env.example docker/.env
docker compose -f docker/docker-compose.build.yml up -d --build
```

### 登录

- 地址：`http://你的服务器IP:4200`
- 账号：`admin` / `admin123`
- ⚠️ 请立即修改默认密码

> 📖 详细文档：[帮助中心](./docs/help-html/) · [源码安装手册](./docs/SOURCE_INSTALL_MANUAL.md)

---

## 📚 文档

| 文档 | 说明 |
|------|------|
| [产品介绍](./docs/marketing/01-产品介绍.md) | 这个产品到底是什么 |
| [快速入门](./docs/help-html/01-快速入门.html) | 30 秒上手 |
| [安装部署](./docs/help-html/02-安装部署.html) | 怎么装、怎么跑 |
| [配置指南](./docs/help-html/03-配置指南.html) | 怎么配模型、频道、权限 |
| [源码安装手册](./docs/SOURCE_INSTALL_MANUAL.md) | 从源码编译部署 |
| [二次开发指南](./docs/developer/二次开发指南.md) | 开发者必读 |
| [API 参考](./docs/developer/API参考.md) | 接口文档 |
| [安全机制](./docs/security/sandbox-security-plan.md) | 安全架构详解 |

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
| Gitee | [ouerlai/coapis-agent](https://gitee.com/ouerlai/coapis-agent) |
| GitHub | [coapis/coapis-agent](https://github.com/coapis-ai/coapis-agent) |
| 安全漏洞报告 | [SECURITY.md](SECURITY.md) |

---

## 🙏 特别鸣谢

CoApis 的前端聊天组件基于 [agentscope-ai](https://github.com/modelscope/agentscope) 项目构建，感谢阿里巴巴达摩院 ModelScope 团队的开源贡献。

---

## 许可证

Apache License 2.0 · Copyright 2026 蜜蜂 & CoApis Contributors

---

**为什么叫 CoApis？** — Eater（探索者）+ Claw（爪子）。一只什么都想试、什么都能抓的蜜蜂。🐝
