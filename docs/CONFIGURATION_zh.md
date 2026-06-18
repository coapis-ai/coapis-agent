# CoApis 配置参考

## 环境变量配置

### 核心配置

| 变量 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `COAPIS_LLM_BASE_URL` | string | - | LLM API 服务地址（必填） |
| `COAPIS_AUTH_ENABLED` | bool | `True` | 是否启用认证系统 |
| `COAPIS_USER_SYSTEM_ENABLED` | bool | `True` | 是否启用多租户用户体系 |
| `COAPIS_DATA_DIR` | string | `/opt/coapis/data` | 数据持久化根目录 |
| `COAPIS_SECRET_DIR` | string | `/opt/coapis/data/.secret` | 密钥存储目录（必须在 DATA_DIR 下） |

### 用户积分配置

| 变量 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `COAPIS_USER_POINTS_LOGIN_DAILY` | int | `5` | 每日登录积分 |
| `COAPIS_USER_POINTS_FIRST_LOGIN` | int | `20` | 首次登录奖励积分 |
| `COAPIS_USER_POINTS_CHAT_PER_SESSION` | int | `2` | 每次聊天会话积分 |
| `COAPIS_USER_POINTS_AGENT_CREATE` | int | `10` | 创建 Agent 积分 |
| `COAPIS_USER_POINTS_SKILL_CREATE` | int | `15` | 创建技能积分 |
| `COAPIS_USER_POINTS_MCP_CONFIG` | int | `5` | 配置 MCP 积分 |
| `COAPIS_USER_POINTS_DOC_IMPORT` | int | `3` | 导入文档积分 |
| `COAPIS_USER_POINTS_WEEKLY_STREAK` | int | `30` | 每周连续登录奖励 |
| `COAPIS_USER_POINTS_MONTHLY_STREAK` | int | `100` | 每月连续登录奖励 |
| `COAPIS_USER_POINTS_DAILY_CAP` | int | `50` | 每日积分上限 |

### Token 配额配置（每月）

| 变量 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `COAPIS_USER_TOKEN_QUOTA_L0` | int | `100000` | L0 用户月配额（新用户） |
| `COAPIS_USER_TOKEN_QUOTA_L1` | int | `1000000` | L1 用户月配额 |
| `COAPIS_USER_TOKEN_QUOTA_L2` | int | `5000000` | L2 用户月配额 |
| `COAPIS_USER_TOKEN_QUOTA_L3` | int | `20000000` | L3 用户月配额 |
| `COAPIS_USER_TOKEN_QUOTA_L4` | int | `-1` | L4 用户月配额（无限制） |
| `COAPIS_USER_TOKEN_QUOTA_HARD_LIMIT` | bool | `False` | 是否硬限制（True=超配额拒绝，False=超配额警告） |

### 限流配置（每分钟请求数）

| 变量 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `COAPIS_USER_RATE_LIMIT_L0` | int | `10` | L0 用户限流 |
| `COAPIS_USER_RATE_LIMIT_L1` | int | `10` | L1 用户限流 |
| `COAPIS_USER_RATE_LIMIT_L2` | int | `50` | L2 用户限流 |
| `COAPIS_USER_RATE_LIMIT_L3` | int | `200` | L3 用户限流 |
| `COAPIS_USER_RATE_LIMIT_L4` | int | `1000` | L4 用户限流 |

### 特殊配置

| 变量 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `COAPIS_USER_LOCAL_MODEL_FREE_TOKENS` | bool | `True` | 本地模型是否免 Token 计量 |

---

## Provider 配置 (`docker/config/providers.json`)

```json
{
  "provider_id": {
    "id": "provider_id",
    "type": "openai|anthropic|google",
    "api_base": "http://llm-service:port/v1",
    "api_key": "your-api-key"
  }
}
```

### 配置说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | ✅ | Provider 唯一标识（如 `local_llm`） |
| `type` | string | ✅ | Provider 类型：`openai`、`anthropic`、`google` |
| `api_base` | string | ✅ | API 基础地址（从容器内可访问） |
| `api_key` | string | ✅ | API 密钥（本地 LLM 推理服务无需认证时用 `none`） |

### 示例配置

**本地 LLM 推理服务（无需认证）：**
```json
{
  "local_llm": {
    "id": "local_llm",
    "type": "openai",
    "api_base": "http://172.16.6.241:8082/v1",
    "api_key": "none"
  }
}
```

**OpenAI：**
```json
{
  "openai": {
    "id": "openai",
    "type": "openai",
    "api_base": "https://api.openai.com/v1",
    "api_key": "sk-xxx"
  }
}
```

**Anthropic Claude：**
```json
{
  "anthropic": {
    "id": "anthropic",
    "type": "anthropic",
    "api_base": "https://api.anthropic.com",
    "api_key": "sk-ant-xxx"
  }
}
```

---

## Agent 配置 (`docker/config/config.json`)

```json
{
  "agents": {
    "active_agent": "default",
    "profiles": {
      "default": {
        "model": "qwen3.6-27b",
        "provider": "local_llm",
        "enable_memory": false,
        "tool_calling_method": "raw"
      }
    }
  }
}
```

### 配置说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `active_agent` | string | ✅ | 默认激活的 Agent ID |
| `profiles` | object | ✅ | Agent 配置集合 |
| `model` | string | ✅ | 模型名称（必须与 LLM 服务实际提供的一致） |
| `provider` | string | ✅ | Provider ID（必须与 providers.json 中的 ID 匹配） |
| `enable_memory` | bool | - | 是否启用记忆模块（Qwen3 建议 `false`） |
| `tool_calling_method` | string | - | 工具调用方式（Qwen3 建议 `raw`） |

---

## Docker Compose 配置

### 端口配置

| 服务 | 内部端口 | 暴露端口 | 说明 |
|------|---------|---------|------|
| Server | 8000 | 不直接暴露 | 仅内部网络访问 |
| Nginx | 80 | 4200 | 统一入口端口 |

### Volume 挂载

| 挂载路径 | 容器内路径 | 说明 |
|---------|-----------|------|
| `../workspaces` | `/opt/coapis/workspaces` | Agent 配置持久化 |
| `docker_coapis-data` | `/opt/coapis/data` | 用户/认证/密钥数据持久化 |

### 健康检查

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/api/health"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 60s
```

---

## 性能调优配置

### ContextCompressor 阈值

在 `server/coapis/agent/context_compressor.py` 中调整：

```python
HISTORY_TOKEN_BUDGET = 500  # 历史消息 Token 预算（超过则触发压缩）
TIER1_THRESHOLD = 5         # Tier1 压缩触发阈值（轮数）
```

### 本地 LLM 推理服务启动参数建议（以 vLLM 为例）

```bash
vllm serve \
  --model /path/to/model \
  --tensor-parallel-size 4 \
  --max_num_seqs 8 \
  --max-model-len 131072 \
  --max-num-batched-tokens 8192 \
  --block-size 16 \
  --gpu-memory-utilization 0.87 \
  --enable-prefix-caching \
  --enable_chunked_prefill \
  --enforce_eager
```

---

## 用户等级体系

| 等级 | 积分范围 | Token 配额 | 限流 |
|------|---------|-----------|------|
| L0 | 0-99 | 100K/月 | 10 req/min |
| L1 | 100-499 | 1M/月 | 10 req/min |
| L2 | 500-1999 | 5M/月 | 50 req/min |
| L3 | 2000-9999 | 20M/月 | 200 req/min |
| L4 | 10000+ | 无限制 | 1000 req/min |

---

## JSONL 文件轮转策略

系统使用 JSONL（JSON Lines）格式记录运行时数据，所有写入通过 `safe_append_jsonl()` 统一管理，自带自动轮转。

### 轮转规则

| 参数 | 默认值 | 说明 |
|------|--------|------|
| 触发阈值 | **10 MB** | 文件超过此大小时触发轮转 |
| 历史保留 | **1 份** | 保留最近 1 份归档（`*.1.jsonl`） |
| 轮转时机 | 写入前 | 在打开文件句柄之前检查，避免 fd 指向已重命名的旧文件 |
| 原子性 | `path.rename()` | POSIX 文件系统上为原子操作 |
| 并发安全 | `fcntl.LOCK_EX` | 排他锁保护，与写入操作共用同一锁 |

### 涉及的 JSONL 文件

| 文件路径 | 写入方 | 内容 | 预估增长速率 |
|----------|--------|------|-------------|
| `system/skill_evolution/trigger_log.jsonl` | TriggerTracker | 技能触发事件与结果 | ~1KB/次对话 |
| `system/tool_usage.jsonl` | usage_tracker | 工具调用统计 | ~200B/次调用 |
| `system/skill_evolution/effectiveness_signals.jsonl` | bridge | 技能有效性信号 | ~500B/次评估 |
| `system/skill_evolution/improvement_feedback.jsonl` | bridge | 改进反馈记录 | ~300B/次反馈 |

### 调整建议

- **高流量环境**：可降低 `max_bytes` 至 5MB 以更频繁轮转，减少单次读取开销
- **低流量环境**：可提高至 50MB 以减少归档文件数量
- **审计需求**：如需保留更多历史，修改 `_rotate_jsonl_if_needed()` 中的归档数量上限
- 代码位置：`server/coapis/utils/file_lock.py` → `_rotate_jsonl_if_needed()`
