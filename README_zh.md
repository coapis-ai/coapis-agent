<div align="center">

# CoApis

[![GitHub Stars](https://img.shields.io/github/stars/coapis-ai/coapis-agent?style=social)](https://github.com/coapis-ai/coapis-agent)
[![GitHub Forks](https://img.shields.io/github/forks/coapis-ai/coapis-agent?style=social)](https://github.com/coapis-ai/coapis-agent)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Version](https://img.shields.io/badge/Version-0.11.0-green.svg)](https://github.com/coapis-ai/coapis-agent/releases)
[![Docker Pulls](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://github.com/coapis-ai/coapis-agent/pkgs/container/server)
[![Contributors](https://img.shields.io/badge/Contributors-Welcome-orange.svg)](CONTRIBUTING.md)

**中文** | [English](./README.md)

<img src="https://img.icons8.com/color/96/bee.png" alt="CoApis Logo" width="120">

# 企业级 Agent Harness 平台

> 统一编排、安全治理、持续进化
> 
> 让团队 AI 能力协同倍增

[官网](https://coapis.cn) · [文档](https://coapis.cn/docs) · [快速开始](#-快速开始)

---

</div>

## 📊 核心数据

| 🎯 **丰富** | 🔒 **7层** | 📈 **50%-75%** | 🏢 **多用户** |
|------------|----------|---------------|-------------|
| 工具和业务场景 | 安全纵深防护 | 效率提升 | 独立空间协作 |

---

## 🎯 CoApis 是什么？

**CoApis 是企业的智能体管家。**

不只是单个 AI 助手，而是管理、编排、治理多个智能体的企业级平台。

---

## 💎 核心价值

| 特色 | 说明 | 价值 |
|------|------|------|
| 🤝 **群体智能** | 多智能体协同，经验共享 | 1+1>2 的协作效果 |
| 🧠 **持续进化** | 越用越聪明，技能自动沉淀 | 降低重复劳动 |
| 🛡️ **安全可控** | 七层防护，全程审计 | 企业级安全保障 |
| 🚀 **零门槛** | 浏览器即用，无需技术背景 | 全员可用 |

**🌟 越用越聪明** - 智能体会记住你的习惯、项目背景、客户偏好，自动沉淀可复用技能

---

## 🆚 核心差异

**不是单个 AI 助手**，而是管理多个智能体的平台

**不是开发框架**，而是开箱即用的产品

**不是应用平台**，而是编排治理框架

**CoApis = Agent Harness = 智能体的编排与治理平台**

---

## 🏗️ 核心能力架构

**四大支柱**

### 🎭 Orchestration - 智能编排

- 多智能体全生命周期管理
- 场景智能体 + 用户智能体组合
- 工作流编排与调度
- 智能体协作与协同

### 🔧 Harness - 工具支撑

- 丰富的工具和业务场景
- 统一 LLM 接入（OpenAI、Claude、通义千问等）
- 支持 MCP 协议
- 可扩展的工具生态

### 🧠 Evolution - 持续进化

- 多层记忆体系
- 自动沉淀可复用模式为技能
- 知识积累与共享
- 持续学习与改进

### 🛡️ Governance - 安全治理

- 七层安全纵深防护
- 权限与配额管理
- 全程审计追溯与合规
- 企业级可靠性保障

---

## 🚀 快速开始

### 一键安装（推荐 ⭐）

```bash
# 默认版本
curl -fsSL https://raw.githubusercontent.com/coapis-ai/coapis-agent/main/install.sh | bash

# 访问：http://<server-ip>:4208
# 账号：admin / admin123
```

### Docker 部署

```bash
export COAPIS_IMAGE=ghcr.io/coapis-ai/coapis-agent/server:v0.11.0
wget https://raw.githubusercontent.com/coapis-ai/coapis-agent/main/docker-compose.yml
docker compose up -d
```

📖 **详细安装指南**：[安装文档](https://coapis.cn/docs/#/help/install) · [源码构建](./docs/SOURCE_INSTALL_MANUAL.md)

---

## 💼 适用场景

**赋能企业、单位、组织、团队** - 覆盖文档处理、数据分析、知识管理等核心需求

**行业验证**：环境咨询（效率提升 75%）、科研院所（效率提升 60%）、法律服务等领域

📖 **了解更多场景**：[官网](https://coapis.cn)

---

## 📚 文档

- **官网**：[coapis.cn](https://coapis.cn) - 产品介绍、在线体验
- **快速入门**：[30秒上手指南](https://coapis.cn/docs/#/help/guide)
- **安装部署**：[Docker 部署、源码安装](https://coapis.cn/docs/#/help/install)
- **配置指南**：[环境变量、模型配置](https://coapis.cn/docs/#/help/config)

---

## 🤝 参与贡献

欢迎贡献代码、文档、Bug 报告！

请参阅 [CONTRIBUTING.md](CONTRIBUTING.md) 了解详情。

---

## 🌟 Star History

[![Star History Chart](https://api.star-history.com/svg?repos=coapis-ai/coapis-agent&type=Date)](https://star-history.com/#coapis-ai/coapis-agent&Date)

---

## 💬 社区

- **官网**：[coapis.cn](https://coapis.cn)
- **GitHub**：[coapis-ai/coapis-agent](https://github.com/coapis-ai/coapis-agent)
- **Gitee**：[ouerlai/coapis-agent](https://gitee.com/ouerlai/coapis-agent)（国内用户推荐）
- **Discussions**：[GitHub Discussions](https://github.com/coapis-ai/coapis-agent/discussions)

---

## 🙏 特别鸣谢

前端聊天组件基于 [agentscope-ai](https://github.com/modelscope/agentscope) 项目构建，感谢阿里巴巴达摩院 ModelScope 团队的开源贡献。

---

## 📄 许可证

Apache License 2.0 · Copyright 2026 蜜蜂 & CoApis Contributors

---

<div align="center">

**为什么叫 CoApis？**

**Co**（协作）+ **Apis**（拉丁语"蜜蜂"）

寓意蜂群式的团队协作，构建企业级 AI Agent Harness

**如果你觉得 CoApis 有用，请给我们一个 ⭐ Star！**

</div>
