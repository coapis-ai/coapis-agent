<div align="center">

# CoApis

[![License](https://img.shields.io/badge/License-AGPL%203.0-red.svg)](LICENSE)
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

## 🏗️ Core Capability Architecture

### Tool Capabilities

What agents can do. Tools for file operations, shell execution, browser automation, document processing, web search; automatically identify reusable patterns and crystallize into skills.

### Integration Capabilities

How agents connect to external systems. Integrate existing enterprise systems through API, MCP (Model Context Protocol), and other standard protocols to bridge data and workflows.

### Orchestration Capabilities

How agents organize and collaborate. Configure roles, styles, and security boundaries; orchestrate multi-agent workflows; accumulate knowledge, continuously evolve, and share experience across agents.

### Control Capabilities

How agents run stably. Complete execution environment, multi-layer memory system, security boundaries, audit trails — enabling long-term, controllable operation.

**This is the core capability**

---

## 🚀 Quick Start

### Docker Deploy

```bash
# Download only docker directory
git clone --depth 1 --filter=blob:none --sparse \
  https://github.com/coapis-ai/coapis-agent.git && \
  cd coapis-agent && \
  git sparse-checkout set docker && \
  cd docker

# Configure environment variables
cp .env.example .env
nano .env  # Fill in API Key

# Start service
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

GNU Affero General Public License v3.0 · Copyright 2026 蜜蜂 & CoApis Contributors

---

**Why "CoApis"?** — Co (Collaboration) + Apis (Latin for "bee"), symbolizing swarm-style team collaboration, building enterprise-grade AI Agent Harness, embodying the philosophy of "enterprise collaboration, collective intelligence, division of labor evolution, full-chain control". 🐝
