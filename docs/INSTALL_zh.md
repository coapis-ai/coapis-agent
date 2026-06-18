# CoApis 安装部署指南

## 系统要求

| 组件 | 最低要求 | 推荐配置 |
|------|---------|---------|
| CPU | 4 核 | 8 核+ |
| 内存 | 8 GB | 16 GB+ |
| 磁盘 | 20 GB | 50 GB+ (SSD) |
| Docker | 20.10+ | 24.0+ |
| Docker Compose | 2.0+ | 2.20+ |
| LLM 服务 | OpenAI 兼容 API | 本地 LLM 推理服务（如 vLLM/Ollama/LM Studio） |

## 快速部署

### 1. 前置准备

```bash
# 安装 Docker（如果未安装）
curl -fsSL https://get.docker.com | sh

# 安装 Docker Compose V2（通常随 Docker Desktop 或 docker-compose-plugin 提供）
# Ubuntu/Debian: apt install docker-compose-plugin
# CentOS/RHEL: dnf install docker-compose-plugin
```

### 2. 获取代码

```bash
git clone https://github.com/eater-claw/eater-claw.git
cd eater-claw
```

### 3. 配置环境变量

```bash
cp docker/.env.example docker/.env
```

编辑 `docker/.env`，根据实际环境修改：

```bash
# LLM API 服务地址（必填）
# 如果使用本地 LLM 推理服务（如 vLLM）:
COAPIS_LLM_BASE_URL=http://172.16.6.241:8002/v1
# 如果使用 OpenAI:
# COAPIS_LLM_BASE_URL=https://api.openai.com/v1

# 认证配置
COAPIS_AUTH_ENABLED=True
COAPIS_USER_SYSTEM_ENABLED=True

# 数据目录（默认即可）
COAPIS_DATA_DIR=/opt/coapis/data
COAPIS_SECRET_DIR=/opt/coapis/data/.secret
```

### 4. 配置 LLM Provider

```bash
cp docker/config/providers.example.json docker/config/providers.json
```

编辑 `docker/config/providers.json`：

```json
{
  "local_llm": {
    "id": "local_llm",
    "type": "openai",
    "api_base": "http://172.16.6.241:8002/v1",
    "api_key": "none"
  }
}
```

> **注意**: 
> - 如果使用 OpenAI，设置 `"api_key": "sk-xxx"` 真实密钥
> - 如果使用本地 LLM 推理服务（无需认证），设置 `"api_key": "none"` 即可
> - `api_base` 必须从容器内可访问

### 5. 配置 Agent

```bash
cp docker/config/config.example.json docker/config/config.json
```

编辑 `docker/config/config.json`：

```json
{
  "agents": {
    "active_agent": "default",
    "profiles": {
      "default": {
        "model": "qwen3.6-27b",
        "provider": "local_llm"
      }
    }
  }
}
```

> **注意**: `model` 和 `provider` 必须与你的 LLM 服务实际提供的模型名称和 Provider ID 匹配。

### 6. 启动服务

```bash
cd docker
docker compose up -d
```

### 7. 验证部署

```bash
# 检查容器状态
docker compose ps

# 健康检查
curl http://localhost:4200/api/health

# 预期输出:
# {"status": "healthy", "timestamp": "...", "version": "0.1.0"}
```

### 8. 首次使用

1. 打开浏览器访问 `http://<服务器IP>:4200`
2. 注册管理员账号
3. 开始使用！

---

## 配置详解

### 环境变量参考

| 变量 | 说明 | 默认值 | 必填 |
|------|------|--------|------|
| `COAPIS_LLM_BASE_URL` | LLM API 服务地址 | - | ✅ |
| `COAPIS_AUTH_ENABLED` | 是否启用认证 | `True` | - |
| `COAPIS_USER_SYSTEM_ENABLED` | 是否启用用户体系 | `True` | - |
| `COAPIS_DATA_DIR` | 数据持久化目录 | `/opt/coapis/data` | - |
| `COAPIS_SECRET_DIR` | 密钥存储目录 | `/opt/coapis/data/.secret` | - |
| `COAPIS_USER_POINTS_LOGIN_DAILY` | 每日登录积分 | `5` | - |
| `COAPIS_USER_TOKEN_QUOTA_L0` | L0 用户月 Token 配额 | `100000` | - |
| `COAPIS_USER_LOCAL_MODEL_FREE_TOKENS` | 本地模型免 Token 计量 | `True` | - |

### Provider 配置参考

```json
{
  "provider_id": {
    "id": "provider_id",
    "type": "openai",
    "api_base": "http://llm-service:port/v1",
    "api_key": "your-api-key"
  }
}
```

支持的 Provider 类型：
- `openai` — OpenAI 兼容 API（vLLM、Ollama、LM Studio 等）
- `anthropic` — Anthropic Claude
- `google` — Google Gemini

### Agent 配置参考

```json
{
  "agents": {
    "active_agent": "default",
    "profiles": {
      "default": {
        "model": "model-name",
        "provider": "provider-id"
      }
    }
  }
}
```

---

## 常见问题

### Q: 容器启动失败

**A**: 检查日志：
```bash
docker compose logs server
docker compose logs nginx
```

### Q: 聊天返回 400 错误

**A**: 检查 `agent.json` 中的 `active_model` 是否有效：
```bash
docker exec coapis-server cat /opt/coapis/workspaces/default/agent.json
```

确保 `model` 和 `provider` 字段与 `providers.json` 和 `config.json` 一致。

### Q: 浏览器缓存导致旧代码

**A**: Nginx 静态资源缓存 1 年，更新后需要：
- 清除浏览器缓存（Ctrl+Shift+Delete）
- 或使用无痕模式
- 或硬刷新（Ctrl+F5）

### Q: 自定义 Provider 刷新后丢失

**A**: 确保 `COAPIS_SECRET_DIR` 指向 `DATA_DIR` 下的目录（如 `/opt/coapis/data/.secret`），该目录会被 Docker Volume 持久化。

---

## 性能优化

### 本地 LLM 推理服务配置建议（以 vLLM 为例）

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
  --enable_chunked_prefill
```

### CoApis 侧优化

- 启用 System Prompt 缓存（默认开启）
- 启用 Compact Skills Index（默认开启）
- 调整 ContextCompressor 阈值（`HISTORY_TOKEN_BUDGET=500`）

---

## 升级指南

```bash
# 1. 备份数据
docker compose exec server tar czf /tmp/backup.tar.gz /opt/coapis/data/

# 2. 拉取最新代码
git pull origin main

# 3. 重建容器
cd docker
docker compose up -d --force-recreate

# 4. 验证
curl http://localhost:4200/api/health
```

---

## 生产部署建议

1. **使用 HTTPS** — 配置 Nginx 反向代理 + Let's Encrypt
2. **数据备份** — 定期备份 `DATA_DIR`
3. **监控** — 配置容器健康检查和告警
4. **资源限制** — 在 `docker-compose.yaml` 中设置 `deploy.resources.limits`
5. **日志管理** — 配置日志轮转，避免磁盘占满
