<div align="center">

# CoApis

[![License](https://img.shields.io/badge/License-AGPL%203.0-red.svg)](LICENSE)
[![Version](https://img.shields.io/badge/Version-0.9.11-green.svg)](CHANGELOG.md)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://hub.docker.com/r/coapis/server)

[中文](./README.md) | **English**

<img src="https://img.icons8.com/color/96/bee.png" alt="CoApis Logo" width="120">

# Enterprise Agent Harness

> Deploy once, entire team uses

[Website](https://coapis.cn) · [Quick Start](#-quick-start)

---

</div>

## 🎯 Core Value

### Install Once, Everyone Uses

Deploy once for the entire company, and everyone can start immediately. Zero technical barrier — no need to understand configuration, install environments, or buy accounts. Just open your browser and start working, as simple as using any enterprise tool.

### Team Collaboration, Individual Privacy

Everyone shares the same system, but each person has their own private workspace. Your conversations, files, and accumulated experience are invisible to others. Share resources while protecting privacy.

### Smarter Over Time

The system remembers your habits and preferences, automatically learning your common workflows. The more you use it, the better it understands you. Good methods you discover can be shared with colleagues; their experience can be inherited by you. The team's collective wisdom flows and grows.

### Fortress-Grade Security

Seven layers of defense: dangerous operations are automatically blocked, sensitive files are protected, abnormal behaviors are monitored in real-time, all actions are fully logged. Like installing a safe for your enterprise — enabling productivity while preventing chaos.

### Remembers What Matters

The system remembers key information, extracts valuable knowledge, and accumulates reusable experience. Project context, customer preferences, operational tips — no need to worry about forgetting, everything is retrievable. Like having an assistant who never tires of organizing your notes.

### Integrates Into Daily Work

Connect to WeCom, DingTalk, Feishu — use it where you already work. Link to existing enterprise systems, bridge data and workflows. Not a separate tool, but an enhancement to what you already use, making AI part of your daily routine.

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
