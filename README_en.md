<div align="center">

# CoApis

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/Version-0.9.11-green.svg)](CHANGELOG.md)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://hub.docker.com/r/coapis/server)

[中文](./README.md) | **English**

<img src="https://img.icons8.com/color/96/bee.png" alt="CoApis Logo" width="120">

# Enterprise AI Agent Harness Platform

> **Agent = Model + Harness**<br>Deploy and manage AI agents securely for your entire team

[Website](https://coapis.cn) · [Harness 4-Layer Architecture](#-harness-4-layer-architecture) · [Quick Start](#-quick-start)

---

</div>

## 🎯 What is AI Agent Harness?

**Harness = Everything Outside the Model**

Equip the AI model "wild horse" with a complete set of gear — tools, connections, environment, control — to make it controllable, usable, and productive.

### Why Does Harness Matter?

**80% of the performance gap is in the Harness, not the model**

The same model with good vs. poor Harness implementation can mean:
- "Stalls after 3 steps" vs. "Runs continuously for 8 hours completing a feature module"
- "Frequently erratic" vs. "Smooth and reliable"

---

## 🏗️ Harness 4-Layer Architecture

### Layer 1: Capability Layer (Skills / Tools)

**Solves "What can the agent do?"**

| Capability | Description |
|------------|-------------|
| File Operations | Read/write, edit, search |
| Shell Execution | Command execution, environment management |
| Browser Automation | Web scraping, form filling |
| Document Processing | PDF, Word, Excel, PPT |
| Web Search | Tavily, Exa search engines |
| Email Management | IMAP/SMTP send/receive |

**CoApis provides 29 built-in tools + custom skill system**

### Layer 2: Connection Layer (API / MCP)

**Solves "How does the agent talk to the outside world?"**

- Multi-channel integration (WeCom, DingTalk, Feishu, Telegram, Discord, QQ)
- API interface standards
- MCP (Model Context Protocol) support

### Layer 3: Build Layer (Prompt / SDK / Framework)

**Solves "How is the agent built and organized?"**

- Agent configuration system (roles, styles, security boundaries)
- Prompt template management
- Task orchestration logic
- Multi-agent collaboration framework

### Layer 4: Runtime Control Layer ⭐

**Solves "How does the agent run stably, long-term, and controllably?"**

| Capability | Description |
|------------|-------------|
| **Execution Environment** | Docker sandbox isolation, secure runtime |
| **State & Memory** | Multi-layer memory system, automatic experience accumulation |
| **Execution Control** | Retry, throttling, monitoring, auto-evaluation |
| **Security Boundaries** | Seven-layer defense, command classification |
| **Observability** | Complete audit trail, trace recording, replay debugging |

**This layer is the core of Harness, and CoApis' strength**

---

## 🏆 Core Value

### One Deployment, Team-Wide Access

IT deploys once, the entire team starts using immediately. No need for everyone to understand AI, deployment, or configuration.

### Server-Side Resident Operation

Agents run 7×24 on the server. Close your browser, tasks continue executing; scheduled tasks trigger automatically.

### Multi-User Collaboration, Independent Spaces

Team members share agent infrastructure, but each person has their own workspace — conversations, files, and memory are isolated.

### Enterprise-Grade Harness Engineering

Complete runtime control layer: execution environment, state memory, security boundaries, observability — enabling agents to run stably, long-term, and controllably.

---

## 🏗️ Use Cases

| Scenario | Description |
|----------|-------------|
| **R&D Teams** | Code review, documentation, technical research, automated testing |
| **Operations Teams** | Data analysis, content creation, automated workflows, report generation |
| **Customer Service Teams** | Knowledge base Q&A, ticket processing, response suggestions, sentiment analysis |
| **Administrative Teams** | Meeting notes, email drafting, schedule management, contract review |

---

## 🚀 Quick Start

### Docker Deploy (Recommended)

```bash
mkdir -p /opt/coapis && cd /opt/coapis
wget https://raw.githubusercontent.com/coapis/coapis/main/docker-compose.yml
wget https://raw.githubusercontent.com/coapis/coapis/main/.env.example -O .env
nano .env  # Fill in your LLM API Key
docker compose up -d
```

### Access the Service

- URL: `http://<server-ip>:4200`
- Account: `admin` / `admin123`
- ⚠️ Change the default password immediately after first login

### Install from Source

See [Source Install Manual](./docs/SOURCE_INSTALL_MANUAL.md)

---

## 💡 Why Choose CoApis?

### For Enterprise Managers

- **Controlled Costs** — Token quota allocation by role, transparent usage
- **Security & Compliance** — Data never leaves enterprise network, complete audit trail
- **Lower Barriers** — No need to purchase and configure AI tools for each employee

### For IT Departments

- **One-Click Deployment** — Docker containerized, complete in 5 minutes
- **Permission Management** — Four-level role permissions, fine-grained access control
- **Easy Maintenance** — Unified management, centralized upgrades

### For Team Members

- **Ready to Use** — No client installation, access directly via browser
- **Personal Space** — Independent conversations, files, and memory for each person
- **Continuous Evolution** — Agents get better the more you use them

---

## 📚 Documentation

| Document | Description |
|----------|-------------|
| [Website](https://coapis.cn) | Product overview, edition comparison, online demo |
| [Quick Start](https://coapis.cn/docs/#/help/guide) | 30-second guide |
| [Installation](https://coapis.cn/docs/#/help/install) | Docker deploy, source installation |
| [Configuration](https://coapis.cn/docs/#/help/config) | Environment variables, model configuration |
| [User Guide](https://coapis.cn/docs/#/help/direction) | Feature module details |
| [FAQ](https://coapis.cn/docs/#/help/faq) | Installation, configuration, usage FAQ |
| [Source Install Manual](./docs/SOURCE_INSTALL_MANUAL.md) | Build from source |
| [Developer Guide](./docs/developer/二次开发指南.md) | For developers |

---

## 🗺️ Roadmap

- 🏗️ Docker non-root execution
- 💬 Group chat mode
- 🧠 Smart context compression
- 🛒 Skill marketplace

---

## Contributing

Contributions welcome — code, docs, bug reports. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Community

| Channel | Link |
|---------|------|
| Website | [coapis.cn](https://coapis.cn) |
| Gitee | [ouerlai/coapis-agent](https://gitee.com/ouerlai/coapis-agent) |
| GitHub | [coapis-ai/coapis-agent](https://github.com/coapis-ai/coapis-agent) |
| Security | [SECURITY.md](SECURITY.md) |

---

## 🙏 Acknowledgments

CoApis frontend chat components are built on [agentscope-ai](https://github.com/modelscope/agentscope). Special thanks to the Alibaba DAMO Academy ModelScope team for their open-source contribution.

---

## License

Apache License 2.0 · Copyright 2026 蜜蜂 & CoApis Contributors

---

**Why "CoApis"?** — Eater (explorer) + Claw (grip). A bee that tries everything and grabs anything. 🐝
