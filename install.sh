#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
# CoApis 一键安装脚本
# 用法: curl -fsSL https://get.coapis.com | bash
#   或: bash install.sh
# ═══════════════════════════════════════════════════════════════════
set -e

VERSION="1.0"
REPO="coapis/coapis"
INSTALL_DIR="${COAPIS_INSTALL_DIR:-/opt/coapis}"
COMPOSE_URL="https://raw.githubusercontent.com/${REPO}/main/docker-compose.yml"
ENV_EXAMPLE_URL="https://raw.githubusercontent.com/${REPO}/main/.env.example"

# ── 颜色输出 ──────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}ℹ ${NC}$*"; }
ok()    { echo -e "${GREEN}✅ $*${NC}"; }
warn()  { echo -e "${YELLOW}⚠️  $*${NC}"; }
fail()  { echo -e "${RED}❌ $*${NC}"; exit 1; }

# ── Banner ────────────────────────────────────────────────────────
echo ""
echo "╔═══════════════════════════════════════════════╗"
echo "║       🦀 CoApis Installer v${VERSION}            ║"
echo "║   Multi-user AI Agent Platform                 ║"
echo "╚═══════════════════════════════════════════════╝"
echo ""

# ── 1. 检测 Docker ────────────────────────────────────────────────
info "检测 Docker 环境..."

if ! command -v docker &>/dev/null; then
    fail "Docker 未安装。请先安装 Docker:\n   https://docs.docker.com/get-docker/"
fi

DOCKER_VERSION=$(docker --version | grep -oP '\d+\.\d+\.\d+' | head -1)
ok "Docker ${DOCKER_VERSION} 已安装"

# 检测 Docker Compose
if docker compose version &>/dev/null; then
    COMPOSE_CMD="docker compose"
    ok "Docker Compose (plugin) 可用"
elif command -v docker-compose &>/dev/null; then
    COMPOSE_CMD="docker-compose"
    ok "Docker Compose (standalone) 可用"
else
    fail "Docker Compose 未安装。请安装 Docker Compose:\n   https://docs.docker.com/compose/install/"
fi

# ── 2. 创建安装目录 ──────────────────────────────────────────────
echo ""
info "创建安装目录: ${INSTALL_DIR}"

if [ -d "${INSTALL_DIR}" ]; then
    warn "目录已存在: ${INSTALL_DIR}"
    read -p "是否覆盖现有安装？(y/N): " OVERWRITE
    if [ "${OVERWRITE}" != "y" ] && [ "${OVERWRITE}" != "Y" ]; then
        info "已取消"
        exit 0
    fi
fi

mkdir -p "${INSTALL_DIR}"

# ── 3. 交互式配置 ────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
info "配置向导"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# LLM API Key
read -p "LLM API Key (如 OpenAI sk-xxx，稍后可配置): " API_KEY

# 访问端口
read -p "Web 访问端口 [4200]: " PORT
PORT=${PORT:-4200}

# 生成 .env
cat > "${INSTALL_DIR}/.env" <<ENVEOF
# ═══════════════════════════════════════════════════
# CoApis 环境配置
# 生成时间: $(date '+%Y-%m-%d %H:%M:%S')
# ═══════════════════════════════════════════════════

# ── 核心路径 ──
COAPIS_WORKING_DIR=/data
COAPIS_PORT=${PORT}

# ── LLM 配置 ──
ENVEOF

if [ -n "${API_KEY}" ]; then
    echo "OPENAI_API_KEY=${API_KEY}" >> "${INSTALL_DIR}/.env"
fi

cat >> "${INSTALL_DIR}/.env" <<'ENVEOF'

# ── 认证 ──
# COAPIS_AUTH_ENABLED=true
# COAPIS_AUTH_SECRET_KEY=change-me-to-random-string

# ── 前端端口 ──
# COAPIS_FRONTEND_PORT=4200
ENVEOF

ok ".env 配置已生成"

# ── 4. 下载 docker-compose.yml ──────────────────────────────────
echo ""
info "下载 docker-compose.yml..."

if curl -fsSL "${COMPOSE_URL}" -o "${INSTALL_DIR}/docker-compose.yml" 2>/dev/null; then
    ok "docker-compose.yml 已下载"
else
    # 如果下载失败，内嵌生成
    warn "下载失败，自动生成配置..."
    cat > "${INSTALL_DIR}/docker-compose.yml" <<'COMPOSEEOF'
services:
  server:
    image: ghcr.io/coapis/server:latest
    container_name: coapis
    ports:
      - "${COAPIS_PORT:-4200}:80"
    volumes:
      - coapis-data:/data
    env_file:
      - .env
    environment:
      - COAPIS_WORKING_DIR=/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:8000/api/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 60s

volumes:
  coapis-data:
    driver: local
COMPOSEEOF
    ok "docker-compose.yml 已生成"
fi

# ── 5. 拉取镜像 ──────────────────────────────────────────────────
echo ""
info "拉取 CoApis 镜像 (可能需要几分钟)..."

cd "${INSTALL_DIR}"
if ${COMPOSE_CMD} pull 2>&1; then
    ok "镜像拉取完成"
else
    warn "镜像拉取失败，可能需要配置镜像源"
    warn "尝试使用源码构建: docker compose -f docker-compose.build.yml up -d --build"
    echo ""
    read -p "是否继续尝试源码构建？(y/N): " BUILD_FROM_SOURCE
    if [ "${BUILD_FROM_SOURCE}" = "y" ] || [ "${BUILD_FROM_SOURCE}" = "Y" ]; then
        info "请手动执行:"
        echo "  cd ${INSTALL_DIR}"
        echo "  git clone https://github.com/${REPO}.git source"
        echo "  cd source"
        echo "  docker compose -f docker-compose.build.yml up -d --build"
        exit 0
    fi
    fail "安装中止"
fi

# ── 6. 启动服务 ──────────────────────────────────────────────────
echo ""
info "启动 CoApis..."

${COMPOSE_CMD} up -d
sleep 5

# 等待健康检查
info "等待服务就绪..."
for i in $(seq 1 30); do
    if curl -sf "http://localhost:${PORT}/api/health" > /dev/null 2>&1; then
        ok "服务就绪！"
        break
    fi
    if [ "$i" = "30" ]; then
        warn "服务启动超时，请检查日志: ${COMPOSE_CMD} logs"
    fi
    sleep 2
done

# ── 7. 输出安装信息 ──────────────────────────────────────────────
echo ""
echo "╔═══════════════════════════════════════════════╗"
echo "║       🎉 CoApis 安装成功！                  ║"
echo "╚═══════════════════════════════════════════════╝"
echo ""
echo "  🌐 访问地址:  http://localhost:${PORT}"
echo "  👤 默认账号:  admin"
echo "  🔑 默认密码:  admin123"
echo "  📁 安装目录:  ${INSTALL_DIR}"
echo ""
echo "  常用命令:"
echo "    启动服务:  cd ${INSTALL_DIR} && ${COMPOSE_CMD} up -d"
echo "    停止服务:  cd ${INSTALL_DIR} && ${COMPOSE_CMD} down"
echo "    查看日志:  cd ${INSTALL_DIR} && ${COMPOSE_CMD} logs -f"
echo "    升级版本:  cd ${INSTALL_DIR} && ${COMPOSE_CMD} pull && ${COMPOSE_CMD} up -d"
echo ""
echo "  ⚠️  首次登录后请立即修改默认密码！"
echo ""
