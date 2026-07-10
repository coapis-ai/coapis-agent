# Contributing to CoApis / 贡献指南

感谢你对 CoApis 项目的关注！我们欢迎各种形式的贡献，包括代码、文档、Bug 报告、功能建议等。

## 贡献方式

### 1. 报告 Bug

如果你发现了 Bug，请创建一个 Issue，包含以下信息：

- **问题描述**：清晰描述遇到的问题
- **复现步骤**：详细的操作步骤
- **预期行为**：你认为应该发生什么
- **实际行为**：实际发生了什么
- **环境信息**：
  - OS 版本
  - Docker 版本
  - LLM 服务版本（如 Ollama、OpenAI 等）
  - CoApis 版本

### 2. 提出功能建议

如果你有好的想法，请创建一个 Issue，标签为 `feature`，包含：

- **功能描述**：你想实现什么
- **使用场景**：什么情况下需要这个功能
- **替代方案**：有没有其他方式达到类似效果

### 3. 提交代码

#### 开发环境设置

```bash
# 1. Fork 项目并克隆
git clone https://github.com/<your-username>/coapis-agent.git
cd coapis-agent

# 2. 创建开发分支
git checkout -b feature/your-feature-name

# 3. 安装后端依赖
cd server
pip install -r requirements.txt
cd ..

# 4. 安装前端依赖
cd client
npm install
cd ..

# 5. 启动开发环境
cd docker
docker compose up -d
```

#### 本地调试

```bash
# 后端调试（自动读取 docker/.env）
python start_backend.py

# 前端热更新
cd client && npm run dev
```

#### 代码规范

**Python 后端：**

- 遵循 [PEP 8](https://peps.python.org/pep-0008/) 风格指南
- 使用类型注解（Type Hints）
- 所有 Python 文件需包含 AGPL-3.0 License Header
- 使用 `black` 格式化代码
- 使用 `ruff` 进行 linting

```bash
# 格式化
black server/coapis/

# Lint
ruff check server/coapis/
```

**TypeScript 前端：**

- 遵循 [TypeScript 官方风格指南](https://typescriptlang.org/docs/handbook/declaration-files/do-s-donts.html)
- 使用 ESLint + Prettier
- 组件使用函数式组件 + Hooks
- 所有 API 调用通过 `@/api/index` 的 `api` 对象

```bash
# 进入前端目录
cd client

# 安装依赖
npm install

# Lint
npm run lint

# 格式化
npx prettier --write src/
```

#### 提交规范

使用 [Conventional Commits](https://www.conventionalcommits.org/) 格式：

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

**Type 类型：**

| Type | 说明 |
|------|------|
| `feat` | 新功能 |
| `fix` | Bug 修复 |
| `docs` | 文档更新 |
| `style` | 代码格式（不影响功能） |
| `refactor` | 重构（不改变功能） |
| `perf` | 性能优化 |
| `test` | 测试相关 |
| `chore` | 构建/工具/依赖 |

**示例：**

```
feat(agent): add on-demand skill loading based on query matching

- Add match_skills_by_query() method to SkillManager
- Integrate query-based matching in AgentCore._build_system_prompt()
- Reduce system prompt tokens by filtering irrelevant skills

fix(console): resolve SSE stream timeout issue

- Fix async iterator usage in stream_chat()
- Ensure proper cleanup on connection close
```

#### 分支策略

| 分支 | 用途 |
|------|------|
| `main` | 生产版本，稳定发布 |
| `develop` | 开发版本，功能集成 |
| `feature/*` | 新功能开发 |
| `fix/*` | Bug 修复 |
| `release/*` | 发布准备 |

### 4. 改进文档

文档同样重要！你可以：

- 修正拼写/语法错误
- 补充缺失的说明
- 添加使用示例
- 翻译文档

## 代码审查流程

1. Fork 项目并创建功能分支
2. 提交变更到功能分支
3. 创建 Pull Request 到 `develop` 分支
4. 等待维护者审查
5. 根据反馈修改代码
6. 审查通过后合并

## PR 要求

- [ ] 代码通过 lint 检查
- [ ] 包含必要的测试
- [ ] 更新相关文档
- [ ] 遵循 Conventional Commits 规范
- [ ] 描述清楚变更内容和原因

## 社区行为准则

- 尊重每一位贡献者
- 使用包容性的语言
- 接受建设性的反馈
- 聚焦于对社区最好的事情

## 问题

如果你有任何问题，请通过以下方式联系：

- GitHub Issues
- 项目讨论区

---

再次感谢你的贡献！🎉
