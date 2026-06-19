# CoApis 开发者指南

## 开发环境搭建

### 前置要求

- Python 3.11+
- Node.js 18+ + npm
- Docker & Docker Compose
- Git

### 本地开发模式

```bash
# 1. 克隆项目
git clone https://github.com/coapis/coapis.git
cd coapis-agent

# 2. 配置环境变量
cp docker/.env.example docker/.env
# 编辑 docker/.env

# 3. 配置 Provider 和 Agent
cp docker/config/providers.example.json docker/config/providers.json
cp docker/config/config.example.json docker/config/config.json

# 4. 启动 Docker 服务
cd docker
docker compose up -d server
# 注意：只启动 server，前端使用开发服务器

# 5. 启动前端开发服务器
cd ../client
npm install
npm run dev

# 6. 访问前端
# 打开浏览器访问 http://localhost:5173 (Vite 默认端口)
```

### 后端开发

```bash
# 1. 安装 Python 依赖
cd server
pip install -e ".[dev]"

# 2. 启动开发服务器
cd coapis
uvicorn app._app:app --reload --host 0.0.0.0 --port 8000

# 3. 运行测试
python -m pytest tests/ -v

# 4. 代码格式化
black server/coapis/
ruff check server/coapis/ --fix

# 5. 类型检查
mypy server/coapis/
```

### 前端开发

```bash
# 1. 安装依赖
cd client
npm install

# 2. 启动开发服务器
npm run dev

# 3. 构建生产版本
npm run build

# 4. 预览生产构建
npm run preview

# 5. 代码检查
npm run lint
npm run lint -- --fix
```

---

## 项目架构

### 后端架构

```
server/coapis/
├── agent/                 # Agent 核心引擎
│   ├── core.py            # AgentCore - 智能体核心
│   ├── workspace.py       # Workspace - 工作区管理
│   ├── skills_manager.py  # 技能管理器
│   ├── context_compressor.py  # 上下文压缩器
│   └── skills/            # 内置技能
├── app/                   # API 层
│   ├── _app.py            # FastAPI 应用入口
│   ├── routers/           # 路由模块
│   │   ├── console.py     # 聊天路由（SSE 流式）
│   │   ├── auth.py        # 认证路由
│   │   ├── files.py       # 文件管理路由
│   │   ├── evolution.py   # 进化系统路由
│   │   └── ...
│   ├── middleware/        # 中间件
│   │   ├── auth_middleware.py      # 认证中间件
│   │   ├── user_isolation.py       # 用户隔离中间件
│   │   └── rate_limit.py           # 限流中间件
│   └── crons/             # 定时任务
├── evolution/             # 进化引擎
│   ├── evolution_engine.py    # 核心引擎
│   ├── experience_extractor.py # 经验提取器
│   ├── knowledge_flow.py      # 知识流动
│   └── backend_review.py      # 后台审查
├── foundation/            # 分层记忆
│   ├── foundation_manager.py  # 基础层管理器
│   ├── memory_entry.py        # 记忆条目
│   └── memory_injector.py     # 记忆注入器
├── user_system/           # 用户体系
│   ├── database.py        # SQLite 数据库
│   ├── models.py          # 数据模型
│   └── routers/           # 用户路由
└── config/                # 配置管理
    └── config.py          # 配置加载器
```

### 前端架构

```
client/src/
├── api/                   # API 封装层
│   ├── index.ts           # API 客户端
│   ├── request.ts         # 请求封装（fetch）
│   ├── config.ts          # API 配置
│   └── modules/           # 按模块划分
│       ├── auth.ts        # 认证 API
│       ├── chat.ts        # 聊天 API
│       ├── evolution.ts   # 进化 API
│       └── ...
├── components/            # 通用 UI 组件
├── contexts/              # React Context
│   ├── UserContext.tsx    # 用户上下文
│   └── ThemeContext.tsx   # 主题上下文
├── layouts/               # 布局组件
│   ├── MainLayout/        # 主布局
│   ├── Header.tsx         # 顶部导航
│   └── Sidebar.tsx        # 侧边栏
├── pages/                 # 页面组件
│   ├── Chat/              # 聊天页面
│   ├── MySpace/           # 文件管理
│   ├── Evolution/         # 进化 Dashboard
│   └── ...
├── stores/                # 状态管理（Zustand）
└── locales/               # 国际化
    ├── zh.json            # 中文
    └── en.json            # 英文
```

---

## 添加新功能

### 添加新的 API 路由

1. 在 `server/coapis/app/routers/` 创建路由文件：

```python
# server/coapis/app/routers/my_feature.py
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

router = APIRouter()

@router.get("/my-feature")
async def get_my_feature():
    return {"status": "ok", "data": "..."}

@router.post("/my-feature")
async def create_my_feature(data: dict):
    # 业务逻辑
    return {"status": "created"}
```

2. 在 `server/coapis/app/routers/__init__.py` 注册：

```python
from .my_feature import router as my_feature_router

# 注册到主 router
main_router.include_router(my_feature_router, prefix="/my-feature")
```

3. 更新 Nginx 配置（如果需要）：

```nginx
# docker/nginx.conf
location ~ ^/api/(my-feature|...) {
    proxy_pass http://coapis-server:8000;
}
```

### 添加新的前端页面

1. 创建页面组件：

```tsx
// client/src/pages/MyFeature/index.tsx
import { useTranslation } from 'react-i18next';

export default function MyFeaturePage() {
  const { t } = useTranslation();
  
  return (
    <div className="page-container">
      <h1>{t('myFeature.title')}</h1>
      {/* 页面内容 */}
    </div>
  );
}
```

2. 添加路由：

```tsx
// client/src/layouts/MainLayout/index.tsx
import MyFeaturePage from '../../pages/MyFeature';

// 在 routes 中添加
{
  path: '/my-feature',
  element: <MyFeaturePage />,
}
```

3. 添加菜单项：

```ts
// client/src/layouts/constants.ts
export const MENU_ITEMS = {
  // ...
  myFeature: '/my-feature',
};
```

4. 添加翻译：

```json
// client/src/locales/zh.json
{
  "myFeature": {
    "title": "我的功能",
    "description": "功能描述"
  }
}
```

### 添加新的内置技能

1. 创建技能目录：

```
server/coapis/agent/skills/my_skill-en/
├── SKILL.md           # 技能文档（英文）
└── scripts/           # 技能脚本
    └── my_script.py
```

2. 编写 SKILL.md：

```markdown
# My Skill

## Description
Brief description of what this skill does.

## Usage
How to use this skill.

## Parameters
- param1: Description
- param2: Description
```

3. 技能会自动被发现（启动时 `SkillsManager` 扫描 `agent/skills/` 目录）。

---

## 调试技巧

### 后端调试

```bash
# 1. 查看容器日志
docker compose logs -f server

# 2. 进入容器
docker exec -it coapis-server bash

# 3. 查看配置文件
cat /opt/coapis/workspaces/default/agent.json
cat /opt/coapis/data/users/users.json

# 4. 测试 API
curl -X POST http://localhost:4200/api/console/chat \
  -H "Content-Type: application/json" \
  -d '{"input": [{"role": "user", "content": "hello"}], "biz_params": {"agent_id": "default"}}'
```

### 前端调试

```bash
# 1. 查看 Vite 开发服务器日志
# npm run dev 的输出

# 2. 浏览器开发者工具
# - Network 标签查看 API 请求
# - Console 标签查看日志
# - Application 标签查看 localStorage

# 3. 清除浏览器缓存
# Ctrl+Shift+Delete 或无痕模式
```

### 常见问题排查

**聊天 400 错误：**
1. 检查 `agent.json` 中 `active_model` 是否有效
2. 检查 `providers.json` 中 Provider 配置
3. 检查前端是否传递了 `agent_id`

**容器启动失败：**
1. `docker compose logs server` 查看错误
2. 检查 `.env` 配置
3. 检查端口冲突

**前端白屏：**
1. 清除浏览器缓存
2. 检查浏览器控制台错误
3. 检查 Nginx 日志：`docker compose logs nginx`

---

## 代码规范

### Python 后端

- 使用 Black 格式化（行宽 88）
- 使用 Ruff 进行 linting
- 使用 PEP 8 命名规范
- 类型注解使用 `typing` 模块
- 日志使用 `logger`（不直接使用 `print`）

### TypeScript 前端

- 使用 ESLint + Prettier
- 组件使用函数式 + Hooks
- 类型定义放在 `types/` 目录
- API 封装放在 `api/modules/`
- 使用 `react-i18next` 做国际化

### Git 提交规范

```
feat: 新功能
fix: 修复 Bug
docs: 文档更新
style: 代码格式调整
refactor: 重构
test: 测试相关
chore: 其他改动
```

---

## 测试

### 后端测试

```bash
# 运行所有测试
cd server/coapis
python -m pytest tests/ -v

# 运行特定测试
python -m pytest tests/test_auth.py -v

# 生成覆盖率报告
python -m pytest tests/ --cov=coapis --cov-report=html
```

### 前端测试

```bash
# 运行测试
cd client
npm test

# 运行特定测试
npm test -- test_auth.tsx
```

### E2E 测试

```bash
# 运行端到端测试
cd scripts
python e2e_test.py
```

---

## 发布流程

1. 更新 `CHANGELOG.md`
2. 更新版本号（`server/coapis/__version__.py`）
3. 创建 Git 标签：`git tag -a v0.x.0 -m "Release v0.x.0"`
4. 推送标签：`git push origin v0.x.0`
5. 在 GitHub 创建 Release

---

## 贡献流程

1. Fork 本项目
2. 创建特性分支：`git checkout -b feat/my-feature`
3. 提交更改：`git commit -am 'feat: add my feature'`
4. 推送分支：`git push origin feat/my-feature`
5. 提交 Pull Request

详细流程请参阅 [CONTRIBUTING.md](../../CONTRIBUTING.md)。
