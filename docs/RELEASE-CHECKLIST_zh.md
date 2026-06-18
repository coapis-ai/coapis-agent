# CoApis v0.1.0 开源发布清单

## 发布前检查

### 代码质量
- [x] 清理硬编码 IP 地址（使用环境变量）
- [x] 清理敏感信息（API keys、secrets）
- [x] 清理临时/调试脚本
- [x] 清理 DEBUG 日志
- [x] 添加 Apache 2.0 License Header（598 个 Python 文件）
- [ ] 运行 Black 格式化检查（待 GitHub Actions 联调）
- [ ] 运行 Ruff linting 检查（待 GitHub Actions 联调）
- [ ] 运行 mypy 类型检查（待 GitHub Actions 联调）

### 文档
- [x] README.md（项目介绍、快速开始、架构概览）
- [x] CONTRIBUTING.md（贡献指南）
- [x] CHANGELOG.md（版本历史）
- [x] LICENSE（Apache 2.0）
- [x] 安装部署文档 (docs/INSTALL.md)
- [x] 配置参考文档 (docs/CONFIGURATION.md)
- [x] API 参考文档 (docs/API-REFERENCE.md)
- [x] 开发者指南 (docs/DEVELOPER-GUIDE.md)

### CI/CD
- [x] Backend CI workflow（lint + test）
- [x] Frontend CI workflow（lint + build）
- [x] Docker Build workflow
- [ ] 联调测试（推送到 GitHub 后验证 Actions 运行）
- [ ] 自动发布 Release

### 安全
- [x] .gitignore 排除敏感文件
- [x] .env.example 模板（无真实密钥）
- [x] providers.example.json 模板
- [x] config.example.json 模板
- [x] 依赖漏洞扫描（npm audit: 修复 15 个，剩余 8 个中等）
- [x] 依赖漏洞扫描（pip-audit: 修复 8 个，通过 constraints.txt 强制升级）
- [x] Docker 镜像重建验证（coapis-server:latest 3.4GB）
- [x] E2E 全链路测试（59/59 通过，100%）

### 发布准备
- [x] Git 仓库初始化（本地）
- [x] 首次提交
- [x] v0.1.0 标签创建
- [x] Release Notes 编写 (docs/RELEASE-NOTES.md)
- [ ] GitHub 远程仓库创建 ⚠️ 需用户配合
- [ ] 代码推送到 GitHub ⚠️ 需用户配合
- [ ] CI/CD 联调通过 ⚠️ 需用户配合
- [ ] GitHub Release 创建 ⚠️ 需用户配合
- [ ] 开源公告发布 ⚠️ 需用户配合

---

## 待完成项

### 高优先级
1. **GitHub 仓库创建** — 需要用户创建 GitHub 组织/仓库
2. **CI/CD 联调** — 推送到 GitHub 后验证 Actions 运行
3. **依赖漏洞扫描** — 运行 `npm audit` 和 `pip audit`

### 中优先级
1. **完善文档** — 安装部署、配置参考、API 参考
2. **代码格式化检查** — 运行 Black/Ruff/mypy
3. **Release Notes** — 编写详细的 v0.1.0 发布说明

### 低优先级
1. **开源公告** — 撰写发布博客/公告
2. **社区建设** — 创建 Discussions、Issues 模板

---

## 已知限制（v0.1.0）

- 仅支持 OpenAI 兼容 API（不支持其他协议）
- 向量搜索仅支持 ReMeLight（轻量级）
- 不支持 GPU 加速（需用户自行配置 LLM 服务）
- 不支持集群部署（单节点）
- 部分 TODO 未完成（见代码注释）

---

## 下一步计划

- v0.2.0: 多 LLM 提供商支持、集群部署、完善文档
- v0.3.0: 插件系统、API 网关、监控告警
- v1.0.0: 企业级功能完整、生产就绪
