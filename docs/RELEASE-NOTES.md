# CoApis v0.1.0 Release Notes

## 🎉 Initial Open Source Release

CoApis v0.1.0 is now available! This is the first open-source release of CoApis, a multi-user server-side AI agent platform with hierarchical memory architecture and intelligent evolution system.

## ✨ Highlights

- **Multi-tenant Architecture**: Complete user isolation with independent agents, models, skills, and configurations per user
- **Hierarchical Memory System**: Three-layer memory architecture (Foundation/Professional/Instance) with intelligent injection and quota management
- **Intelligent Evolution**: LLM-driven experience extraction, knowledge flow mechanism, and async background review system
- **On-demand Skill Loading**: Semantic/keyword-based skill matching, reducing context tokens by 91%
- **Context Compression**: 4-tier compression strategy with cooling mechanism, reducing prefill time by 2-3x
- **Enterprise File Management**: Drag-and-drop upload, search, preview, storage quota tracking
- **Evolution Dashboard**: Real-time monitoring of agent evolution status, experiences, and knowledge flow
- **User Preference Sync**: Chat display settings, timestamps, token counts, auto-scroll, and more
- **Admin Backend**: Global configuration, user management, and system monitoring

## 📦 Dependencies

### Frontend (npm)
- **Fixed**: 15 vulnerabilities (12 high, 3 moderate) via `npm audit fix`
- **Remaining**: 8 moderate vulnerabilities (require breaking changes to fix)
- **Note**: Remaining vulnerabilities are in transitive dependencies (`prismjs`, `react-syntax-highlighter`, etc.)

### Backend (pip)
- **Fixed**: 8 vulnerabilities in transitive dependencies (authlib CVE-2026-41425, lxml CVE-2026-41066, mistune CVE-2026-33079, python-multipart CVE-2026-42561, jupyter-server CVE-2025-61669/CVE-2026-40110/CVE-2026-35397/CVE-2026-40934)
- **Solution**: Added `server/constraints.txt` with minimum patched versions, applied during Docker build
- **Note**: All vulnerabilities are in transitive dependencies, not direct `pyproject.toml` declarations

## 🐛 Bug Fixes

- Chat 400 error (missing `agent_id` in `biz_params`)
- `active_model` null after container rebuild
- Custom Provider config persistence (`SECRET_DIR` → `DATA_DIR`)
- Nginx Authorization header stripping
- Rate limiting on internal API paths
- SSE streaming deadlocks (`BaseHTTPMiddleware` → `@app.middleware("http")`)
- Provider config parsing (`api_key=None` → `"none"`)
- Reasoning parser compatibility (`reasoning` field vs `content` field)
- Model config persistence on refresh
- PyPI 404 errors (disabled version check)

## 📚 Documentation

- README.md (project overview, quick start, architecture)
- CONTRIBUTING.md (contribution guidelines)
- CHANGELOG.md (version history)
- INSTALL.md (installation & deployment guide)
- CONFIGURATION.md (configuration reference)
- API-REFERENCE.md (comprehensive API documentation)
- DEVELOPER-GUIDE.md (development environment, architecture, debugging)
- LICENSE (Apache 2.0)

## 🚀 CI/CD

- Backend CI workflow (lint + test)
- Frontend CI workflow (lint + build)
- Docker Build workflow

## 📋 Known Limitations

- Only supports OpenAI-compatible API (no other protocols)
- Vector search only supports ReMeLight (lightweight)
- No GPU acceleration (requires user-configured LLM service)
- No cluster deployment (single node only)
- Some TODOs incomplete (see code comments)

## 🔜 Next Steps

- **v0.2.0**: Multi-LLM provider support, cluster deployment, improved documentation
- **v0.3.0**: Plugin system, API gateway, monitoring & alerting
- **v0.1.0.0**: Full enterprise features, production-ready

## 🙏 Acknowledgments

- Built on top of [CoApis](https://github.com/QwenLM/CoApis) console
- Uses [AgentScope](https://github.com/agentscope-ai/agentscope) runtime
- Powered by any OpenAI-compatible LLM service (e.g., vLLM, Ollama, LM Studio, OpenAI)

## 📝 License

Apache 2.0 License - see [LICENSE](../../LICENSE) for details.

---

**Happy coding! 🎉**
