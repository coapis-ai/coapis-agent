# CoApis

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/Docker-GHCR-green)](https://ghcr.io/coapis/server)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue)](https://www.python.org/)
[![React](https://img.shields.io/badge/React-18-blue)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Latest-green)](https://fastapi.tiangolo.com/)
[![i18n](https://img.shields.io/badge/i18n-EN%20%7C%20ZH%20%7C%20JA%20%7C%20RU-orange)](./docs/help/)

<div align="center">

[中文](./README.md) | **English**

---

## 🦀 CoApis Multi-User Server-Side AI Agent Platform

**Run and manage multiple AI agents on the server side, shared by multiple users within an organization**

[Quick Start](#quick-start-en) • [Features](#features-en) • [Architecture](#architecture-en) • [Documentation](./docs/help/) • [Configuration](./docs/help/03-配置指南_zh.md)

## ✨ Features

### 🏢 Multi-User Server-Side Agents

- **Server-Side Persistence** — Agents run on the server, 24/7 online, independent of user frontend connections
- **Multi-User Sharing** — Multiple users in an organization can share the same Agent
- **Background Tasks** — Support cron jobs, async execution, cross-session memory

### 🔐 Multi-Tenant Data Isolation

- **Independent Workspaces** — Each user has independent Agents, files, memory, and preferences
- **Fine-Grained Permissions** — RBAC permission management system
- **Data Privacy First** — Fully local deployment, data never leaves the enterprise network

### 🧠 Hierarchical Memory Architecture

- **Three-Layer Memory** — Foundation (long-term) / Professional (domain knowledge) / Instance (context)
- **Smart Memory Management** — Auto compression, retrieval, and updates
- **ContextCompressor** — Smart context compression for long conversations

### 🌱 Intelligent Evolution System

- **Auto Learning** — Learn from every conversation, extract experience automatically
- **Knowledge Accumulation** — Experience auto-converted to reusable knowledge and skills
- **Skill Promotion** — Highly effective skills auto-promoted to higher levels; low-performing ones retired
- **Cross-Agent Propagation** — Validated skills can be automatically shared across agents

### 🧩 Skill Ecosystem

- **Auto Generation** — Agents create new skills based on user needs, no manual coding required
- **Continuous Optimization** — Skill triggers and content are automatically tuned based on usage effectiveness
- **Version Control** — Every skill change is versioned with rollback capability
- **Three-Tier Skills** — Global → User → Agent-level skills with cascading override

### 🏗️ Enterprise-Grade Features

- **Audit Logs** — Complete operation logging for compliance
- **File Management** — Upload, download, versioning, 409 overwrite confirmation
- **Cron Jobs** — Cron expression support for automation
- **Backup & Restore** — Data backup and recovery
- **Token Quotas** — Per-user token quotas to prevent abuse

### 🌍 Multi-Language Support

| Language | Code | Status |
|----------|------|--------|
| 中文（简体） | `zh` | ✅ Full |
| English | `en` | ✅ Full |
| 日本語 | `ja` | ✅ Full |
| Русский | `ru` | ✅ Full |

### 🔌 Multi-Channel Integration

- **WeCom** (Enterprise WeChat)
- **DingTalk** (DingTalk)
- **Slack**
- **Telegram**
- **Webhook** (Custom)

## 🚀 Quick Start (EN)

### Prerequisites

- Docker & Docker Compose
- OpenAI-compatible LLM API (OpenAI, Ollama, vLLM, LM Studio, etc.)

### Option 1: One-Click Install (Recommended ⭐)

```bash
curl -fsSL https://raw.githubusercontent.com/coapis/coapis/main/install.sh | bash
```

### Option 2: Manual Docker Deployment

```bash
mkdir -p /opt/coapis && cd /opt/coapis
wget https://raw.githubusercontent.com/coapis/coapis/main/docker-compose.yml
wget https://raw.githubusercontent.com/coapis/coapis/main/.env.example -O .env
# Edit .env to set your API key
nano .env
docker compose up -d
```

### Option 3: Build from Source

```bash
git clone https://github.com/coapis/coapis.git
cd coapis
cp .env.example .env
# Edit .env to set your API key
docker compose -f docker-compose.build.yml up -d --build
```

### Access

Open browser: `http://<server-ip>:4200`

- Default admin: `admin` / `admin123`
- ⚠️ Change the default password immediately after first login
# Register admin account on first use
```

> 📖 **Full documentation**: [Help Docs](./docs/help/)

## 🏗️ Architecture (EN)

```
┌─────────────────────────────────────────────────────────┐
│                     CoApis Platform                    │
├─────────────────────────────────────────────────────────┤
│  Frontend (React + Ant Design)          Backend (FastAPI)│
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐ │
│  │   Chat UI    │  │  MySpace     │  │  API Routers   │ │
│  │  (ChatPage)  │  │  (Files)     │  │  (REST + SSE)  │ │
│  └──────────────┘  └──────────────┘  └────────────────┘ │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐ │
│  │  Evolution   │  │  Admin       │  │  Middleware    │ │
│  │  Dashboard   │  │  (User Mgmt) │  │  (Auth/Rate)   │ │
│  └──────────────┘  └──────────────┘  └────────────────┘ │
├─────────────────────────────────────────────────────────┤
│                    Agent Core Layer                       │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐ │
│  │ Foundation   │  │  Evolution   │  │  Context       │ │
│  │  (Memory)    │  │  (Learning)  │  │  Compressor    │ │
│  └──────────────┘  └──────────────┘  └────────────────┘ │
├─────────────────────────────────────────────────────────┤
│                    Infrastructure Layer                    │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐ │
│  │  LLM Service  │  │   SQLite     │  │  File Storage  │ │
│  └──────────────┘  └──────────────┘  └────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

## 📊 Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | React 18 + TypeScript + Ant Design 5 + Vite 5 |
| Backend | Python 3.11+ + FastAPI + SQLite + Pydantic v2 |
| Deployment | Docker + Docker Compose + Nginx |
| LLM | Any OpenAI-compatible API (Ollama/OpenAI/Anthropic/vLLM etc.) |

## 📚 Documentation

- **[Help Docs](./docs/help/)** — Complete product documentation
- **[Deployment Guide](./docs/deployment.md)** — Production deployment guide
- **[API Reference](./docs/API-REFERENCE.md)** — API documentation
- **[Configuration Guide](./docs/help/03-配置指南_zh.md)** — Environment, Agent, Provider config
- **[Contributing Guide](./CONTRIBUTING.md)** — How to contribute
- **[Security Policy](./SECURITY.md)** — Security vulnerability reporting

## 🗺️ Edition Strategy

| Edition | Positioning | License |
|---------|-------------|---------|
| CE (Community) | Open source free | Apache 2.0 |
| EE (Enterprise) | Commercial enhanced | Commercial License |
| CD (Cloud) | SaaS service | Subscription |

## 🤝 Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

## 📄 License

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

</div>
