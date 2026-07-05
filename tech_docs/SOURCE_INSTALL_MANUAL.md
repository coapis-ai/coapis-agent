# CoApis-agent 源码安装帮助手册

> **版本**: 基于当前代码分析（`master` 分支，commit `57ac222`）
> **生成时间**: 2026-07-02
> **作者**: Paw
> **状态**: 📋 安装前必读 — 仅分析，未修改任何代码

---

## 一、环境要求

### 1.1 系统要求

| 组件 | 最低要求 | 推荐配置 | 说明 |
|------|---------|---------|------|
| Python | 3.10 | **3.11** | Dockerfile 使用 `python:3.11-slim`，3.12 未验证 |
| Node.js | 16.x | **18.x+** | 前端构建需要 |
| npm | 8.x | **10.x+** | 前端依赖安装 |
| Git | 2.x | 最新 | 代码克隆 |
| Docker | 20.10+ | 最新 | 容器部署（可选） |
| Docker Compose | v2 | 最新 | 容器编排（可选） |
| 磁盘空间 | 10GB | 20GB+ | 含依赖、前端构建、运行时数据 |
| 内存 | 4GB | 8GB+ | 编译 + 运行时 |

### 1.2 操作系统兼容性

| 系统 | 状态 | 备注 |
|------|------|------|
| Linux (Ubuntu/Debian) | ✅ 完全支持 | 首选平台 |
| Linux (CentOS/RHEL) | ✅ 完全支持 | 需安装 EPEL 源 |
| macOS | ✅ 完全支持 | 需安装 Xcode CLI Tools |
| Windows | ⚠️ 部分支持 | 需要 WSL2，原生 Windows 未验证 |

### 1.3 系统依赖（Linux）

Dockerfile 中预装的系统包：

```bash
# 基础编译工具
build-essential
libssl-dev
libffi-dev

# 多媒体处理
ffmpeg

# 系统工具
curl
git
xclip

# Playwright 浏览器依赖（可选，仅需要浏览器自动化时）
libnss3
libnspr4
libatk1.0-0
libatk-bridge2.0-0
libcups2
libdrm2
libdbus-1-3
libxkbcommon0
libxcomposite1
libxdamage1
libxfixes3
libxrandr2
libgbm1
libpango-1.0-0
libcairo2
libasound2
libatspi2.0-0
libwayland-client0
```

**安装命令**（Ubuntu/Debian）：
```bash
sudo apt-get update && sudo apt-get install -y \
    build-essential libssl-dev libffi-dev \
    curl git ffmpeg xclip
```

---

## 二、安装方式总览

CoApis 提供三种安装方式：

### 2.1 方式一：源码安装（pip install -e .）

**适用场景**: 本地开发、调试、自定义部署

```bash
cd /path/to/coapis-agent/server
pip install -e .
```

**优点**: 可编辑模式，修改代码立即生效
**缺点**: 需要手动处理依赖冲突

### 2.2 方式二：Docker 源码构建

**适用场景**: 生产部署、标准化环境

```bash
cd /path/to/coapis-agent/docker
docker compose -f docker-compose.build.yml up -d --build
```

**优点**: 环境隔离、可复现
**缺点**: 构建时间长（约 10-20 分钟）

### 2.3 方式三：一键安装脚本

**适用场景**: 快速体验、标准部署

```bash
curl -fsSL https://get.coapis.com | bash
# 或
bash install.sh --source
```

**优点**: 自动化程度高
**缺点**: 自定义能力有限

---

## 三、源码安装详细步骤

### 3.1 获取代码

```bash
# 方式一：从 GitHub 克隆
git clone https://github.com/coapis/coapis.git
cd coapis

# 方式二：从 Gitee 克隆（国内推荐）
git clone https://gitee.com/ouerlai/coapis-agent.git
cd coapis-agent
```

### 3.2 目录结构说明

```
coapis-agent/
├── server/                    ← 后端 Python 项目（核心）
│   ├── coapis/               ← 主 Python 包
│   │   ├── cli/              ← CLI 命令（coapis init, coapis app 等）
│   │   ├── agents/           ← 智能体管理
│   │   ├── app/              ← 应用层（渠道、路由、消息处理）
│   │   ├── config/           ← 配置管理
│   │   ├── providers/        ← AI 提供商（OpenAI、DashScope 等）
│   │   ├── skills/           ← 内置技能
│   │   ├── tools/            ← 工具集
│   │   ├── security/         ← 安全模块
│   │   ├── constant.py       ← 全局常量（WORKING_DIR 等）
│   │   └── __init__.py       ← 入口（加载环境变量）
│   ├── pyproject.toml        ← 包定义（35 个直接依赖）
│   ├── requirements.txt      ← 完整依赖（48 个，含补充依赖）⚠️ 注意差异
│   ├── setup.py              ← setuptools 入口
│   └── deploy/               ← 部署脚本
│       ├── Dockerfile        ← 源码构建 Dockerfile
│       ├── entrypoint.sh     ← 容器入口脚本
│       └── init_workspace.sh ← 工作区初始化
├── client/                    ← 前端 React 项目
│   ├── src/                  ← 源代码
│   ├── dist/                 ← 构建产物（被 Dockerfile 复制到后端）
│   └── package.json          ← 前端依赖
├── docker/                    ← Docker 配置
│   ├── docker-compose.build.yml  ← 源码构建编排
│   ├── docker-compose.yml        ← 标准部署编排
│   └── .env.example            ← 环境变量模板
└── install.sh                 ← 一键安装脚本
```

### 3.3 安装 Python 依赖

#### 3.3.1 标准安装（推荐）

```bash
cd server
pip install -e .
```

这会安装 `pyproject.toml` 中声明的 **35 个直接依赖**。

#### 3.3.2 完整安装（包含补充依赖）

```bash
cd server
pip install -e .
pip install -r requirements.txt
```

⚠️ **注意**: `requirements.txt` 包含 **48 个依赖**，比 `pyproject.toml` 多 13 个。
详见 [第五节：依赖差异分析](#五依赖差异分析)。

#### 3.3.3 按需安装渠道依赖

如果你只需要特定渠道，可以只安装对应依赖：

```bash
# 仅钉钉
pip install dingtalk-stream alibabacloud-dingtalk alibabacloud-tea-openapi

# 仅飞书
pip install lark-oapi

# 仅 Discord
pip install discord-py

# 仅企业微信
pip install wecom-aibot-python-sdk==1.0.2

# 仅 Telegram
pip install python-telegram-bot

# 仅 Matrix
pip install matrix-nio

# 浏览器自动化
pip install playwright browser-use
```

### 3.4 构建前端（可选）

前端构建产物会被复制到 `coapis/console/` 目录，供后端提供 Web UI。

```bash
cd client
npm install          # 安装前端依赖
npm run build        # 构建生产版本
```

⚠️ **注意**: 如果不需要 Web UI，可以跳过此步骤。CLI 模式不依赖前端。

### 3.5 初始化系统

安装完成后，运行初始化命令：

```bash
# 方式一：交互式初始化（推荐首次使用）
coapis init

# 方式二：快速初始化（使用默认值）
coapis init --defaults --accept-security
```

初始化流程：
1. 创建目录结构（`WORKING_DIR/system/`, `workspaces/`, `agents/`, `skills/` 等）
2. 创建 `config.json` 配置文件
3. 创建 `HEARTBEAT.md` 心跳配置
4. 创建默认智能体（`global_default`）
5. 创建 QA 智能体（`global_qa_agent`）
6. 初始化技能池
7. 配置 AI 提供商（交互式）
8. 配置渠道（交互式）

### 3.6 配置环境变量

创建 `.env` 文件在项目根目录（`coapis-agent/.env`）：

```bash
# ── 基础配置 ──
COAPIS_WORKING_DIR=/data/coapis
COAPIS_LOG_LEVEL=info
COAPIS_VERSION=0.8.26-dev

# ── AI 提供商 ──
OPENAI_API_KEY=sk-xxxxxxxx
OPENAI_API_BASE=https://api.openai.com/v1

# ── 渠道配置（按需） ──
# DINGTALK_APP_KEY=xxx
# DINGTALK_APP_SECRET=xxx
```

### 3.7 启动服务

```bash
# 方式一：CLI 启动
coapis app start

# 方式二：直接 Python 启动
cd server
python -m coapis app start

# 方式三：uvicorn 直接启动
cd server
uvicorn coapis.app.main:app --host 0.0.0.0 --port 8000
```

---

## 四、环境变量参考

### 4.1 核心环境变量

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `COAPIS_WORKING_DIR` | 推荐 | `~/.coapis` | 工作目录（运行时数据存储） |
| `COAPIS_LOG_LEVEL` | 否 | `info` | 日志级别 |
| `COAPIS_VERSION` | 否 | `0.0.0-dev` | 版本号 |
| `COAPIS_SERVER_PORT` | 否 | `4200` | 服务端口（Docker 映射） |

### 4.2 AI 提供商环境变量

| 变量 | 必填 | 说明 |
|------|------|------|
| `OPENAI_API_KEY` | 是* | OpenAI 兼容 API Key |
| `OPENAI_API_BASE` | 否 | API 地址（支持 vLLM、Ollama 等） |
| `DASHSCOPE_BASE_URL` | 否 | 阿里云灵积 API 地址 |
| `COAPIS_LLM_MAX_CONCURRENT` | 否 | 最大并发数（默认 10） |
| `COAPIS_LLM_MAX_RETRIES` | 否 | 最大重试次数（默认 3） |

*至少需要一个 AI 提供商配置

### 4.3 渠道环境变量

| 渠道 | 变量 | 说明 |
|------|------|------|
| 钉钉 | `DINGTALK_APP_KEY` / `DINGTALK_APP_SECRET` | 钉钉机器人凭证 |
| 飞书 | `LARK_APP_ID` / `LARK_APP_SECRET` | 飞书应用凭证 |
| Discord | `DISCORD_BOT_TOKEN` | Discord Bot Token |
| 企业微信 | 在 `envs.json` 中配置 | 企业微信凭证 |
| Telegram | `TELEGRAM_BOT_TOKEN` | Telegram Bot Token |

---

## 五、依赖差异分析 ⚠️

### 5.1 pyproject.toml vs requirements.txt 差异

**这是源码安装最大的坑**。两个文件声明的依赖不一致：

| 依赖 | pyproject.toml | requirements.txt | 风险等级 |
|------|---------------|------------------|---------|
| `python-frontmatter` | ❌ 缺失 | ✅ `>=1.3.0` | 🔴 **P0** |
| `fastapi` | ❌ 缺失 | ✅ `>=0.100.0,<1.0.0` | 🔴 **P0** |
| `pydantic` | ❌ 缺失 | ✅ `>=2.0.0,<3.0.0` | 🔴 **P0** |
| `pydantic-settings` | ❌ 缺失 | ✅ `>=2.0.0` | 🔴 **P0** |
| `starlette` | ❌ 缺失 | ✅ `>=0.27.0` | 🔴 **P0** |
| `click` | ❌ 缺失 | ✅ `>=8.0.0` | 🔴 **P0** |
| `aiohttp` | ❌ 缺失 | ✅ `>=3.9.0` | 🔴 **P0** |
| `websockets` | ❌ 缺失 | ✅ `>=13.0` | 🔴 **P0** |
| `mcp` | ❌ 缺失 | ✅ `>=1.0.0` | 🔴 **P0** |
| `rich` | ❌ 缺失 | ✅ `>=13.0.0` | 🟡 **P1** |
| `psutil` | ❌ 缺失 | ✅ `>=6.0.0` | 🟡 **P1** |
| `orjson` | ❌ 缺失 | ✅ `>=3.9` | 🟡 **P1** |
| `alibabacloud-tea-util` | ❌ 缺失 | ✅ `>=0.3.0` | 🟡 **P1** |
| `anthropic` | ❌ 缺失 | ✅ `>=0.10.0` | 🟡 **P1** |
| `openai` | ❌ 缺失 | ✅ `>=2.0.0,<=2.33.0` | 🟡 **P1** |

### 5.2 影响分析

**仅执行 `pip install -e .`（基于 pyproject.toml）的后果**：

| 缺失依赖 | 影响功能 | 症状 |
|---------|---------|------|
| `fastapi` + `starlette` | Web API 服务 | `ModuleNotFoundError: No module named 'fastapi'` |
| `pydantic` | 数据验证 | `ModuleNotFoundError: No module named 'pydantic'` |
| `click` | CLI 命令 | `coapis` 命令无法运行 |
| `python-frontmatter` | 技能管理 | `ModuleNotFoundError: No module named 'frontmatter'` |
| `aiohttp` | 部分渠道/工具 | 运行时异步 HTTP 请求失败 |
| `mcp` | MCP 协议支持 | MCP 工具无法加载 |
| `websockets` | WebSocket 支持 | 流式输出可能失败 |

### 5.3 推荐安装顺序

```bash
cd server

# 第一步：安装 pyproject.toml 声明的依赖
pip install -e .

# 第二步：安装 requirements.txt 中的补充依赖
pip install fastapi pydantic pydantic-settings starlette click \
    aiohttp websockets mcp rich psutil orjson \
    alibabacloud-tea-util anthropic openai \
    python-frontmatter
```

---

## 六、已知问题与解决方案

### 6.1 🔴 P0: pyproject.toml 缺失关键依赖

**问题**: `pyproject.toml` 的 `dependencies` 列表不完整，缺失 `fastapi`、`pydantic`、`click` 等核心依赖。

**根因**: 这些依赖被 `agentscope` 传递依赖覆盖，但版本不可控。

**症状**: `pip install -e .` 后，`coapis` 命令可能因版本不匹配而失败。

**解决方案**:
```bash
# 方案一：手动安装缺失依赖（推荐）
pip install fastapi pydantic pydantic-settings starlette click

# 方案二：使用 requirements.txt
pip install -r requirements.txt

# 方案三（长期修复）: 在 pyproject.toml 中补充缺失依赖
# 需要修改代码，此处不展开
```

### 6.2 🔴 P0: wecom-aibot-python-sdk 可能不可用

**问题**: `wecom-aibot-python-sdk==1.0.2` 锁定精确版本，且可能是私有包。

**根因**: 企业微信 SDK 可能不在公共 PyPI 上。

**症状**: `pip install` 时报 `ERROR: Could not find a version that satisfies the requirement wecom-aibot-python-sdk==1.0.2`。

**解决方案**:
```bash
# 方案一：如果你不需要企业微信渠道，跳过此依赖
# 从 pyproject.toml 中移除该依赖（需修改代码）

# 方案二：如果有私有 PyPI 源
pip install --extra-index-url https://your-private-pypi/simple wecom-aibot-python-sdk==1.0.2

# 方案三：从本地安装
pip install /path/to/wecom-aibot-python-sdk-1.0.2.tar.gz
```

### 6.3 🟡 P1: anyio 版本约束过严

**问题**: `anyio>=4.0.0,<4.13.0` 排除了 4.13.0+ 版本。

**根因**: `anyio 4.13.0` 存在 `_deliver_cancellation` busy-loop bug（CoApis#2632）。

**症状**: 如果其他依赖（如 `httpx`、`httpcore`）升级并要求 `anyio>=4.13.0`，安装会失败。

**解决方案**:
```bash
# 方案一：等待 anyio 修复 bug 后更新约束
# 方案二：手动安装特定版本
pip install "anyio>=4.0.0,<4.13.0"

# 方案三：如果其他依赖强制需要 anyio>=4.13.0
# 需要测试 4.13.0+ 是否真的有问题，可能已修复
pip install anyio --upgrade
```

### 6.4 🟡 P1: agentscope 精确版本锁定

**问题**: `agentscope==1.0.19.post1` 和 `agentscope-runtime==1.1.4` 锁定精确版本。

**症状**: 如果其他依赖与这些精确版本不兼容，安装会失败。

**解决方案**:
```bash
# 如果遇到版本冲突，尝试放宽版本
pip install "agentscope>=1.0.0,<2.0.0" "agentscope-runtime>=1.1.0,<2.0.0"
```

### 6.5 🟡 P1: Python 3.12 兼容性

**问题**: `pyproject.toml` 声明 `requires-python = ">=3.10,<3.14"`，但 Dockerfile 使用 `python:3.11-slim`。

**症状**: Python 3.12 环境下，某些依赖（如 `mss`、`keyring`）可能有兼容性问题。

**解决方案**:
```bash
# 推荐：使用 Python 3.11
# 如果必须使用 Python 3.12，先测试依赖安装
python3.11 -m venv venv
source venv/bin/activate
pip install -e .
```

### 6.6 🟢 P2: 前端构建产物依赖

**问题**: Dockerfile 中 `COPY client/dist ./coapis/console` 依赖预构建的前端产物。

**症状**: 如果 `client/dist/` 不存在或为空，Web UI 无法访问。

**解决方案**:
```bash
cd client
npm install
npm run build
# 然后执行 Docker 构建或 pip install
```

### 6.7 🟢 P2: WORKING_DIR 权限问题

**问题**: `COAPIS_WORKING_DIR` 目录需要读写权限，且子目录（`.secret/`）需要严格权限。

**症状**: 运行时 `PermissionError` 或 `FileNotFoundError`。

**解决方案**:
```bash
# 创建工作目录
mkdir -p /data/coapis
chmod 755 /data/coapis

# 如果以非 root 用户运行
chown -R $(whoami):$(whoami) /data/coapis
```

---

## 七、Docker 源码构建详细步骤

### 7.1 前置条件

```bash
# 确认 Docker 和 Docker Compose 已安装
docker --version
docker compose version
```

### 7.2 构建命令

```bash
cd docker

# 构建并启动
docker compose -f docker-compose.build.yml up -d --build

# 查看日志
docker compose -f docker-compose.build.yml logs -f server

# 停止服务
docker compose -f docker-compose.build.yml down
```

### 7.3 Docker 环境变量

创建 `docker/.env` 文件：

```bash
# 工作目录（宿主机路径 → 容器内路径）
COAPIS_WORKING_DIR=/data/coapis
COAPIS_SERVER_PORT=4200

# 版本
COAPIS_VERSION=0.8.26-dev

# AI 提供商
OPENAI_API_KEY=sk-xxxxxxxx
OPENAI_API_BASE=https://api.openai.com/v1

# 可选：安装浏览器自动化
# COAPIS_INSTALL_BROWSER=1
```

### 7.4 Docker 构建注意事项

1. **构建上下文**: Dockerfile 的 build context 是项目根目录（`..`），不是 `server/`
2. **前端产物**: Dockerfile 会复制 `client/dist/` 到容器内，确保先构建前端
3. **数据持久化**: `COAPIS_WORKING_DIR` 映射到宿主机，数据不会因容器删除而丢失
4. **构建时间**: 首次构建约 10-20 分钟（含系统包安装 + Python 依赖 + 前端）

---

## 八、安装后验证

### 8.1 验证 CLI 安装

```bash
# 检查 coapis 命令是否可用
coapis --version

# 检查子命令
coapis --help
```

### 8.2 验证初始化

```bash
# 查看工作目录结构
ls -la $COAPIS_WORKING_DIR/
ls -la $COAPIS_WORKING_DIR/system/
ls -la $COAPIS_WORKING_DIR/system/templates/

# 检查配置文件
cat $COAPIS_WORKING_DIR/system/config.json

# 检查智能体
ls -la $COAPIS_WORKING_DIR/agents/
```

### 8.3 验证服务启动

```bash
# 启动服务
coapis app start

# 在另一个终端测试健康检查
curl http://localhost:8000/api/health

# 预期响应
# {"status": "healthy"}
```

### 8.4 验证 AI 连接

```bash
# 测试 AI 提供商连接
coapis doctor

# 查看诊断报告
# - Python 版本
# - 依赖完整性
# - AI 提供商连接
# - 渠道配置
# - 磁盘空间
```

---

## 九、常见问题排查

### 9.1 pip install 失败

**症状**: `ERROR: Cannot install ... because these package versions have conflicting dependencies`

**排查步骤**:
1. 检查 Python 版本：`python --version`（推荐 3.11）
2. 检查 pip 版本：`pip --version`（推荐 23.x+）
3. 查看冲突详情：`pip install -e . --dry-run`
4. 尝试单独安装冲突包：`pip install <冲突包名>`

**常见冲突**:
- `anyio` 版本冲突 → 手动指定 `pip install "anyio>=4.0.0,<4.13.0"`
- `wecom-aibot-python-sdk` 找不到 → 跳过或使用私有源
- `frontmatter` vs `pyyaml` → 使用 `python-frontmatter`（已在 requirements.txt 中修复）

### 9.2 coapis 命令找不到

**症状**: `command not found: coapis`

**排查步骤**:
1. 确认安装成功：`pip show coapis-agent`
2. 检查 PATH：`which coapis`
3. 虚拟环境：确认已 `source venv/bin/activate`
4. 手动运行：`python -m coapis --help`

### 9.3 前端构建失败

**症状**: `npm run build` 报错

**排查步骤**:
1. 检查 Node.js 版本：`node --version`（推荐 18.x+）
2. 清理缓存：`rm -rf node_modules package-lock.json`
3. 重新安装：`npm install`
4. 检查 TypeScript 版本：`npx tsc --version`

### 9.4 Docker 构建失败

**症状**: `docker compose -f docker-compose.build.yml up -d --build` 报错

**排查步骤**:
1. 检查 Docker 版本：`docker --version`
2. 检查磁盘空间：`df -h`
3. 检查前端产物：`ls client/dist/`
4. 查看构建日志：`docker compose -f docker-compose.build.yml build`

### 9.5 运行时导入错误

**症状**: `ModuleNotFoundError: No module named 'xxx'`

**排查步骤**:
1. 确认依赖已安装：`pip show xxx`
2. 检查 PYTHONPATH：`echo $PYTHONPATH`（Docker 中设为 `/app`）
3. 检查虚拟环境：`which python`（确认是预期环境）
4. 重新安装：`pip install -e .`

---

## 十、安装检查清单

### 10.1 安装前

- [ ] Python 3.10-3.13（推荐 3.11）
- [ ] Node.js 18+（如果需要前端）
- [ ] Git
- [ ] 系统依赖（build-essential 等）
- [ ] 磁盘空间 ≥ 10GB
- [ ] 内存 ≥ 4GB

### 10.2 安装中

- [ ] 代码克隆成功
- [ ] `pip install -e .` 成功
- [ ] 补充依赖安装成功（fastapi、pydantic 等）
- [ ] 前端构建成功（如果适用）
- [ ] `coapis` 命令可用

### 10.3 安装后

- [ ] `coapis init` 成功
- [ ] `COAPIS_WORKING_DIR` 目录创建成功
- [ ] `config.json` 生成成功
- [ ] 环境变量配置正确
- [ ] `coapis app start` 成功
- [ ] 健康检查通过
- [ ] AI 提供商连接正常

---

## 十一、附录

### 11.1 依赖关系图（简化）

```
coapis-agent
├── agentscope==1.0.19.post1          ← 核心框架
│   ├── python-frontmatter             ← 传递依赖
│   ├── pydantic                       ← 传递依赖
│   └── ...
├── agentscope-runtime==1.1.4         ← 运行时
├── fastapi                           ← Web 框架（需手动安装）
├── uvicorn                           ← ASGI 服务器
├── click                             ← CLI 框架（需手动安装）
├── httpx                             ← HTTP 客户端
├── apscheduler                       ← 定时任务
├── questionary                       ← 交互式 CLI
├── mss                               ← 截图
├── pillow                            ← 图像处理
├── cryptography                      ← 加密
├── bcrypt                            ← 密码哈希
├── pyyaml                            ← YAML 处理
└── [渠道依赖]                        ← 按需安装
    ├── dingtalk-stream               ← 钉钉
    ├── lark-oapi                     ← 飞书
    ├── discord-py                    ← Discord
    ├── wecom-aibot-python-sdk        ← 企业微信
    ├── python-telegram-bot           ← Telegram
    └── matrix-nio                    ← Matrix
```

### 11.2 端口参考

| 服务 | 默认端口 | 环境变量 |
|------|---------|---------|
| CoApis Server | 8000 | `COAPIS_SERVER_PORT`（Docker 映射） |
| 健康检查 | 8000 | `/api/health` |
| Web UI | 8000 | `/console` |

### 11.3 目录权限参考

| 目录 | 权限 | 说明 |
|------|------|------|
| `WORKING_DIR/` | 755 | 工作目录 |
| `WORKING_DIR/.secret/` | 700 | 密钥存储 |
| `WORKING_DIR/.secret/envs.json` | 600 | 环境变量持久化 |
| `WORKING_DIR/logs/` | 755 | 日志目录 |
| `WORKING_DIR/media/` | 755 | 媒体文件 |

---

*基于 CoApis-agent 源码分析整理，未修改任何代码*
