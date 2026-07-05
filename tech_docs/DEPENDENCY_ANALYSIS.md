# CoApis-agent 依赖分析报告

> 创建时间: 2026-07-01
> 状态: 待评审
> 作者: Paw

---

## 一、Python 版本分析

### 1.1 声明的 Python 版本要求

```toml
# pyproject.toml
requires-python = ">=3.10,<3.14"
```

### 1.2 Docker 构建版本

```dockerfile
# server/deploy/Dockerfile
FROM python:3.11-slim
```

### 1.3 当前环境版本

```
Python 3.12.7  # 开发环境
Python 3.11    # Docker 构建
```

### 1.4 与 参考实现 对比

| 维度 | CoApis-agent | 参考实现 |
|------|-------------|---------|
| requires-python | >=3.10,<3.14 | >=3.10,<3.14 |
| Docker 基础镜像 | python:3.11-slim | python:3.11-slim |
| 推荐版本 | 3.11 | 3.11 |
| 3.13 兼容 | 需要 audioop-lts | 需要 audioop-lts |

**结论**: 两者 Python 版本要求完全一致，推荐 **Python 3.11** 作为标准版本。

---

## 二、直接依赖分析（源码扫描结果）

### 2.1 分析方法

从 `server/coapis/` 目录下所有 `.py` 文件中提取 `import` 和 `from ... import` 语句，过滤掉 Python 标准库和项目内部模块后，得到**实际使用的第三方包**。

### 2.2 核心问题：pyproject.toml 中缺失的关键依赖

以下包在源码中**实际使用**，但**未在 pyproject.toml 中声明**：

| 包名 | 用途 | 严重性 | 参考实现 是否有 |
|------|------|--------|---------------|
| **fastapi** | Web 框架（100+ 文件使用） | 🔴 致命 | ✅ 有 |
| **pydantic** | 数据验证（64+ 文件使用） | 🔴 致命 | ✅ 有 |
| **click** | CLI 框架（25+ 文件使用） | 🔴 致命 | ✅ 有 |
| **aiohttp** | HTTP 客户端/服务器 | 🟡 高 | ✅ 有 |
| **anthropic** | Claude AI 提供商 | 🟡 高 | ✅ 有 |
| **mcp** | MCP 协议客户端 | 🟡 高 | ✅ 有 |
| **rich** | 终端美化输出 | 🟡 高 | ✅ 有 |
| **frontmatter** | YAML 前处理 | 🟢 中 | ✅ 有 |
| **alibabacloud_tea_util** | 阿里云 SDK 工具类 | 🟢 中 | ✅ 有 |
| **huggingface_hub** | 本地模型下载 | 🟢 中 | ✅ 有 |
| **openai** | OpenAI API 客户端 | 🟢 中 | ✅ 有 |
| **orjson** | 高性能 JSON 序列化 | 🟢 中 | ✅ 有 |
| **psutil** | 系统监控 | 🟢 中 | ✅ 有 |

### 2.3 包名与 import 名不一致（正常现象）

以下包在 pyproject.toml 中已声明，但 import 名不同，属于正常现象：

| pyproject.toml 声明 | import 名 | 说明 |
|---------------------|-----------|------|
| `pillow` | `PIL` | Pillow 包的 import 名 |
| `python-dotenv` | `dotenv` | 标准命名惯例 |
| `paho-mqtt` | `paho` | 标准命名惯例 |
| `matrix-nio` | `nio` | 标准命名惯例 |
| `python-telegram-bot` | `telegram` | 标准命名惯例 |
| `pywebview` | `webview` | 标准命名惯例 |
| `discord-py` | `discord` | 标准命名惯例 |
| `google-genai` | `google` | 标准命名惯例 |
| `pyyaml` | `yaml` | 标准命名惯例 |
| `json-repair` | `json_repair` | 标准命名惯例 |
| `agent-client-protocol` | `acp` | 标准命名惯例 |

### 2.4 源码扫描到的全部第三方包

```
acp              ✅ 已声明 (agent-client-protocol)
agentscope       ✅ 已声明
aibot            ❌ 缺失 (wecom-aibot-python-sdk 的子模块)
aiofiles         ✅ 已声明
aiohttp          ❌ 缺失
alibabacloud_tea_openapi  ✅ 已声明
alibabacloud_tea_util     ❌ 缺失 (参考实现 有)
anthropic        ❌ 缺失 (参考实现 有)
anyio            ✅ 已声明
bcrypt           ✅ 已声明
click            ❌ 缺失 (参考实现 有)
dashscope        ❌ 缺失 (SIP 功能)
dashscope_realtime ❌ 缺失 (SIP 功能)
discord          ✅ 已声明 (discord-py)
dotenv           ✅ 已声明 (python-dotenv)
fastapi          ❌ 缺失 (参考实现 有)
frontmatter      ❌ 缺失 (参考实现 有)
google           ✅ 已声明 (google-genai)
httpx            ✅ 已声明
huggingface_hub  ❌ 缺失 (参考实现 有)
jieba            ✅ 已声明
json_repair      ✅ 已声明
keyring          ✅ 已声明
lark_oapi        ✅ 已声明
mcp              ❌ 缺失
mss              ✅ 已声明
nio              ✅ 已声明 (matrix-nio)
openai           ❌ 缺失 (参考实现 有)
orjson           ❌ 缺失 (参考实现 有)
paho             ✅ 已声明 (paho-mqtt)
psutil           ❌ 缺失 (参考实现 有)
pydantic         ❌ 缺失 (参考实现 有)
questionary      ✅ 已声明
rich             ❌ 缺失 (参考实现 有)
segno            ✅ 已声明
shortuuid        ✅ 已声明
telegram         ✅ 已声明 (python-telegram-bot)
uvicorn          ✅ 已声明
websockets       ❌ 缺失
webview          ✅ 已声明 (pywebview)
yaml             ✅ 已声明 (pyyaml)
```

---

## 三、参考实现 对比分析

### 3.1 参考实现 有但 CoApis 缺失的依赖

| 包名 | 参考实现 版本 | CoApis 是否有 | 用途 | 建议 |
|------|-------------|--------------|------|------|
| **alibabacloud_tea_util** | >=0.3.0 | ❌ 缺失 | 阿里云 SDK 工具类 | 🔴 必须添加 |
| **alibabacloud_credentials** | >=0.3.0 | ❌ 缺失 | 阿里云凭证管理 | 🟢 可选 |
| **huggingface_hub** | >=0.20.0 | ❌ 缺失 | 本地模型下载 | 🟢 可选 |
| **openai** | >=2.0.0,<=2.33.0 | ❌ 缺失 | OpenAI API 客户端 | 🟢 可选 |
| **orjson** | >=3.9 | ❌ 缺失 | 高性能 JSON | 🟡 推荐 |
| **psutil** | >=6.0.0 | ❌ 缺失 | 系统监控 | 🟡 推荐 |
| **watchfiles** | >=0.22 | ❌ 缺失 | 文件热重载 | 🟢 可选 |
| **playwright** | >=1.49.0 | ❌ 缺失 | 浏览器自动化 | 🟢 可选 |
| **reme-ai** | ==0.3.1.8 | ❌ 缺失 | 记忆系统 | 🟢 可选 |
| **transformers** | >=4.30.0 | ❌ 缺失 | 本地模型推理 | 🟢 可选 |
| **modelscope** | >=1.35.0 | ❌ 缺失 | 魔搭模型下载 | 🟢 可选 |
| **onnxruntime** | <1.24 | ❌ 缺失 | ONNX 推理 | 🟢 可选 |
| **python-lsp-server** | >=1.10 | ❌ 缺失 | Python LSP | 🟢 可选 |
| **ast-grep-cli** | >=0.20 | ❌ 缺失 | AST 搜索 | 🟢 可选 |

### 3.2 CoApis 有但 参考实现 没有的依赖

| 包名 | CoApis 版本 | 用途 | 说明 |
|------|------------|------|------|
| **bcrypt** | >=4.0.0 | 密码哈希 | 参考实现 可能用其他方式 |
| **grpcio** | >=1.60.0 | gRPC 客户端 | MuGA 功能 |
| **grpcio-tools** | >=1.60.0 | gRPC 代码生成 | MuGA 功能 |
| **protobuf** | >=4.25.0 | 协议缓冲 | MuGA 功能 |
| **agent-client-protocol** | >=0.9.0 | ACP 协议 | CoApis 特有 |
| **alibabacloud-dingtalk** | >=2.2.42 | 钉钉 API | 两者都有 |

### 3.3 版本差异对比

| 包名 | CoApis 版本 | 参考实现 版本 | 差异 |
|------|------------|-------------|------|
| agentscope | ==1.0.19.post1 | ==1.0.20 | 参考实现 更新 |
| agentscope-runtime | ==1.1.4 | ==1.1.6 | 参考实现 更新 |

---

## 四、依赖分类

### 4.1 核心框架（必须）

```txt
agentscope==1.0.19.post1        # AI 智能体框架
agentscope-runtime==1.1.4       # 运行时环境
fastapi>=0.100.0,<1.0.0         # Web 框架
pydantic>=2.0.0,<3.0.0          # 数据验证
uvicorn>=0.40.0                 # ASGI 服务器
starlette>=0.27.0               # ASGI 基础
click>=8.0.0                    # CLI 框架
```

### 4.2 HTTP/通信（必须）

```txt
httpx>=0.27.0                   # HTTP 客户端
aiohttp>=3.9.0                  # HTTP 客户端/服务器
anyio>=4.0.0,<4.13.0           # 异步兼容层
aiofiles>=24.1.0                # 异步文件操作
websockets>=13.0                # WebSocket 支持
```

### 4.3 数据/加密（必须）

```txt
pydantic>=2.0.0,<3.0.0          # 数据验证
pydantic-settings>=2.0.0        # 配置管理
pyyaml>=6.0                     # YAML 解析
json-repair>=0.30.0             # JSON 修复
orjson>=3.9                     # 高性能 JSON
packaging>=24.0                 # 版本解析
cryptography>=43.0.0            # 加密库
bcrypt>=4.0.0                   # 密码哈希
```

### 4.4 渠道依赖（按需）

```txt
# Discord
discord-py>=2.3

# 钉钉
dingtalk-stream>=0.24.3
alibabacloud-dingtalk>=2.2.42
alibabacloud-tea-openapi>=0.4.4
alibabacloud-tea-util>=0.3.0    # ← 新增

# 飞书
lark-oapi>=1.5.3

# Telegram
python-telegram-bot>=20.0

# SMS/语音
twilio>=9.10.2

# Matrix
matrix-nio>=0.24.0

# 企业微信
wecom-aibot-python-sdk==1.0.2

# 桌面窗口
pywebview>=4.0
```

### 4.5 AI 提供商（按需）

```txt
anthropic>=0.10.0               # Claude ← 新增
openai>=2.0.0,<=2.33.0          # OpenAI ← 新增
google-genai>=1.67.0            # Gemini
```

### 4.6 工具/系统（必须）

```txt
apscheduler>=3.11.2,<4          # 定时任务
questionary>=2.1.1              # 交互式 CLI
python-dotenv>=1.0.0            # 环境变量
shortuuid>=1.0.0                # 短 ID 生成
keyring>=25.0.0                 # 密钥管理
mss>=9.0.0                      # 屏幕截图
pillow>=10.0.0                  # 图像处理
psutil>=6.0.0                   # 系统监控 ← 新增
rich>=13.0.0                    # 终端美化 ← 新增
frontmatter>=2.0.0              # YAML 前处理 ← 新增
```

### 4.7 协议/通信（必须）

```txt
paho-mqtt>=2.0.0                # MQTT 客户端
agent-client-protocol>=0.9.0    # ACP 协议
mcp>=1.0.0                      # MCP 协议 ← 新增
```

> **注意**: MuGA 相关依赖（grpcio、grpcio-tools、protobuf）已标记为试验品，从生产依赖中移除。

### 4.8 中文处理（必须）

```txt
jieba>=0.42.0                   # 中文分词
segno>=1.6.6                    # QR 码生成
```

### 4.9 可选功能

```txt
# 浏览器自动化
playwright>=1.49.0              # ← 新增

# 本地模型
huggingface_hub>=0.20.0         # ← 新增
transformers>=4.30.0            # ← 新增
modelscope>=1.35.0              # ← 新增
onnxruntime<1.24                # ← 新增

# 记忆系统
reme-ai==0.3.1.8                # ← 新增

# 文件热重载
watchfiles>=0.22                # ← 新增

# Python LSP (Coding Mode)
python-lsp-server[all]>=1.10    # ← 新增

# AST 搜索 (Coding Mode)
ast-grep-cli>=0.20              # ← 新增
```

---

## 五、风险矩阵

| 风险 | 概率 | 影响 | 等级 | 建议 |
|------|------|------|------|------|
| fastapi/pydantic 未声明 | 高 | 高 | 🔴 致命 | 立即补充声明 |
| anyio 4.13.0 bug | 低 | 高 | 🟡 中 | 保持 `<4.13.0` 限制 |
| agentscope 版本落后 | 中 | 高 | 🟡 中 | 评估升级到 1.0.20 |
| Python 3.13 兼容 | 中 | 中 | 🟡 中 | 测试 `audioop-lts` 方案 |
| mcp 包未声明 | 中 | 中 | 🟡 中 | 补充声明 |

---

## 六、总结

### 6.1 当前状态

- ❌ **5 个核心依赖未声明**: fastapi、pydantic、click、aiohttp、anthropic
- ❌ **8 个常用依赖未声明**: rich、frontmatter、orjson、psutil、openai、mcp、huggingface_hub、websockets
- ❌ **agentscope 版本落后**: 1.0.19.post1 vs 参考实现 1.0.20
- ✅ **渠道依赖完整**: Discord/钉钉/飞书/Telegram/Matrix/企业微信
- ✅ **Python 版本兼容**: 3.10-3.13 支持

### 6.2 推荐行动优先级

| 优先级 | 行动 | 影响 |
|--------|------|------|
| P0 | 补充 fastapi、pydantic、click 声明 | 防止安装失败 |
| P0 | 补充 aiohttp、anthropic、mcp 声明 | 功能完整性 |
| P1 | 补充 rich、frontmatter、orjson、psutil 声明 | 与 参考实现 对齐 |
| P1 | 评估 agentscope 升级到 1.0.20 | 获取最新特性 |
| P2 | 补充可选依赖（playwright、huggingface_hub 等） | 功能扩展 |

---

## 七、与 参考实现 的差异总结

| 维度 | CoApis-agent | 参考实现 | 差异 |
|------|-------------|---------|------|
| 核心框架依赖声明 | ❌ 缺失 5 个 | ✅ 完整 | CoApis 需补充 |
| agentscope 版本 | 1.0.19.post1 | 1.0.20 | 参考实现 更新 |
| 本地模型支持 | ❌ 缺失 | ✅ 完整 | CoApis 需补充 |
| Coding Mode | ❌ 缺失 | ✅ 完整 | CoApis 需补充 |
| 记忆系统 | ❌ 缺失 | ✅ reme-ai | CoApis 需补充 |
| gRPC/MuGA | ✅ 完整 | ❌ 缺失 | CoApis 特有 |
| ACP 协议 | ✅ 完整 | ❌ 缺失 | CoApis 特有 |

---

*基于 CoApis-agent 项目实战经验整理*
