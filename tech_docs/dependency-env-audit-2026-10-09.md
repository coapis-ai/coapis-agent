# 环境依赖体检报告（2026-10-09）

> 方法：AST 扫描 `server/coapis` 全部 import → 与 `pyproject.toml` / `requirements.txt` / 容器实际安装集 三方对账；并在 dev 容器内做"缺失依赖"模拟实验验证。
> 权威树：`coapis-agent/server/`（前端 `coapis-agent/client/`，企业版 `coapis-pro/`）。

## 一、依赖文件清单与角色

| 文件 | 谁在用 | 状态 |
|---|---|---|
| `server/pyproject.toml` | `install.sh`(pip install -e .)、Dockerfile builder(`pip install .`)、Dockerfile.enterprise(`uv pip install .`) | **权威**，最全 |
| `server/requirements.txt` | CONTRIBUTING.md、`.github/workflows/backend-ci.yml`、`docs/SOURCE_INSTALL_MANUAL.md` | **陈旧**（2026-07-02 生成，头部自称"与 pyproject 同步维护"） |
| `server/constraints.txt` | **没有任何安装路径引用它** | 死文件（安全约束从未生效） |
| `server/deploy/Dockerfile` | min/full 镜像 | 额外装 python-docx / playwright / browser-use / 渠道 SDK，未应用 constraints |
| `client/package.json` | 前端构建 | 缺 1 个直接 import 的包 |
| `coapis-pro/requirements.txt` | 无人使用（企业版走 `base-requirements.locked.txt` + wheelhouse） | 陈旧且缺 2 个模块级 import |

## 二、P0：`pip install -r requirements.txt` 装出来的环境起不来

`requirements.txt` 相对 `pyproject.toml` **缺 2 个包**：`sqlalchemy>=2.0`、`alembic>=1.13`。

这两个是**启动硬依赖**，已在 dev 容器内做缺失模拟实验证实：

1. `coapis/app/_app.py:363-370` 启动时调用 `RepositoryFactory.initialize()`
   → `coapis/foundation/repository_factory.py:100` `from .db.migrate import run_migrations`
   → `coapis/foundation/db/migrate.py:15` `from alembic import command`
   实验结果：`STARTUP FAIL: ImportError ... no alembic`（应用无法启动）

2. `coapis/agents/memory/__init__.py:26` 用 `try/except ImportError` 兜住 `reme_light_memory_manager`
   → 该模块 `from sqlalchemy import ...`（模块级）
   实验结果：ImportError 被吞掉，`ReMeLightMemoryManager = None`
   → **记忆系统静默失效**（比崩溃更糟：产品核心能力没了，日志只有一条 debug）

`sqlalchemy` 在代码里被 import 68 处（`foundation/db/engine.py`、`foundation/db/models/*`、`file_ledger.py`、`memory_timeline_impl.py`、`repository_factory.py` 等）。

**结论：任何按 `requirements.txt` 装的新环境，要么起不来，要么记忆/台账/文件账本全废。**

## 三、P1：`constraints.txt` 从未生效

`server/constraints.txt`（2026-05-08 依据 pip-audit 生成，锁 authlib/lxml/mistune/python-multipart/jupyter-server 的 CVE 版本）在全仓库无任何引用：
Dockerfile builder 只 `COPY server/pyproject.toml server/setup.py`，`pip install .` 不带 `-c`；`install.sh` 只有 `pip install -e .`。
→ 安全约束形同注释。

## 四、P1：CI 是装饰性的

`.github/workflows/backend-ci.yml`：
```
pip install -r server/requirements.txt 2>/dev/null || true
python -m pytest tests/ -v --cov=. ... 2>/dev/null || echo "No tests found yet"
```
- 装的是缺 sqlalchemy/alembic 的 requirements.txt；
- 安装失败被 `|| true` 吞掉；
- 测试失败被 `|| echo "No tests found yet"` 吞掉。
→ CI 永远绿，且从未真正跑过测试。

## 五、P1：文档描述与现状相反

`docs/SOURCE_INSTALL_MANUAL.md` §5.1/§6.1 断言 `pyproject.toml` 缺 `fastapi/pydantic/click/aiohttp/websockets/mcp/rich/psutil/orjson/python-frontmatter/anthropic/openai` 等 15 项，并给出"两步安装法"。
**现状：这些全部已在 pyproject.toml 里声明**。文档描述的是旧版本，会误导新环境搭建（按它装会多装一遍）。

## 六、P2：懒加载依赖未声明为 extras（功能静默降级）

代码里这些 import 全部是函数内 `try/except ImportError`，缺失不崩，但功能不可用；且**没有任何声明**，新环境装不到：

| 包 | 代码位置 | 缺失后果 |
|---|---|---|
| `pymupdf4llm` | `agents/tools/doc_reader.py:57` | PDF 解析降级到 pdftotext |
| `python-pptx` | `agents/tools/doc_reader.py:113` | PPTX 读取不可用 |
| `openpyxl` | `agents/tools/doc_reader.py:129` | XLSX 读取不可用 |
| `duckduckgo_search` | `agents/tools/web_search.py:300` | DDGS 搜索后端不可用（容器内实测未安装） |
| `tavily` | `agents/tools/web_search.py:324` | Tavily 后端不可用（容器内实测未安装） |
| `markdown-it-py` | `app/channels/matrix/channel.py:119` | Matrix 富文本降级 |
| `linkify-it-py` | `app/channels/matrix/channel.py:135` | Matrix 裸链接不自动转链接 |
| `browser-use` | `agents/core.py:636`（仅 Dockerfile 装） | 源码安装无浏览器工具 |
| `python-docx` | 仅 Dockerfile 装（`doc_reader` 走 subprocess/懒加载） | 源码安装无 Word 生成 |
| `typing_extensions` | `agents/schema.py:22`（模块级直接 import） | 靠 pydantic 传递依赖兜住，未显式声明 |

## 七、P2：requirements.txt 与 pyproject 的其余差异

- 仅在 requirements.txt（12 项）：`numpy`（代码里 0 处 import，可删）、`playwright`、`wecom-aibot-python-sdk`、9 个渠道 SDK。
  - 渠道 SDK 在 pyproject 已移到 `[channels]` extras（pyproject 注释写明"渠道 SDK 已移至 optional-dependencies"），requirements.txt 仍当核心装 → 两文件语义不一致。
  - `wecom-aibot-python-sdk` 在 requirements.txt 是**未注释的活跃行**（位于"可选依赖"标题下）。实测它在公共 PyPI 上（1.0.2），所以不会装失败；但 pyproject 注释"私有包，不在公共 PyPI"是**错的**。
- 仅在 pyproject（2 项）：`sqlalchemy`、`alembic`（见 P0）。

## 八、前端

`client/src/utils/preloadLanguages.ts:16` 直接 `import { PrismLight } from 'react-syntax-highlighter'`，但 `package.json` **未声明**它 —— 目前靠 `@agentscope-ai/chat` 的传递依赖（`^15.6.6`）恰好带进来。传递依赖一变，`npm run build` 直接挂。建议显式声明。

`@enterprise` / `@coapis-c2a/renderer` 是 vite alias，不是缺依赖。

## 九、企业版（coapis-pro）

- 权威依赖源是 `coapis-pro/docker/build/wheelhouse-offline-py311/base-requirements.locked.txt`（220 行精确锁定，含 SQLAlchemy 2.0.54 / alembic 1.20.0 / psycopg2-binary / weaviate-client 4.6.5 / langchain-weaviate 0.0.6）—— 这条路径是健康的。
- `coapis-pro/requirements.txt` 无人使用，且缺 2 个**模块级 import** 的包：
  - `weaviate-client`（`coapis/enterprise/repository_weaviate.py:19` 模块级 `import weaviate`）
  - `langchain-weaviate`（`coapis/enterprise/knowledge/vector_store_manager.py:20` 模块级 import）
  → 谁按这个文件装企业版，企业插件注册即崩。

## 十、修复方案（未改代码，等拍板）

| # | 文件 | 改动 | 级别 |
|---|---|---|---|
| F1 | `server/requirements.txt` | 补 `sqlalchemy>=2.0`、`alembic>=1.13`、`typing_extensions>=4.6`；渠道 SDK 移入注释的可选块（与 pyproject 对齐）；删 `numpy`；`playwright`/`wecom` 移入注释可选块；新增 documents/search/matrix/browser 注释块 | **P0** |
| F2 | `server/pyproject.toml` | 核心补 `typing_extensions>=4.6`；`[browser]` 补 `browser-use`；新增 `[documents]`/`[search]`/`[matrix]` extras；修正 wecom"私有包"注释 | P1 |
| F3 | `server/deploy/Dockerfile` | builder 阶段 `COPY server/constraints.txt` + `pip install -c constraints.txt .`；full 阶段补 documents extras | P1 |
| F4 | `install.sh` | `pip install -c server/constraints.txt -e .` | P1 |
| F5 | `.github/workflows/backend-ci.yml` | 改 `pip install -e ".[dev]"`，去掉 `|| true` 与 `|| echo "No tests found yet"`（CI 才真正有效） | P1 |
| F6 | `docs/SOURCE_INSTALL_MANUAL.md` | §5.1/§6.1 过时表格改写为现状（pyproject 已完整，单文件安装即可） | P1 |
| F7 | `client/package.json` | 显式声明 `react-syntax-highlighter` | P2 |
| F8 | `coapis-pro/requirements.txt` | 补 `weaviate-client`、`langchain-weaviate`；或标注"已废弃，权威源=locked.txt" | P2 |

### 决策点

- **D1** requirements.txt 定位：(A) 与 pyproject 完全镜像（推荐，单文件安装=最小可用环境）／(B) 保持"全量超集"（渠道全装，CI 更省事，但两文件语义长期分叉）
- **D2** 渠道 SDK：随 D1 决定。选 A 则 CI 需 `.[dev,channels]`
- **D3** CI 是否改为"真失败"（推荐是，否则 CI 无意义）
- **D4** coapis-pro/requirements.txt：修 vs. 标废弃

## 十一、实施记录（2026-10-09，用户"按照推荐修正"后执行）

拍板结果：**D1=A（完全镜像）／D2=随 A／D3=是（CI 真失败）／D4=标废弃 + 补 2 个缺失包（两者都做）**

| # | 状态 | 实际改动 |
|---|------|---------|
| F1 | ✅ | `server/requirements.txt` 重写为 pyproject 核心逐项镜像（43 项）+ 注释可选块（channels/wecom/browser/documents/search/matrix/local/whisper/sip/sip-livekit/dev）；删 `numpy`（源码 0 import） |
| F2 | ✅ | `server/pyproject.toml` 核心补 `typing_extensions>=4.6`、`tqdm>=4.0`、`sqlalchemy[asyncio]>=2.0`（拉 greenlet）；`[browser]` 补 `browser-use>=0.13.0`；新增 `[documents]`/`[search]`/`[matrix]`；wecom 注释改为"公共 PyPI 可装，实测 1.0.2" |
| F3 | ✅ | Dockerfile builder `COPY server/constraints.txt` + `pip install -c constraints.txt .`；full 阶段补 documents/search/matrix 7 个包 |
| F4 | ✅ | `install.sh` 改 `pip install -c constraints.txt -e .` |
| F5 | ✅ | CI 去 `2>/dev/null`/`|| true`/`|| echo "No tests found yet"`；paths 过滤改 `server/**`；测试命令改为从仓库根跑 4 个单元测试路径（`server/tests/unit` + 3 个文件）；安装改 `-c constraints.txt -e "./server[dev]"` |
| F6 | ✅ | `docs/SOURCE_INSTALL_MANUAL.md` §3.2/§3.3.1/§3.3.2/§5/§6.1 改写为现状 |
| F7 | ✅ | `client/package.json` 显式声明 `react-syntax-highlighter: ^15.6.6`（与 lockfile 顶层实际解析版本一致，避免与 @agentscope-ai/chat 的 ^15 约束冲突） |
| F8 | ✅ | `coapis-pro/requirements.txt` 头部标注"非权威源，权威=locked.txt"，并补 `weaviate-client==4.6.5`、`langchain-weaviate==0.0.6`（pip 解析验证无冲突） |

### 新增发现（审计后追加，超出 F1-F8）

- **greenlet / tqdm 是启动级 P0**：干净 venv 实测 `pip install -c constraints.txt -e ./server` 后 `import agentscope` 直接 `ImportError`（SQLAlchemy asyncio 缺 greenlet）与 `ModuleNotFoundError`（tqdm）。原审计只建议"文档记录 + CI 补装"，不足以让初始环境可启动，故改为在 pyproject 核心声明（`sqlalchemy[asyncio]` + `tqdm`）。
- **顺带发现的代码 bug（未修，等拍板）**：`server/coapis/token_usage/buffer.py:284` 的 `_save_to_db()` 使用 `time.strftime(...)`，但该文件**未 import time**（模块级只有 asyncio/copy/logging/Path/typing）。干净环境启动冒烟时每次关闭必现：`ERROR _app.py:815 Error stopping TokenUsageManager: name 'time' is not defined`。被 try/except 吞掉 → 最后一次 token 用量落库静默失败。修法：buffer.py 模块级补 `import time`（1 行）。

### 验证结果

| 验证项 | 结果 |
|--------|------|
| pyproject ↔ requirements 核心逐项一致 | 43 / 43，差集为空 |
| pyproject TOML 解析 | 43 核心 + 12 extras，`coapis` 入口正常 |
| 干净 venv 安装 + 启动 | `pip install -c constraints.txt -e ./server` → `import agentscope`/`import coapis` OK，`coapis app --port 4399` 完整启动+优雅关闭 |
| Docker builder 构建 | 成功；镜像内含 alembic 1.20.0 / sqlalchemy 2.1.4 / greenlet 3.5.6 / tqdm 4.70.1 / typing_extensions 4.16.0 |
| Docker full 构建 | 成功；镜像内含 pymupdf / pptx / openpyxl / duckduckgo_search / tavily / markdown_it / linkify_it（此前全缺） |
| dev 部署 | `coapis-agent:latest` 重建 + `compose up -d server` + `restart nginx`；4308/4300 均 200，容器 healthy，日志无 import 错误 |
| CI 测试命令本地实跑 | `python -m pytest server/tests/unit server/tests/test_external_auth.py server/tests/test_foundation.py server/tests/test_plugin_registry_extension.py` → **147 passed / 7 failed**（7 项均为已知存量问题：3 个 session_execution + 1 bcrypt 断言 + 4 个 test_external_auth 路径 bug，非本轮回归） |
| CI lint 基线 | `black --check server/coapis/` → 553 文件需重排；`ruff check` → 9384 错误。**CI 首次运行必红**，需要一次性 `black` + `ruff --fix` 清扫（未拍板，未执行） |

### 未提交

本轮 8 个文件改动**均未 git commit**（`coapis-pro` 非 git 仓库）。提交策略等用户拍板。

