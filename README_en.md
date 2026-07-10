<div align="center">

# CoApis

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/Version-0.9.11-green.svg)](CHANGELOG.md)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://hub.docker.com/r/coapis/server)

[中文](./README.md) | **English**

<img src="https://img.icons8.com/color/96/bee.png" alt="CoApis Logo" width="120">

# Enterprise Agent Platform

> Deploy once, entire team uses

[Website](https://coapis.cn) · [Quick Start](#-quick-start)

---

</div>

## 🎯 Core Value

### One Deployment, Team-Wide Access

IT deploys once, the entire team starts using immediately. No need for everyone to understand configuration or deployment.

### Server-Side Resident Operation

Agents run 7×24 on the server. Close your browser, tasks continue executing; scheduled tasks trigger automatically.

### Multi-User Collaboration, Independent Spaces

Team members share agents, but each person has their own workspace — conversations, files, and memory are isolated.

### Auto-Learning, Continuous Evolution

Agents remember your preferences and habits, automatically identify reusable patterns, and crystallize them into skills. The more you use it, the better it understands you.

---

## 🏗️ Four-Layer Capabilities

### Layer 1: Tool Capabilities

29 built-in tools for file operations, shell execution, browser automation, document processing, web search, and more.

### Layer 2: Connection Capabilities

Integrate with WeCom, DingTalk, Feishu, Telegram, Discord, QQ, and more — chat directly in your daily tools.

### Layer 3: Build Capabilities

Configure agent roles, styles, and security boundaries; manage prompt templates; orchestrate multi-agent workflows.

### Layer 4: Control Capabilities

Complete execution environment, multi-layer memory system, security boundaries, audit trails — enabling agents to run stably, long-term, and controllably.

**This layer is the core capability**

---

## 🚀 Quick Start

### Docker Deploy

```bash
mkdir -p /opt/coapis && cd /opt/coapis
wget https://raw.githubusercontent.com/coapis/coapis/main/docker-compose.yml
wget https://raw.githubusercontent.com/coapis/coapis/main/.env.example -O .env
nano .env  # Fill in API Key
docker compose up -d
```

### Access Service

- URL: `http://<server-ip>:4200`
- Account: `admin` / `admin123`
- ⚠️ Change default password immediately

---

## 💡 Use Cases

**R&D Teams** — Code review, documentation, technical research, automated testing

**Operations Teams** — Data analysis, content creation, automated workflows, report generation

**Customer Service Teams** — Knowledge base Q&A, ticket processing, response suggestions, sentiment analysis

**Administrative Teams** — Meeting notes, email drafting, schedule management, contract review

---

## 💡 Why Choose CoApis?

### For Managers

Controlled costs (quota allocation by role), security & compliance (data stays in enterprise), lower barriers (no individual configuration needed)

### For IT Departments

One-click deployment (complete in 5 minutes), permission management (four-level roles), easy maintenance (unified management)

### For Team Members

Ready to use (browser access), personal space (independent conversations and memory), continuous evolution (gets better over time)

---

## 📚 Documentation

[Website](https://coapis.cn) — Product overview, edition comparison, online demo

[Quick Start](https://coapis.cn/docs/#/help/guide) — 30-second guide

[Installation](https://coapis.cn/docs/#/help/install) — Docker deploy, source installation

[Configuration](https://coapis.cn/docs/#/help/config) — Environment variables, model configuration

[Source Install](./docs/SOURCE_INSTALL_MANUAL.md) — Build from source

---

## Contributing

Contributions welcome — code, docs, bug reports. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Community

Website: [coapis.cn](https://coapis.cn)

Gitee: [ouerlai/coapis-agent](https://gitee.com/ouerlai/coapis-agent)

GitHub: [coapis-ai/coapis-agent](https://github.com/coapis-ai/coapis-agent)

---

## 🙏 Acknowledgments

Frontend chat components built on [agentscope-ai](https://github.com/modelscope/agentscope). Thanks to Alibaba DAMO Academy ModelScope team.

---

## License

Apache License 2.0 · Copyright 2026 蜜蜂 & CoApis Contributors

---

**Why "CoApis"?** — Eater (explorer) + Claw (grip). A bee that tries everything and grabs anything. 🐝
