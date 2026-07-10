<div align="center">

# CoApis

[![License](https://img.shields.io/badge/License-AGPL%203.0-red.svg)](LICENSE)
[![Version](https://img.shields.io/badge/Version-0.9.11-green.svg)](CHANGELOG.md)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://hub.docker.com/r/coapis/server)

**中文** | [English](./README_en.md)

<img src="https://img.icons8.com/color/96/bee.png" alt="CoApis Logo" width="120">

# 企业级智能体平台

> 一套部署，全团队可用

[官网](https://coapis.cn) · [快速开始](#-快速开始)

---

</div>

## 🎯 核心价值

### 企业装一套，全体可用

IT 部门部署一次，全团队立即开始使用。无需每个人都懂配置、懂部署。

### 服务端常驻运行

智能体在服务器端 7×24 小时运行。关掉浏览器，任务继续执行；定时任务到点自动触发。

### 多用户协作，独立空间

团队成员共享智能体，但每人有独立的工作空间——对话、文件、记忆，互不可见。

### 自动学习，持续进化

智能体会记住你的偏好和习惯，自动识别可复用的模式，沉淀为技能。用得越多，越懂你。

---

## 🏗️ 核心能力架构

### 工具能力

智能体能做什么。提供文件操作、Shell 执行、浏览器自动化、文档处理、网络搜索等工具，自动识别可复用模式并沉淀为技能。

### 连接能力

智能体怎么连接外部系统。通过 API、MCP（Model Context Protocol）等标准协议集成企业现有系统，打通数据和工作流。

### 编排能力

智能体怎么组织和协作。配置角色、风格、安全边界；编排多智能体协同流程；沉淀知识、持续进化、跨智能体共享经验。

### 管控能力

智能体怎么稳定运转。完整的执行环境、多层记忆体系、安全边界、审计追溯——让智能体长期、可控地运行。

**这是核心能力**

---

## 🚀 快速开始

### Docker 部署

```bash
# 只下载 docker 目录
git clone --depth 1 --filter=blob:none --sparse \
  https://github.com/coapis-ai/coapis-agent.git && \
  cd coapis-agent && \
  git sparse-checkout set docker && \
  cd docker

# 配置环境变量
cp .env.example .env
nano .env  # 填写 API Key

# 启动服务
docker compose up -d
```

### 访问服务

- 地址：`http://<server-ip>:4200`
- 账号：`admin` / `admin123`
- ⚠️ 请立即修改默认密码

---

## 💡 适用场景

**研发团队** — 代码审查、文档生成、技术调研、自动化测试

**运营团队** — 数据分析、内容创作、自动化流程、报告生成

**客服团队** — 知识库问答、工单处理、话术建议、情绪分析

**行政团队** — 会议纪要、邮件起草、日程管理、合同审查

---

## 💡 为什么选择 CoApis？

### 对于管理者

成本可控（按角色分配配额）、安全合规（数据不离开企业）、降低门槛（无需单独配置）

### 对于 IT 部门

一键部署（5 分钟完成）、权限管理（四级角色）、易于维护（统一管理）

### 对于团队成员

开箱即用（浏览器访问）、个性空间（独立对话和记忆）、持续进化（越用越懂你）

---

## 📚 文档

[官网](https://coapis.cn) — 产品介绍、版本对比、在线体验

[快速入门](https://coapis.cn/docs/#/help/guide) — 30 秒上手

[安装部署](https://coapis.cn/docs/#/help/install) — Docker 部署、源码安装

[配置指南](https://coapis.cn/docs/#/help/config) — 环境变量、模型配置

[源码安装](./docs/SOURCE_INSTALL_MANUAL.md) — 从源码编译

---

## 参与贡献

欢迎贡献代码、文档、Bug 报告。请参阅 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 社区

官网：[coapis.cn](https://coapis.cn)

Gitee：[ouerlai/coapis-agent](https://gitee.com/ouerlai/coapis-agent)

GitHub：[coapis-ai/coapis-agent](https://github.com/coapis-ai/coapis-agent)

---

## 🙏 特别鸣谢

前端聊天组件基于 [agentscope-ai](https://github.com/modelscope/agentscope) 项目构建，感谢阿里巴巴达摩院 ModelScope 团队的开源贡献。

---

## 许可证

GNU Affero General Public License v3.0 · Copyright 2026 蜜蜂 & CoApis Contributors

---

**为什么叫 CoApis？** — Co（协作）-Apis（拉丁语"蜜蜂"）组合，寓意蜂群式的团队协作，构建企业级 AI Agent Harness，体现"企业协作、群体智能、分工进化、全链管控"的理念。🐝
