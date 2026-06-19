# CoApis 安装指南

本文档提供 CoApis 的完整安装说明，包括一键安装、源码安装和 Docker 安装三种方式。

## 目录

- [系统要求](#系统要求)
- [方式一：一键安装（推荐）](#方式一一键安装推荐)
- [方式二：源码安装](#方式二源码安装)
- [方式三：Docker 手动安装](#方式三docker-手动安装)
- [开发模式安装](#开发模式安装)
- [配置说明](#配置说明)
- [更新与卸载](#更新与卸载)
- [常见问题](#常见问题)

---

## 系统要求

### 最低配置

| 组件 | 要求 |
|------|------|
| 操作系统 | Linux / macOS / Windows (WSL2) |
| CPU | 2 核 |
| 内存 | 2 GB |
| 磁盘 | 10 GB 可用空间 |
| Docker | 20.10+ |
| Docker Compose | 2.0+ |

### 源码安装额外要求

| 组件 | 要求 |
|------|------|
| Git | 2.30+ |
| Node.js | 18+ |
| npm | 8+ |
| Python | 3.11+ (开发模式) |

---

## 方式一：一键安装（推荐）

一键安装脚本会自动检测环境、配置参数并启动服务。

### 标准安装

```bash
# 使用在线脚本
curl -fsSL https://get.coapis.com | bash

# 或使用本地脚本
git clone https://github.com/coapis/coapis.git
cd coapis
bash install.sh
```

### 包含浏览器服务

如果需要浏览器自动化功能（如网页抓取、自动化操作），添加 `--with-playwright` 参数：

```bash
bash install.sh --with-playwright
```

### 自定义安装目录

```bash
bash install.sh --dir /your/custom/path
```

### 自定义端口

```bash
bash install.sh --port 8080
```

### 安装流程

1. **环境检测** - 检查 Docker 和 Docker Compose
2. **创建目录** - 创建安装目录（默认 `/opt/coapis`）
3. **交互配置** - 输入 API Key 和端口
4. **拉取镜像** - 下载 CoApis 镜像
5. **启动服务** - 启动并等待就绪

### 安装完成

安装成功后会显示：

```
╔═══════════════════════════════════════════════╗
║       🎉 CoApis 安装成功！                  ║
╚═══════════════════════════════════════════════╝

  🌐 访问地址:  http://localhost:4200
  👤 默认账号:  admin
  🔑 默认密码:  admin123
```

> ⚠️ 首次登录后请立即修改默认密码！

---

## 方式二：源码安装

源码安装适合需要定制或开发的用户。

### 快速开始

```bash
# 1. 克隆代码
git clone https://github.com/coapis/coapis.git
cd coapis

# 2. 一键源码安装
bash install.sh --source
```

### 手动安装

```bash
# 1. 克隆代码
git clone https://github.com/coapis/coapis.git
cd coapis

# 2. 构建前端
cd client
npm ci
npm run build
cd ..

# 3. 配置环境变量
cp docker/.env.example docker/.env
nano docker/.env  # 填写 API Key

# 4. 构建并启动
docker compose -f docker/docker-compose.build.yml up -d --build
```

### 包含浏览器服务

```bash
bash install.sh --source --with-playwright
```

---

## 方式三：Docker 手动安装

适合熟悉 Docker 的用户。

### 拉取镜像

```bash
# 创建目录
mkdir -p /opt/coapis && cd /opt/coapis

# 下载配置文件
wget https://raw.githubusercontent.com/coapis/coapis/main/docker-compose.yml
wget https://raw.githubusercontent.com/coapis/coapis/main/.env.example -O .env

# 编辑配置
nano .env
```

### 启动服务

```bash
# 启动
docker compose up -d

# 查看日志
docker compose logs -f

# 停止
docker compose down
```

---

## 开发模式安装

适合需要修改代码的开发者。

```bash
# 1. 使用安装脚本
bash install.sh --dev

# 2. 启动后端（终端 1）
cd /opt/coapis/source/server
python -m coapis run

# 3. 启动前端（终端 2）
cd /opt/coapis/source/client
npm run dev
```

### 开发环境特点

- 前端热重载
- 后端热重载
- 调试日志输出

---

## 配置说明

### 环境变量

在安装目录的 `.env` 文件中配置：

```bash
# 核心路径
COAPIS_WORKING_DIR=/data          # 数据目录
COAPIS_PORT=4200                  # 访问端口

# LLM 配置
OPENAI_API_KEY=sk-xxx             # API Key
OPENAI_BASE_URL=https://api.openai.com/v1  # API 地址（可选）

# 认证配置
COAPIS_AUTH_ENABLED=true          # 启用认证
COAPIS_AUTH_SECRET_KEY=your-secret-key  # JWT 密钥
```

### LLM 模型配置

CoApis 支持任意 OpenAI 兼容的 API：

| 提供商 | BASE_URL | 说明 |
|--------|----------|------|
| OpenAI | https://api.openai.com/v1 | 默认 |
| Azure OpenAI | https://xxx.openai.azure.com/ | Azure 部署 |
| Ollama | http://localhost:11434/v1 | 本地模型 |
| vLLM | http://localhost:8000/v1 | 本地部署 |
| LM Studio | http://localhost:1234/v1 | 本地 GUI |

### 数据目录结构

```
/apps/ai/coapis/
├── system/                     # 系统配置
│   ├── config.json             # 主配置
│   ├── permissions.json        # 权限定义
│   ├── users.json              # 用户数据
│   └── token_usage.json        # Token 统计
├── workspaces/                 # 用户工作区
│   ├── admin/
│   │   ├── agent.json
│   │   ├── chat/
│   │   └── skill.json
│   └── user1/
└── agents/                     # 智能体数据
    └── agent-xxx/
```

---

## 更新与卸载

### 更新到最新版本

```bash
# 一键更新
bash install.sh --update

# 或手动更新
cd /opt/coapis
docker compose pull
docker compose up -d
```

### 卸载

```bash
# 交互式卸载
bash install.sh --uninstall

# 或手动卸载
cd /opt/coapis
docker compose down           # 停止容器
docker compose down -v        # 停止并删除数据卷
rm -rf /opt/coapis            # 删除安装目录
```

---

## 常见问题

### 1. 端口被占用

```
Error: Address already in use
```

**解决方案**：
```bash
# 修改端口
bash install.sh --port 8080

# 或手动修改 .env
nano /opt/coapis/.env
# 修改 COAPIS_PORT=8080
```

### 2. Docker 权限不足

```
Permission denied while trying to connect to the Docker daemon socket
```

**解决方案**：
```bash
# 将当前用户加入 docker 组
sudo usermod -aG docker $USER

# 或使用 sudo
sudo docker compose up -d
```

### 3. 镜像拉取失败

```
Error response from daemon: Get "https://ghcr.io/v2/": dial tcp: timeout
```

**解决方案**：
```bash
# 使用镜像加速器（阿里云示例）
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json <<-'EOF'
{
  "registry-mirrors": ["https://xxx.mirror.aliyuncs.com"]
}
EOF
sudo systemctl restart docker
```

### 4. 前端无法访问

**检查**：
```bash
# 检查容器状态
docker compose ps

# 检查日志
docker compose logs nginx

# 检查端口
netstat -tlnp | grep 4200
```

### 5. API 连接失败

**检查**：
```bash
# 查看后端日志
docker compose logs server

# 测试 API
curl http://localhost:4200/api/health
```

### 6. 数据丢失恢复

如果误删了数据卷但有备份：

```bash
# 从备份恢复
docker volume create coapis-data
docker volume create coapis-backup
# ... 恢复数据 ...

# 或直接挂载本地目录
docker run -v /path/to/backup:/data ...
```

---

## 进阶配置

### 使用 Nginx 反向代理

```nginx
server {
    listen 80;
    server_name coapis.example.com;
    
    location / {
        proxy_pass http://localhost:4200;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### 使用 HTTPS

```bash
# 使用 Let's Encrypt
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d coapis.example.com
```

### 数据备份

```bash
# 备份数据目录
tar -czf coapis-backup-$(date +%Y%m%d).tar.gz /apps/ai/coapis/

# 或使用 Docker
docker run --rm -v coapis-data:/data -v $(pwd):/backup alpine \
    tar czf /backup/coapis-data.tar.gz /data
```

---

## 获取帮助

- **文档**：[https://docs.coapis.com](https://docs.coapis.com)
- **GitHub**：[https://github.com/coapis/coapis](https://github.com/coapis/coapis)
- **Gitee**：[https://gitee.com/ouerlai/coapis](https://gitee.com/ouerlai/coapis)
- **问题反馈**：[GitHub Issues](https://github.com/coapis/coapis/issues)

---

*最后更新：2026-06-19*
