<div align="center">

# CoApis

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/Version-0.9.11-green.svg)](CHANGELOG.md)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://hub.docker.com/r/coapis/server)
[![i18n](https://img.shields.io/badge/i18n-ZH%20%7C%20EN%20%7C%20JA%20%7C%20RU-orange.svg)](#)

[中文](./README.md) | **English**

<img src="https://img.icons8.com/color/96/bee.png" alt="CoApis Logo" width="120">

# Enterprise Multi-User AI Collaboration Platform

> 🚀 **Server-side Resident · Multi-user Sharing · Multi-agent Collaboration · Gets Smarter Over Time**
>
> Run and manage multiple AI agents on your server, providing a secure, controllable, and continuously evolving AI workspace for your organization.

[Website](https://coapis.cn) · [Core Advantages](#-core-advantages) · [Architecture](#-architecture-design) · [Quick Start](#-quick-start)

---

</div>

## 🎯 In One Sentence

**CoApis = Your Team's Private AI Assistant Team**

- 🔒 **Data Never Leaves** — Fully self-hosted, data stays on your own server
- 👥 **Team Sharing** — Team members share AI agents, each with independent workspace
- 🧠 **Gets Smarter** — Four-layer memory + skill evolution, agents continuously improve
- 🛡️ **Enterprise Security** — Seven-layer defense + complete audit trail

---

## 🏆 Core Advantages

### 1. 🏢 Enterprise Multi-User Architecture

| Capability | Description |
|------------|-------------|
| **Server-side Resident** | Agents online 7×24, tasks continue even when browser is closed |
| **Multi-user Sharing** | Team members share AI agents with independent workspaces |
| **Data Isolation** | Each user has independent agent, files, and memory space |
| **RBAC Permissions** | Four-level roles (guest/user/advanced/admin), fine-grained control |
| **Token Quota** | Monthly usage allocation by role, cost controllable |

### 2. 🧠 Four-Layer Memory System — Truly "Gets Smarter"

| Memory Layer | Purpose | Lifecycle |
|--------------|---------|-----------|
| `short_term` | Current conversation context | Within session |
| `long_term` | Cross-session preferences, experience沉淀 | Permanent |
| `core` | Agent's core values and thinking patterns | Permanent |
| `ephemeral` | Temporary data, intermediate reasoning | Temporary |

**Key Advantages:**
- ✅ Agent **automatically extracts valuable information** into long-term memory
- ✅ Semantic retrieval, **precisely recalls** relevant information from history
- ✅ User preferences, work habits, project context — **never forgets**

### 3. 🌱 Skill Evolution Engine — Self-Learning Agents

```
User Need → Auto-create Skill → Five-dimensional Assessment → Promote/Retire
    ↑                                        ↓
    └──── Continuous Optimization ←────── Feedback ←───────┘
```

**Evolution Mechanism:**
- 🔄 **Auto-generate** — Agent creates new skills based on user needs
- 📊 **Five-dimensional Assessment** — Precision, reliability, efficiency, satisfaction, robustness
- ⬆️ **Auto-promote** — High-performing skills upgrade to higher levels
- ⬇️ **Auto-retire** — Low-performing skills downgrade or remove
- 🌐 **Cross-Agent Spread** — Proven skills can propagate to other agents

### 4. 🛡️ Seven-Layer Security Defense — Enterprise-Grade Protection

```
┌─────────────────────────────────────────────────┐
│  Layer 7: Audit Compliance  All operations traceable, exportable │
│  Layer 6: Docker Hardening  Resource limits + network isolation  │
│  Layer 5: Environment Minimal  Only 4 necessary variables exposed│
│  Layer 4: Tool Guard  29 rules + 65 sensitive path protections   │
│  Layer 3: Sandbox Isolation  Process isolation + namespace mount │
│  Layer 2: Behavior Monitoring  Dangerous ops auto-banned        │
│  Layer 1: Command Risk Classification  17 categories × 4 levels │
└─────────────────────────────────────────────────┘
```

### 5. 🌐 Multi-Language & Multi-Channel

**Interface Languages:** 中文 · English · 日本語 · Русский (toggle in top-right corner)

**Integration Channels:** WeCom · DingTalk · Feishu · Telegram · Discord · QQ · WeChat

### 6. 🛠️ 29 Refined Tools

Refined from 108+ tools to 29 high-frequency practical tools covering:

| Scenario | Tools |
|----------|-------|
| 📁 File Operations | Read/write, edit, search, version management |
| 💻 Shell Execution | Command execution, environment management |
| 🌐 Browser Automation | Playwright integration, web scraping |
| 📄 Document Processing | PDF, Word, Excel, PPT generation and parsing |
| 🔍 Web Search | Tavily, Exa search engines |
| 📧 Email Management | IMAP/SMTP send/receive |
| 🧠 Memory Retrieval | Semantic search through historical memory |
| 🤖 Agent Collaboration | Cross-agent communication, task distribution |

---

## 🏗️ Architecture Design

### Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | React 18 + TypeScript + Ant Design 5 + Vite 5 |
| Backend | Python 3.11+ + FastAPI + SQLite/JSON |
| Deployment | Docker + Docker Compose + Nginx |
| LLM | Any OpenAI-compatible API (OpenAI / Ollama / vLLM / LM Studio etc.) |

---

## 🚀 Quick Start

### Prerequisites

- Docker & Docker Compose
- Any OpenAI-compatible LLM API (OpenAI / Ollama / vLLM / LM Studio etc.)

### Option 1: Docker Deploy (Recommended)

```bash
mkdir -p /opt/coapis && cd /opt/coapis

wget https://raw.githubusercontent.com/coapis/coapis/main/docker-compose.yml
wget https://raw.githubusercontent.com/coapis/coapis/main/.env.example -O .env

nano .env  # Fill in your LLM API Key

docker compose up -d
```

### Option 2: Install from Source

```bash
git clone https://github.com/coapis-ai/coapis-agent.git
cd coapis-agent

# Install frontend dependencies and build
cd client && npm ci && npm run build && cd ..

# Configure environment variables
cp docker/.env.example docker/.env
# Edit docker/.env to fill in API Key

# Build from source and start
docker compose -f docker/docker-compose.build.yml up -d --build
```

### Access the Service

Open your browser at `http://<server-ip>:4200`

- Default admin: `admin` / `admin123`
- ⚠️ Change the default password immediately after first login

---

## 📚 Documentation

| Document | Description |
|----------|-------------|
| [Website](https://coapis.cn) | Product overview, edition comparison, online demo |
| [Quick Start](https://coapis.cn/docs/#/help/guide) | 30-second guide |
| [Installation](https://coapis.cn/docs/#/help/install) | Docker, manual, and source installation |
| [Configuration](https://coapis.cn/docs/#/help/config) | Environment variables, Agent & Provider settings |
| [User Guide](https://coapis.cn/docs/#/help/direction) | Chat, channels, workspace, settings |
| [FAQ](https://coapis.cn/docs/#/help/faq) | Installation, configuration, usage FAQ |
| [Source Install Manual](./docs/SOURCE_INSTALL_MANUAL.md) | Build from source details |
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
