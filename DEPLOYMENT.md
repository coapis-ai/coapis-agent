# CoApis 部署文档

## 快速部署

### 方式一：一键安装（推荐 ⭐）

```bash
curl -fsSL https://raw.githubusercontent.com/coapis/coapis/main/install.sh | bash
```

### 方式二：手动 Docker 部署

```bash
# 1. 创建安装目录
mkdir -p /opt/coapis && cd /opt/coapis

# 2. 下载配置文件
wget https://raw.githubusercontent.com/coapis/coapis/main/docker-compose.yml
wget https://raw.githubusercontent.com/coapis/coapis/main/.env.example -O .env

# 3. 编辑 .env，填写必要配置
nano .env

# 4. 启动
docker compose up -d

# 5. 验证
curl http://localhost:4200/api/health
```

### 方式三：源码构建

```bash
git clone https://github.com/coapis/coapis.git
cd coapis
cp .env.example .env
# 编辑 .env 填写 API Key
docker compose -f docker-compose.build.yml up -d --build
```

## 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `OPENAI_API_KEY` | LLM API Key | (必填) |
| `COAPIS_PORT` | Web 访问端口 | `4200` |
| `COAPIS_WORKING_DIR` | 数据目录 | `/data` |
| `COAPIS_AUTH_ENABLED` | 启用认证 | `false` |

> 完整配置参考：[.env.example](./.env.example)

## 访问服务

- 地址：`http://<server-ip>:4200`
- 默认管理员：`admin` / `admin123`
- ⚠️ 首次登录后请立即修改默认密码

## 升级

```bash
cd /opt/coapis
docker compose pull
docker compose up -d
```

## 数据备份

所有数据存储在 Docker 命名卷 `coapis-data` 中。

```bash
# 备份
docker run --rm -v coapis-data:/data -v $(pwd):/backup alpine \
    tar czf /backup/coapis-backup-$(date +%Y%m%d).tar.gz /data

# 恢复
docker run --rm -v coapis-data:/data -v $(pwd):/backup alpine \
    tar xzf /backup/coapis-backup-YYYYMMDD.tar.gz -C /
```

## 常见问题

### 端口被占用
修改 `.env` 中的 `COAPIS_PORT`，然后重启：`docker compose up -d`

### 容器无法启动
检查日志：`docker compose logs -f`

### LLM 连接失败
确认 `.env` 中的 API Key 和网络连通性。
