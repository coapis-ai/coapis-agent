<div align="center">

# CoApis

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/Version-0.8.13-green.svg)](CHANGELOG.md)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://hub.docker.com/r/coapis/server)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![React](https://img.shields.io/badge/React-18-blue.svg)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Latest-green.svg)](https://fastapi.tiangolo.com/)
[![i18n](https://img.shields.io/badge/i18n-EN%20%7C%20ZH%20%7C%20JA%20%7C%20RU-orange.svg)](./docs/help/)

[中文](./README.md) | **English**

<img src="https://img.icons8.com/color/96/crab.png" alt="CoApis Logo" width="120">

# Enterprise Multi-User AI Collaboration Platform

> 🚀 **Server-Side Persistence · Multi-User Sharing · Multi-Agent Collaboration · Continuous Evolution**
>
> Run and manage multiple AI agents on the server, providing enterprises with secure, controllable, and continuously evolving AI workspaces.

[Quick Start](#-30-second-quick-experience) · [Core Advantages](#-core-advantages) · [Architecture](#-architecture-design) · [Security](#-security-features) · [Documentation](#-documentation)

---

</div>

## 🎯 What is CoApis?

**CoApis = Enterprise Private-Deployed AI Assistant Team**

Unlike ChatGPT / Claude and other personal tools, CoApis lets you:
- 🔒 **Data Stays In-House** — Fully private deployment, data remains on your own servers
- 👥 **Multi-User Sharing** — Team shares one set of AI agents, each with independent workspace
- 🧠 **Smarter Over Time** — Four-layer memory + skill evolution, agents continuously grow
- 🛡️ **Enterprise Security** — Seven-layer defense + complete audit trail

---

## ⚡ 30-Second Quick Experience

```bash
# One-click start (requires Docker)
mkdir -p /opt/coapis && cd /opt/coapis
wget -qO- https://raw.githubusercontent.com/coapis/coapis/main/install.sh | bash

# Visit http://your-server:4200
# Account: admin / admin123
```

**That's it.** No need to install Node.js, Python, or databases — Docker handles everything.

> 📖 Detailed steps in [Installation Guide](./docs/help/02-安装部署_zh.md) · [CLI Reference](./docs/CLI-REFERENCE_zh.md)

---

## 🏆 Core Advantages

### 1. 🏢 Enterprise-Grade Multi-User Architecture

| Capability | Description |
|------------|-------------|
| **Server-Side Persistence** | Agents run 24/7, tasks continue after browser close |
| **Multi-User Sharing** | Team shares AI agents with independent workspaces |
| **Data Isolation** | Each user has independent Agent, files, memory — invisible to others |
| **RBAC Permissions** | Four-tier roles (guest/user/advanced/admin), fine-grained control |
| **Token Quotas** | Monthly quotas by role, costs under control |

### 2. 🧠 Four-Layer Memory — Truly "Smarter Over Time"

| Memory Layer | Purpose | Lifecycle |
|--------------|---------|-----------|
| `short_term` | Current conversation context | Session |
| `long_term` | Cross-session user preferences, experience | Permanent |
| `core` | Agent's core values and thinking patterns | Permanent |
| `ephemeral` | Temporary data, intermediate reasoning | Temporary |

**Key Advantages:**
- ✅ Agent **automatically extracts valuable information** from every interaction into long-term memory
- ✅ Semantic retrieval capability, **precisely recall** relevant information from historical memories
- ✅ User preferences, work habits, project context — **never forgotten**

### 3. 🌱 Skill Evolution Engine — Self-Learning Agents

```
User Need → Auto-Create Skill → Five-Dimension Evaluation → Promote/Retire
    ↑                                                        ↓
    └──── Continuous Optimization ←── Usage Feedback ←────────┘
```

**Evolution Mechanism:**
- 🔄 **Auto-Generation** — Agents create new skills based on user needs
- 📊 **Five-Dimension Evaluation** — Accuracy, reliability, efficiency, satisfaction, robustness
- ⬆️ **Auto-Promotion** — High-performing skills upgrade to higher tiers (global/user/agent)
- ⬇️ **Auto-Retirement** — Low-performing skills demoted or removed
- 🌐 **Cross-Agent Propagation** — Validated skills shared across agents

### 4. 🛡️ Seven-Layer Security — Enterprise-Grade Protection

```
┌─────────────────────────────────────────────────┐
│  Layer 7: Audit & Compliance    All actions traceable │
│  Layer 6: Docker Hardening      Resource limits + network isolation │
│  Layer 5: Env Minimization      Only 4 variables exposed │
│  Layer 4: Tool Protection       29 rules + 65 sensitive paths │
│  Layer 3: Sandbox Isolation     Process + namespace isolation │
│  Layer 2: Behavior Monitoring   Auto-ban dangerous ops │
│  Layer 1: Command Risk Classify 17 categories × 4 role levels │
└─────────────────────────────────────────────────┘
```

### 5. 🌐 Multi-Language & Multi-Channel

**Languages:** 中文 · English · 日本語 · Русский (one-click switch)

**Channels:** WeCom · DingTalk · Slack · Telegram · Webhook

### 6. 🛠️ 56+ Refined Tools

Refined from 108+ tools to 56+ high-frequency utilities covering:

| Scenario | Tools |
|----------|-------|
| 📁 File Operations | Read, write, edit, search, version management |
| 💻 Shell Execution | Command execution, environment management |
| 🌐 Browser Automation | Playwright integration, web scraping |
| 📄 Document Processing | PDF, Word, Excel, PPT generation & parsing |
| 🔍 Web Search | Tavily, Exa search engines |
| 📧 Email Management | IMAP/SMTP send/receive |
| 🧠 Memory Retrieval | Semantic search of historical memories |
| 🤖 Agent Collaboration | Cross-agent communication, task distribution |

---

## 🏗️ Architecture Design

### Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18 + TypeScript + Ant Design 5 + Vite 5 |
| Backend | Python 3.11+ + FastAPI + SQLite/JSON |
| Deployment | Docker + Docker Compose + Nginx |
| LLM | Any OpenAI-compatible API (OpenAI / Ollama / vLLM / LM Studio, etc.) |

### System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      CoApis Platform                        │
├─────────────────────────────────────────────────────────────┤
│  Frontend (React)              Backend (FastAPI)            │
│  ┌─────────────┐  ┌─────────────┐  ┌────────────────────┐  │
│  │  Chat UI    │  │  MySpace    │  │  REST + SSE API    │  │
│  │  (Multi-turn)│ │  (File Mgmt)│  │  (56+ Tools)       │  │
│  └─────────────┘  └─────────────┘  └────────────────────┘  │
│  ┌─────────────┐  ┌─────────────┐  ┌────────────────────┐  │
│  │  Evolution  │  │  Admin      │  │  Security Layer    │  │
│  │  (Dashboard)│  │  (User Mgmt)│  │  (7-Layer Defense) │  │
│  └─────────────┘  └─────────────┘  └────────────────────┘  │
├─────────────────────────────────────────────────────────────┤
│                    Agent Core Layer                          │
│  ┌─────────────┐  ┌─────────────┐  ┌────────────────────┐  │
│  │  Foundation │  │  Evolution  │  │  Context Manager   │  │
│  │  (4-Layer   │  │  (Skill     │  │  (Context          │  │
│  │   Memory)   │  │   Evolution)│  │   Compression)    │  │
│  └─────────────┘  └─────────────┘  └────────────────────┘  │
├─────────────────────────────────────────────────────────────┤
│                    Infrastructure                            │
│  ┌─────────────┐  ┌─────────────┐  ┌────────────────────┐  │
│  │  LLM Service│  │  Storage    │  │  Channels          │  │
│  │  (Multi-    │  │  (JSON/DB)  │  │  (WeCom/DingTalk)  │  │
│  │   Model)    │  │             │  │                    │  │
│  └─────────────┘  └─────────────┘  └────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### Comparison with Alternatives

| Dimension | Personal AI (ChatGPT/Claude) | CoApis |
|-----------|------------------------------|--------|
| 🏠 **Deployment** | Local client, tied to personal computer | Server-side, team shared |
| 👥 **Users** | 1 person | Multiple users, data isolated |
| 🧠 **Memory** | Session-only, lost on close | Four-layer memory, permanent |
| 🤖 **Agents** | Single assistant | Three-tier system, skill evolution |
| 🛡️ **Security** | Basic filtering | Seven-layer defense, audit trail |
| 🏢 **Compliance** | None | RBAC + audit logs + token quotas |
| 🔧 **Extension** | Plugin marketplace | Custom skills + multi-channel |

---

## 🚀 Quick Start

### Prerequisites

- Docker & Docker Compose
- Any OpenAI-compatible LLM API (OpenAI / Ollama / vLLM / LM Studio, etc.)

### Option 1: One-Click Install (Recommended ⭐)

```bash
curl -fsSL https://raw.githubusercontent.com/coapis/coapis/main/install.sh | bash
```

### Option 2: Manual Docker Deployment

```bash
mkdir -p /opt/coapis && cd /opt/coapis

wget https://raw.githubusercontent.com/coapis/coapis/main/docker-compose.yml
wget https://raw.githubusercontent.com/coapis/coapis/main/.env.example -O .env

nano .env  # Set your LLM API Key

docker compose up -d
```

### Option 3: Install from Source

```bash
git clone https://github.com/coapis/coapis.git
cd coapis

# Build frontend
cd client && npm ci && npm run build && cd ..

# Configure environment
cp docker/.env.example docker/.env
# Edit docker/.env to set API Key

# Build and start
docker compose -f docker/docker-compose.build.yml up -d --build
```

### Access Service

Open browser at `http://<server-ip>:4200`

- Default admin: `admin` / `admin123`
- ⚠️ Change default password after first login

---

## 📚 Documentation

| Document | Description |
|----------|-------------|
| [Installation Guide](./docs/help/02-安装部署_zh.md) | One-click, Docker, source installation |
| [CLI Reference](./docs/CLI-REFERENCE_zh.md) | Complete CLI tool reference |
| [Configuration Guide](./docs/help/03-配置指南_zh.md) | Model, channel, permission config |
| [API Reference](./docs/API-REFERENCE_zh.md) | RESTful API documentation |
| [Security Hardening](./docs/security-hardening-guide.md) | Seven-layer security architecture |
| [Security Architecture](./docs/security-architecture.md) | Architecture design & extension |
| [Operations Manual](./docs/ops-security-manual.md) | Whitelist, ban handling, alerts |
| [Deployment Guide](./docs/DEPLOYMENT_zh.md) | Production deployment |

---

## 🔧 CLI Quick Reference

```bash
# System initialization
coapis init                              # Interactive initialization
coapis init --defaults --accept-security # Non-interactive (Docker/scripts)

# Management
coapis auth                              # Authentication management
coapis models                            # Model configuration
coapis channels                          # Channel configuration
coapis cron                              # Scheduled tasks
coapis admin                             # Admin tools
coapis doctor                            # Health check

# Help
coapis --help                            # General help
coapis <command> --help                  # Subcommand help
```

> 📖 Complete reference at [CLI-REFERENCE_zh.md](./docs/CLI-REFERENCE_zh.md)

---

## 🛡️ Security Features

CoApis features a **seven-layer defense-in-depth architecture**, each layer independently intercepting threats:

| Layer | Capability | Description |
|-------|-----------|-------------|
| L1 | Command Risk Classification | 17 command categories × 4 role levels |
| L2 | Behavior Monitoring & Auto-Ban | Dangerous operations auto-banned |
| L3 | Sandbox Isolation | Process + namespace isolation |
| L4 | Environment Minimization | Only 4 variables exposed |
| L5 | Tool Protection Engine | 29 rules + 65 sensitive paths |
| L6 | Docker Hardening | Resource limits + network isolation |
| L7 | Complete Audit Trail | All actions logged and exportable |

See [Security Hardening Guide](./docs/security-hardening-guide.md) · [Security Architecture](./docs/security-architecture.md)

---

## 🗺️ Roadmap

| Direction | Item | Status |
|-----------|------|--------|
| **Platform** | Docker non-root execution | Planned |
| **Platform** | Kernel-level seccomp/AppArmor sandbox | Planned |
| **Agents** | Group chat mode | Planned |
| **Agents** | Smart context compression | In Progress |
| **Skill Ecosystem** | Skill marketplace (ClawHub-style) | Seeking Contributors |
| **Channels** | Feishu, QQ channels | Seeking Contributors |
| **Coding** | LSP, workspace version control | Planned |

---

## Version Strategy

| Version | Position | License |
|---------|----------|---------|
| CE (Community) | Open source free | Apache 2.0 |
| EE (Enterprise) | Commercial enhancement | Commercial License |
| CD (Cloud) | SaaS service | Subscription |

---

## Contributing

Welcome code contributions, documentation, bug reports, etc. See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

## Community

| Channel | Link |
|---------|------|
| Gitee | [ouerlai/coapis-agent](https://gitee.com/ouerlai/coapis-agent) |
| GitHub | [coapis/coapis-agent](https://github.com/coapis/coapis-agent) |
| Security Vulnerabilities | [SECURITY.md](SECURITY.md) |

---

## Why "CoApis"?

CoApis — Eater (explorer) + Claw (grip). A crab that wants to try everything and can grab anything — your AI work partner. 🦀

---

## License

Copyright 2026 蜜蜂 & CoApis Contributors

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
