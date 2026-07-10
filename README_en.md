<div align="center">

# CoApis

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/Version-0.9.11-green.svg)](CHANGELOG.md)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://hub.docker.com/r/coapis/server)

[中文](./README.md) | **English**

<img src="https://img.icons8.com/color/96/bee.png" alt="CoApis Logo" width="120">

# Enterprise AI Agent Harness Platform

> Deploy and manage AI agents securely for your entire team

[Website](https://coapis.cn) · [What is Harness](#-what-is-ai-agent-harness) · [Quick Start](#-quick-start)

---

</div>

## 🎯 What is AI Agent Harness?

**Harness** is a framework that provides runtime infrastructure for AI agents:

- **Runtime Environment** — Keep agents running continuously on the server
- **Tool Capabilities** — Shell, browser, document processing, and more
- **Memory System** — Manage context, accumulate experience
- **Security Boundaries** — Constrain agent behavior, prevent dangerous operations
- **Monitoring & Audit** — Track all operations, ensure compliance

**CoApis is Enterprise-Grade Harness** — Deploy once, entire team uses it, each person has isolated space.

---

## 🏆 Core Value

### One Deployment, Team-Wide Access

IT deploys once, the entire team starts using immediately. No need for everyone to understand AI or deployment.

### Server-Side Resident Operation

Agents run 7×24 on the server. Close your browser, tasks continue executing.

### Multi-User Collaboration, Independent Spaces

Team members share agent infrastructure, but each person has their own workspace — conversations, files, and memory are isolated.

### Continuous Agent Evolution

Agents remember your preferences, automatically identify reusable patterns, and crystallize them into skills. The more you use it, the better it understands you.

### Enterprise-Grade Security & Audit

Complete data isolation, permission control, dangerous operation approval, and audit trail.

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

## 🔧 Harness Capabilities

| Capability | Description |
|------------|-------------|
| **Tool System** | Shell execution, browser automation, document processing, web search, and 29 built-in tools |
| **Memory Management** | Multi-layer memory system, semantic retrieval, automatic experience accumulation |
| **Security Boundaries** | Command risk classification, dangerous operation blocking, sandbox isolation |
| **Constraint Mechanism** | RBAC permissions, token quotas, operation approval |
| **Monitoring & Audit** | Complete audit trail, behavior monitoring, log export |

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
