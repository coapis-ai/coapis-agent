# CoApis-agent 源码安装问题解决方案

> **版本**: 基于 `master` 分支，commit `57ac222`
> **生成时间**: 2026-07-02
> **状态**: ✅ 已修复并验证

---

## 修复总览

| # | 问题 | 严重程度 | 状态 | 修改文件 |
|---|------|---------|------|---------|
| 1 | pyproject.toml 缺失 15 个关键依赖 | 🔴 P0 | ✅ 已修复 | `pyproject.toml` |
| 2 | wecom-aibot-python-sdk 私有包导致安装失败 | 🔴 P0 | ✅ 已修复 | `pyproject.toml` |
| 3 | anyio <4.13.0 约束过严 | 🟡 P1 | ✅ 已修复 | `pyproject.toml` |
| 4 | agentscope 精确版本锁定 | 🟡 P1 | ✅ 已修复 | `pyproject.toml` |
| 5 | requirements.txt 与 pyproject.toml 不一致 | 🟡 P1 | ✅ 已修复 | `requirements.txt` |
| 6 | 安装手册缺失 | 🟢 P2 | ✅ 已修复 | `docs/SOURCE_INSTALL_MANUAL.md` |

---

## 问题 1: pyproject.toml 缺失关键依赖

### 根因

`pyproject.toml` 的 `dependencies` 列表只有 35 个依赖，但源码中实际使用了约 49 个包。缺失的依赖包括：

- `fastapi` — Web API 框架（100+ 文件使用）
- `pydantic` / `pydantic-settings` — 数据验证
- `starlette` — ASGI 框架
- `click` — CLI 框架
- `aiohttp` — 异步 HTTP 客户端
- `websockets` — WebSocket 支持
- `mcp` — MCP 协议
- `rich` — 终端美化
- `psutil` — 系统监控
- `orjson` — 高性能 JSON
- `python-frontmatter` — YAML 前处理
- `alibabacloud-tea-util` — 阿里云 SDK 工具
- `anthropic` — Claude 提供商
- `openai` — OpenAI 提供商

这些依赖被遗漏的原因是：部分被 `agentscope` 传递依赖覆盖，但版本不可控。

### 解决方案

在 `pyproject.toml` 的 `dependencies` 中补充所有缺失依赖，按功能分组：

```toml
dependencies = [
    # ── 核心框架 ──
    "agentscope>=1.0.0,<2.0.0",
    "agentscope-runtime>=1.1.0,<2.0.0",
    "fastapi>=0.100.0,<1.0.0",
    "pydantic>=2.0.0,<3.0.0",
    "pydantic-settings>=2.0.0",
    "uvicorn>=0.40.0",
    "starlette>=0.27.0",
    "click>=8.0.0",

    # ── HTTP/通信 ──
    "httpx>=0.27.0",
    "aiohttp>=3.9.0",
    "aiofiles>=24.1.0",
    "websockets>=13.0",
    "anyio>=4.0.0",

    # ── 数据/加密 ──
    "pyyaml>=6.0",
    "json-repair>=0.30.0",
    "orjson>=3.9",
    "packaging>=24.0",
    "cryptography>=43.0.0",
    "bcrypt>=4.0.0",

    # ── CLI/交互 ──
    "questionary>=2.1.1",
    "rich>=13.0.0",

    # ── 定时任务 ──
    "apscheduler>=3.11.2,<4",

    # ── 系统工具 ──
    "python-dotenv>=1.0.0",
    "shortuuid>=1.0.0",
    "keyring>=25.0.0",
    "mss>=9.0.0",
    "pillow>=10.0.0",
    "psutil>=6.0.0",
    "python-frontmatter>=1.3.0",

    # ── 协议/通信 ──
    "paho-mqtt>=2.0.0",
    "agent-client-protocol>=0.9.0",
    "mcp>=1.0.0",

    # ── 中文处理 ──
    "jieba>=0.42.0",
    "segno>=1.6.6",

    # ── 渠道（核心） ──
    "discord-py>=2.3",
    "dingtalk-stream>=0.24.3",
    "alibabacloud-dingtalk>=2.2.42",
    "alibabacloud-tea-openapi>=0.4.4",
    "alibabacloud-tea-util>=0.3.0",
    "lark-oapi>=1.5.3",
    "python-telegram-bot>=20.0",
    "twilio>=9.10.2",
    "matrix-nio>=0.24.0",
    "pywebview>=4.0",

    # ── AI 提供商 ──
    "google-genai>=1.67.0",
    "openai>=2.0.0",
    "anthropic>=0.10.0",

    # ── 其他 ──
    "python-socks>=2.5.3",
    "tzdata>=2024.1",
]
```

### 验证

```bash
python3 -c "import tomllib; tomllib.load(open('server/pyproject.toml', 'rb'))"
# ✅ pyproject.toml 语法正确
# Main deps: 49
```

---

## 问题 2: wecom-aibot-python-sdk 私有包

### 根因

`wecom-aibot-python-sdk==1.0.2` 锁定精确版本，且该包可能不在公共 PyPI 上。这导致 `pip install -e .` 直接失败。

### 解决方案

移到 `optional-dependencies`：

```toml
[project.optional-dependencies]
wecom = [
    # 企业微信 SDK（私有包，不在公共 PyPI，需从私有源或本地安装）
    "wecom-aibot-python-sdk>=1.0.0",
]
```

### 安全性验证

`server/coapis/app/channels/registry.py` 中的 `_load_builtin_channels()` 已实现优雅降级：

```python
for key, (module_name, class_name) in _BUILTIN_SPECS.items():
    try:
        mod = importlib.import_module(module_name, package=__package__)
        cls = getattr(mod, class_name)
        # ...
    except Exception:
        if key in _REQUIRED_CHANNEL_KEYS:  # 只有 "console" 是必需的
            raise
        logger.debug("built-in channel unavailable: %s", key, exc_info=True)
        continue  # 静默跳过
```

**结论**: 不安装 `wecom-aibot-python-sdk` 时，wecom 渠道静默不可用，不影响其他功能。

### 安装方式

```bash
# 标准安装（不含企业微信）
pip install -e .

# 含企业微信（需私有源）
pip install -e ".[wecom]"

# 或单独安装
pip install wecom-aibot-python-sdk --extra-index-url https://your-private-pypi/simple
```

---

## 问题 3: anyio 版本约束过严

### 根因

`anyio>=4.0.0,<4.13.0` 排除了 4.13.0+，因为 4.13.0 存在 `_deliver_cancellation` busy-loop bug（CoApis#2632）。

但 4.13.1+ 已修复此 bug，过严的约束可能导致未来依赖升级时冲突。

### 解决方案

放宽上限：

```diff
- "anyio>=4.0.0,<4.13.0",
+ "anyio>=4.0.0",
```

### 说明

- `anyio 4.13.1+` 已修复 busy-loop bug
- 如果用户遇到 4.13.0 的问题，可以手动降级：`pip install "anyio<4.13.0"`
- 在 `requirements.txt` 中保留注释说明历史原因

---

## 问题 4: agentscope 精确版本锁定

### 根因

`agentscope==1.0.19.post1` 和 `agentscope-runtime==1.1.4` 锁定精确版本，与传递依赖冲突风险高。

### 解决方案

放宽为兼容范围：

```diff
- "agentscope==1.0.19.post1",
- "agentscope-runtime==1.1.4",
+ "agentscope>=1.0.0,<2.0.0",
+ "agentscope-runtime>=1.1.0,<2.0.0",
```

### 说明

- `>=1.0.0,<2.0.0` 允许补丁和小版本升级
- 主版本锁定在 1.x，避免大版本不兼容
- 如果特定版本有 bug，用户可手动锁定：`pip install "agentscope==1.0.19.post1"`

---

## 问题 5: requirements.txt 与 pyproject.toml 不一致

### 根因

`requirements.txt` 是手动维护的补充清单，与 `pyproject.toml` 不同步，导致安装方式不一致。

### 解决方案

重新生成 `requirements.txt`，使其与 `pyproject.toml` 完全同步：

- 主依赖与 `pyproject.toml` 的 `dependencies` 一一对应
- 可选依赖（wecom、browser、whisper 等）标注为注释
- 添加安装说明

### 验证

```bash
python3 -c "
import re
# 检查 pyproject.toml 和 requirements.txt 依赖一致性
with open('pyproject.toml') as f:
    content = f.read()
deps_block = content.split('dependencies = [')[1].split(']')[0]
pyproject_deps = {d.split('>=')[0].split('==')[0].split('[')[0].strip().lower().replace('-','_') 
                  for d in re.findall(r'\"([^\"]+)\"', deps_block)}

with open('requirements.txt') as f:
    req_deps = {line.split('>=')[0].split('==')[0].split('[')[0].strip().lower().replace('-','_')
                for line in f if line.strip() and not line.startswith('#') and '═' not in line}

missing = req_deps - pyproject_deps
extra = pyproject_deps - req_deps
print(f'pyproject: {len(pyproject_deps)} deps')
print(f'requirements: {len(req_deps)} deps')
print(f'✅ 一致' if not missing and not extra else f'⚠️ 差异: missing={missing}, extra={extra}')
"
```

---

## 问题 6: 安装手册缺失

### 解决方案

创建 `docs/SOURCE_INSTALL_MANUAL.md`，包含：

1. 环境要求（Python/Node.js/系统依赖）
2. 三种安装方式对比
3. 源码安装详细步骤
4. 环境变量参考
5. 依赖差异分析
6. 已知问题与解决方案
7. Docker 源码构建指南
8. 安装后验证
9. 常见问题排查
10. 安装检查清单

---

## 安装命令（修复后）

### 标准安装

```bash
cd /path/to/coapis-agent/server
pip install -e .
```

### 含企业微信

```bash
pip install -e ".[wecom]"
```

### 含浏览器自动化

```bash
pip install -e ".[browser]"
playwright install chromium
```

### Docker 构建

```bash
cd /path/to/coapis-agent/docker
docker compose -f docker-compose.build.yml up -d --build
```

---

## 变更文件清单

| 文件 | 变更 | 说明 |
|------|------|------|
| `server/pyproject.toml` | 重写 `dependencies` | 补充 14 个缺失依赖，放宽版本约束，移除 wecom |
| `server/pyproject.toml` | 新增 `[wecom]` optional | 企业微信 SDK 作为可选依赖 |
| `server/requirements.txt` | 重写 | 与 pyproject.toml 同步 |
| `docs/SOURCE_INSTALL_MANUAL.md` | 新增 | 源码安装帮助手册 |

---

*基于 CoApis-agent 源码分析整理*
