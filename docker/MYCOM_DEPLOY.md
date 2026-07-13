# CoApis 企业内部生产环境部署指南

## 📁 文件说明

- `docker-compose-mycom.yml` - 企业内部生产环境 Docker Compose 配置
- `.env.mycom` - 环境变量配置文件

## 🚀 快速部署

### 1. 配置工作目录

编辑 `.env.mycom`，修改以下配置：

```bash
# ⚠️ 必须修改为实际路径
COAPIS_WORKING_DIR=/path/to/your/coapis-data
COAPIS_WORKSPACES_DIR=${COAPIS_WORKING_DIR}/workspaces
```

### 2. 启动服务

```bash
cd coapis-agent/docker
docker compose -f docker-compose-mycom.yml up -d
```

### 3. 查看日志

```bash
docker compose -f docker-compose-mycom.yml logs -f
```

### 4. 停止服务

```bash
docker compose -f docker-compose-mycom.yml down
```

## 🌐 服务端口

| 服务 | 端口 | 说明 |
|------|------|------|
| Web 界面 | 4880 | http://localhost:4880 |
| Server API | 4888 | http://localhost:4888 |
| Playwright | 4881 | 浏览器服务 |

## ⚙️ 配置优化建议

### 企业环境推荐配置

```bash
# .env.mycom

# 文件上传（企业版建议更大限制）
COAPIS_UPLOAD_MAX_FILES=20
COAPIS_UPLOAD_MAX_FILE_SIZE_MB=50

# 浏览器并发（根据服务器性能调整）
COAPIS_PLAYWRIGHT_MAX_SESSIONS=10-20
COAPIS_PLAYWRIGHT_MAX_QUEUE=20

# 日志级别
COAPIS_LOG_LEVEL=INFO
```

### 数据持久化

工作目录结构：
```
/path/to/your/coapis-data/
├── workspaces/          # 用户空间
│   ├── admin/
│   ├── user1/
│   └── ...
├── system/              # 系统配置
└── agent.json           # 全局智能体配置
```

## 🔧 常用命令

```bash
# 重启服务
docker compose -f docker-compose-mycom.yml restart

# 查看服务状态
docker compose -f docker-compose-mycom.yml ps

# 查看特定服务日志
docker compose -f docker-compose-mycom.yml logs -f server

# 进入容器
docker exec -it coapis-mycom-server bash

# 清理并重启（⚠️ 会删除容器）
docker compose -f docker-compose-mycom.yml down
docker compose -f docker-compose-mycom.yml up -d
```

## 📊 资源监控

```bash
# 查看容器资源使用
docker stats coapis-mycom-server coapis-mycom-nginx coapis-mycom-playwright

# 查看容器详情
docker inspect coapis-mycom-server
```

## 🔐 安全建议

1. **修改默认端口**（如果需要对外服务）
2. **配置防火墙**，限制访问来源
3. **定期备份数据目录**
4. **定期更新镜像版本**

## 📞 故障排查

### 服务无法启动

```bash
# 检查端口占用
netstat -tlnp | grep 488

# 检查工作目录权限
ls -la /path/to/your/coapis-data

# 查看详细日志
docker compose -f docker-compose-mycom.yml logs --tail=100
```

### 健康检查失败

```bash
# 检查服务健康状态
docker inspect coapis-mycom-server | grep -A 10 Health

# 手动测试 API
curl http://localhost:4888/api/health
```

---

**部署日期**: 2026-07-13  
**维护团队**: 企业 IT 部门
