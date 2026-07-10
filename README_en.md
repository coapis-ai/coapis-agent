<div align="center">

# CoApis

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/Version-0.9.11-green.svg)](CHANGELOG.md)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://hub.docker.com/r/coapis/server)
[![i18n](https://img.shields.io/badge/i18n-ZH%20%7C%20EN%20%7C%20JA%20%7C%20RU-orange.svg)](#)

[中文](./README.md) | **English**

<img src="https://img.icons8.com/color/96/bee.png" alt="CoApis Logo" width="120">

# Your Team Deserves Its Own AI Assistant

> CoApis is a self-hosted AI collaboration platform. It runs on your own server, shared by your team, with data that never leaves your hands — and gets smarter over time.

[What It Does](#-what-does-it-do) · [Why Choose It](#-why-choose-it) · [Get Started](#-get-started)

</div>

---

## 🤔 What Does It Do?

### A Shared AI Assistant for Your Team

Instead of everyone having their own ChatGPT account, CoApis runs on your company server. **The whole team shares one AI assistant**, but each person has their own workspace — your conversations, your files, your memory. No one else can see them.

The agent runs 24/7. Close your browser, it keeps working. Scheduled tasks trigger automatically — no babysitting required.

### It Actually Gets Smarter

Regular AI assistants forget everything after each conversation. CoApis agents have **four layers of memory**:

- It remembers what you talked about last time
- It knows your work habits and preferences
- It learns from every interaction, automatically
- The longer you use it, the better it understands you

### It Creates Its Own Skills

When an agent notices you doing the same thing repeatedly, it **automatically creates a new skill** to handle it. Good skills get promoted, bad ones get retired. What one agent learns can be shared with others.

### Enterprise-Grade Security

Your data stays **completely on your own server** — nothing gets sent to any third party. Built-in seven-layer security: dangerous operations require confirmation, unusual behavior gets auto-banned, and every action has an audit trail.

### Multi-Channel Integration

Not just a web interface. CoApis supports **WeCom, DingTalk, Feishu, Telegram, Discord, QQ** and more — so you can chat with AI right in the tools you already use.

### Multi-Language UI

Supports Chinese, English, Japanese, and Russian interface languages.

---

## 💡 Why Choose It?

| | ChatGPT / Claude (Personal Tools) | CoApis |
|--|-----------------------------------|--------|
| **Data** | On someone else's server | On your own server |
| **Users** | One person | Your whole team |
| **Close browser** | Conversation ends | Agent keeps working |
| **Memory** | Starts fresh every time | Learns about you over time |
| **Security** | Basic protection | Seven-layer defense + audit trail |
| **Enterprise** | None | Permissions + usage quotas |

---

## 🚀 Get Started

### Docker Deploy

```bash
mkdir -p /opt/coapis && cd /opt/coapis
wget https://raw.githubusercontent.com/coapis/coapis/main/docker-compose.yml
wget https://raw.githubusercontent.com/coapis/coapis/main/.env.example -O .env
nano .env  # Set your LLM API Key
docker compose up -d
```

### From Source

```bash
git clone https://github.com/coapis/coapis.git
cd coapis
cd client && npm ci && npm run build && cd ..
cp docker/.env.example docker/.env
docker compose -f docker/docker-compose.build.yml up -d --build
```

### Log In

- URL: `http://your-server-ip:4200`
- Account: `admin` / `admin123`
- ⚠️ Change the default password immediately

> 📖 Docs: [Help Center](./docs/help-html/) · [Source Install Manual](./docs/SOURCE_INSTALL_MANUAL.md)

---

## 📚 Documentation

| Document | Description |
|----------|-------------|
| [Product Overview](./docs/marketing/01-产品介绍.md) | What this product is |
| [Quick Start](./docs/help-html/01-快速入门.html) | 30-second guide |
| [Installation](./docs/help-html/02-安装部署.html) | How to install and run |
| [Configuration](./docs/help-html/03-配置指南.html) | Models, channels, permissions |
| [Source Install Manual](./docs/SOURCE_INSTALL_MANUAL.md) | Build from source |
| [Developer Guide](./docs/developer/二次开发指南.md) | For developers |
| [API Reference](./docs/developer/API参考.md) | API documentation |
| [Security](./docs/security/sandbox-security-plan.md) | Security architecture |

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
