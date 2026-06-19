# CoApis 部署文档

## 目录

- [快速开始](#快速开始)
- [开源版部署](#开源版部署)
- [企业版部署](#企业版部署)
- [多环境部署](#多环境部署)
- [配置参考](#配置参考)
- [故障排查](#故障排查)

---

## 快速开始

### 前置条件

- Docker 20.10+
- Docker Compose 2.0+
- 4GB+ 内存
- 20GB+ 磁盘空间

### 一键部署（开源版）

```bash
# Clone repository
git clone https://github.com/coapis/coapis.git
cd coapis-agent

# Start with docker-compose
docker-compose up -d

# Access console
# Open http://localhost:4200 in browser
# Default admin: admin / admin123
```

---

## 开源版部署

### Docker 部署

```bash
# Build image
docker build -f server/deploy/Dockerfile -t coapis-server:latest server/

# Create volumes
docker volume create coapis-data
docker volume create coapis-workspace

# Run container
docker run -d --name coapis-server \
  -p 8000:8000 \
  -v coapis-data:/root/.coapis/data \
  -v coapis-workspace:/app/working \
  -e COAPIS_AUTH_ENABLED=true \
  -e COAPIS_ADMIN_USERNAME=admin \
  -e COAPIS_ADMIN_PASSWORD=admin123 \
  coapis-server:latest
```

### Docker Compose 部署

```yaml
# docker-compose.yml
version: '3.8'

services:
  server:
    build:
      context: ./server
      dockerfile: deploy/Dockerfile
    container_name: coapis-server
    ports:
      - "8000:8000"
    volumes:
      - coapis-data:/root/.coapis/data
      - coapis-workspace:/app/working
    environment:
      - COAPIS_AUTH_ENABLED=true
      - COAPIS_ADMIN_USERNAME=admin
      - COAPIS_ADMIN_PASSWORD=admin123
    restart: unless-stopped

  nginx:
    image: nginx:alpine
    container_name: coapis-nginx
    ports:
      - "4200:80"
    volumes:
      - ./docker/nginx/conf.d:/etc/nginx/conf.d:ro
    depends_on:
      - server
    restart: unless-stopped

volumes:
  coapis-data:
  coapis-workspace:
```

### 验证部署

```bash
# Check container status
docker ps | grep coapis

# Test API
curl http://localhost:8000/api/health

# Test login
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'
```

---

## 企业版部署

### 架构说明

企业版采用**双包分离架构**：

```
coapis (开源包)
├── 核心功能
├── P2 基础实现 (存根)
└── 企业插件接口

coapis-enterprise (企业包)
├── 监控面板 (高级功能)
├── SSO 集成 (OIDC/SAML)
├── 技能市场 (审核/付费)
├── 集群管理
└── 审计日志
```

### Docker 部署

```bash
# Build enterprise image
docker build -f server/deploy/Dockerfile.enterprise \
  -t coapis-server:enterprise .

# Run with enterprise license
docker run -d --name coapis-server \
  -p 8000:8000 \
  -v coapis-data:/root/.coapis/data \
  -v coapis-workspace:/app/working \
  -e COAPIS_AUTH_ENABLED=true \
  -e COAPIS_ADMIN_USERNAME=admin \
  -e COAPIS_ADMIN_PASSWORD=admin123 \
  -e COAPIS_LICENSE_KEY=<your-license-key> \
  coapis-server:enterprise
```

### Docker Compose 部署

```yaml
# docker-compose.enterprise.yml
version: '3.8'

services:
  server:
    build:
      context: .
      dockerfile: server/deploy/Dockerfile.enterprise
    container_name: coapis-server
    ports:
      - "8000:8000"
    volumes:
      - coapis-data:/root/.coapis/data
      - coapis-workspace:/app/working
    environment:
      - COAPIS_AUTH_ENABLED=true
      - COAPIS_ADMIN_USERNAME=admin
      - COAPIS_ADMIN_PASSWORD=admin123
      - COAPIS_LICENSE_KEY=${COAPIS_LICENSE_KEY}
    restart: unless-stopped

  nginx:
    image: nginx:alpine
    container_name: coapis-nginx
    ports:
      - "4200:80"
    volumes:
      - ./docker/nginx/conf.d:/etc/nginx/conf.d:ro
    depends_on:
      - server
    restart: unless-stopped

volumes:
  coapis-data:
  coapis-workspace:
```

### 企业功能验证

```bash
# Test monitoring endpoints
curl http://localhost:8000/api/monitor/health \
  -H "Authorization: Bearer <token>"

# Test SSO endpoints
curl http://localhost:8000/api/sso/providers \
  -H "Authorization: Bearer <token>"

# Test skill market
curl http://localhost:8000/api/skill-market/skills \
  -H "Authorization: Bearer <token>"

# Test license status
curl http://localhost:8000/api/license/status \
  -H "Authorization: Bearer <token>"
```

---

## 多环境部署

### 开发环境

```bash
# Development mode (hot reload enabled)
docker run -d --name coapis-dev \
  -p 8000:8000 \
  -v $(pwd)/server/coapis:/opt/coapis/coapis \
  -v coapis-dev-data:/root/.coapis/data \
  -e COAPIS_ENV=development \
  -e COAPIS_DEBUG=true \
  -e COAPIS_AUTH_ENABLED=false \
  coapis-server:latest
```

### 测试环境

```bash
# Test environment (with auth, no license)
docker run -d --name coapis-test \
  -p 8000:8000 \
  -v coapis-test-data:/root/.coapis/data \
  -v coapis-test-workspace:/app/working \
  -e COAPIS_ENV=testing \
  -e COAPIS_AUTH_ENABLED=true \
  -e COAPIS_ADMIN_USERNAME=testadmin \
  -e COAPIS_ADMIN_PASSWORD=test123 \
  coapis-server:latest
```

### 生产环境

```bash
# Production environment (enterprise, with license)
docker run -d --name coapis-prod \
  -p 8000:8000 \
  -v coapis-prod-data:/root/.coapis/data \
  -v coapis-prod-workspace:/app/working \
  -e COAPIS_ENV=production \
  -e COAPIS_AUTH_ENABLED=true \
  -e COAPIS_ADMIN_USERNAME=<prod-admin> \
  -e COAPIS_ADMIN_PASSWORD=<prod-password> \
  -e COAPIS_LICENSE_KEY=<production-license> \
  --restart=always \
  --memory=4g \
  --cpus=2 \
  coapis-server:enterprise
```

### 集群部署

```yaml
# docker-compose.cluster.yml
version: '3.8'

services:
  server-1:
    extends:
      file: docker-compose.enterprise.yml
      service: server
    container_name: coapis-server-1
    environment:
      - COAPIS_CLUSTER_NODE=1
      - COAPIS_CLUSTER_PEERS=node2:8000,node3:8000
    ports:
      - "8001:8000"

  server-2:
    extends:
      file: docker-compose.enterprise.yml
      service: server
    container_name: coapis-server-2
    environment:
      - COAPIS_CLUSTER_NODE=2
      - COAPIS_CLUSTER_PEERS=node1:8000,node3:8000
    ports:
      - "8002:8000"

  redis:
    image: redis:7-alpine
    container_name: coapis-redis
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    restart: unless-stopped

volumes:
  redis-data:
```

---

## 配置参考

### 环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `COAPIS_ENV` | production | 运行环境 (development/testing/production) |
| `COAPIS_AUTH_ENABLED` | false | 是否启用认证 |
| `COAPIS_ADMIN_USERNAME` | admin | 管理员用户名 |
| `COAPIS_ADMIN_PASSWORD` | admin123 | 管理员密码 |
| `COAPIS_LICENSE_KEY` | - | 企业版许可证密钥 |
| `COAPIS_DEBUG` | false | 调试模式 |
| `COAPIS_LOG_LEVEL` | INFO | 日志级别 (DEBUG/INFO/WARNING/ERROR) |
| `COAPIS_PORT` | 8088 | API 服务端口 |
| `COAPIS_WORKING_DIR` | /app/working | 工作目录 |
| `COAPIS_DISABLED_CHANNELS` | imessage | 禁用的频道 |

### 权限配置

权限配置文件位置：`/root/.coapis/data/permissions.json`

```json
{
  "roles": {
    "admin": {
      "permissions": ["*"]
    },
    "user": {
      "permissions": [
        "api:agents:read",
        "api:agents:write",
        "api:skills:read",
        "api:skills:write",
        "api:user:me"
      ]
    },
    "visitor": {
      "permissions": [
        "api:user:me",
        "api:skills:read"
      ]
    }
  },
  "modules": {
    "monitoring": ["admin"],
    "sso": ["admin"],
    "skill_market": ["admin"],
    "audit": ["admin"],
    "clustering": ["admin"]
  }
}
```

---

## 故障排查

### 容器无法启动

```bash
# 查看日志
docker logs coapis-server

# 检查端口冲突
netstat -tlnp | grep 8000

# 检查磁盘空间
df -h

# 检查 Docker 状态
systemctl status docker
```

### 登录失败

```bash
# 检查认证配置
docker exec coapis-server env | grep COAPIS_AUTH

# 检查用户数据库
docker exec coapis-server python3 -c "
import sqlite3
conn = sqlite3.connect('/root/.coapis/data/user_system.db')
cursor = conn.cursor()
cursor.execute('SELECT username, role FROM users')
for row in cursor.fetchall():
    print(f'User: {row[0]}, Role: {row[1]}')
conn.close()
"
```

### 企业功能不可用

```bash
# 检查企业包安装
docker exec coapis-server pip list | grep coapis

# 检查许可证状态
curl http://localhost:8000/api/license/status \
  -H "Authorization: Bearer <token>"

# 检查环境变量
docker exec coapis-server env | grep LICENSE
```

### 性能问题

```bash
# 监控系统资源
docker stats coapis-server

# 查看 API 统计
curl http://localhost:8000/api/monitor/api-stats \
  -H "Authorization: Bearer <token>"

# 查看系统指标
curl http://localhost:8000/api/monitor/health \
  -H "Authorization: Bearer <token>"
```

---

## 备份与恢复

### 备份数据

```bash
# Backup data volume
docker run --rm \
  -v coapis-data:/data:ro \
  -v $(pwd)/backups:/backups \
  alpine tar czf /backups/coapis-data-$(date +%Y%m%d).tar.gz -C /data .

# Backup workspace volume
docker run --rm \
  -v coapis-workspace:/data:ro \
  -v $(pwd)/backups:/backups \
  alpine tar czf /backups/coapis-workspace-$(date +%Y%m%d).tar.gz -C /data .
```

### 恢复数据

```bash
# Restore data volume
docker run --rm \
  -v coapis-data:/data \
  -v $(pwd)/backups:/backups:ro \
  alpine tar xzf /backups/coapis-data-20260515.tar.gz -C /data .

# Restart container
docker restart coapis-server
```

---

## 升级指南

### 从开源版升级到企业版

```bash
# 1. Backup current data
docker run --rm \
  -v coapis-data:/data:ro \
  -v $(pwd)/backups:/backups \
  alpine tar czf /backups/coapis-data-pre-upgrade.tar.gz -C /data .

# 2. Stop current container
docker stop coapis-server
docker rm coapis-server

# 3. Build enterprise image
docker build -f server/deploy/Dockerfile.enterprise \
  -t coapis-server:enterprise .

# 4. Start with enterprise license
docker run -d --name coapis-server \
  -p 8000:8000 \
  -v coapis-data:/root/.coapis/data \
  -v coapis-workspace:/app/working \
  -e COAPIS_AUTH_ENABLED=true \
  -e COAPIS_ADMIN_USERNAME=admin \
  -e COAPIS_ADMIN_PASSWORD=admin123 \
  -e COAPIS_LICENSE_KEY=<your-license-key> \
  coapis-server:enterprise

# 5. Verify upgrade
docker logs coapis-server | grep -i enterprise
curl http://localhost:8000/api/license/status \
  -H "Authorization: Bearer <token>"
```

---

## 附录

### A. 端口参考

| 服务 | 端口 | 说明 |
|------|------|------|
| API Server | 8000 | CoApis API 服务 |
| Nginx | 4200 | 前端控制台 |
| Redis | 6379 | 集群缓存（企业版） |

### B. 目录结构

```
coapis-agent/
├── client/                 # 前端代码
├── server/                 # 后端代码
│   ├── coapis/         # 开源包
│   └── deploy/            # 部署配置
│       ├── Dockerfile     # 开源版镜像
│       └── Dockerfile.enterprise  # 企业版镜像
├── enterprise/            # 企业包
│   └── coapis_enterprise/
├── docker/                # Docker 配置
│   ├── nginx/
│   └── config/
├── docs/                  # 文档
└── scripts/               # 脚本
```

### C. 测试命令

```bash
# Run all tests
cd server && python3 -m pytest tests/

# Run deployment test
python3 /tmp/final_install_deploy_test.py

# Run enterprise test
python3 /tmp/enterprise_test.py
```

---

**文档版本**: 1.0.0
**更新日期**: 2026-05-15
**维护者**: 蜜蜂
