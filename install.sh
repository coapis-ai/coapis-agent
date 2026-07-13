#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
# CoApis 一键安装脚本（增强版）
# 用法:
#   curl -fsSL https://get.coapis.com | bash                    # 默认安装
#   COAPIS_VERSION=v0.9.11 bash install.sh                       # 指定版本
#   bash install.sh --source                                     # 源码构建
#   bash install.sh --with-playwright                            # 包含浏览器服务
#   bash install.sh --update                                     # 仅更新
#   bash install.sh --uninstall                                  # 卸载
# ═══════════════════════════════════════════════════════════════════
set -e

VERSION="2.1"
REPO="coapis-ai/coapis-agent"
INSTALL_DIR="${COAPIS_INSTALL_DIR:-/opt/coapis}"
COMPOSE_URL="https://raw.githubusercontent.com/${REPO}/main/docker-compose.yml"
ENV_EXAMPLE_URL="https://raw.githubusercontent.com/${REPO}/main/.env.example"

# ── 镜像版本配置 ──────────────────────────────────────────────────
# 查看可用版本: https://github.com/coapis-ai/coapis-agent/pkgs/container/server
DEFAULT_VERSION="v0.9.11"
COAPIS_VERSION="${COAPIS_VERSION:-$DEFAULT_VERSION}"
COAPIS_IMAGE="ghcr.io/${REPO}/server:${COAPIS_VERSION}"

# ── 默认选项 ──────────────────────────────────────────────────────
MODE="standard"         # standard | source | dev
WITH_PLAYWRIGHT=false
UPDATE_ONLY=false
UNINSTALL=false

# ── 颜色输出 ──────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${CYAN}ℹ ${NC}$*"; }
ok()    { echo -e "${GREEN}✅ $*${NC}"; }
warn()  { echo -e "${YELLOW}⚠️  $*${NC}"; }
fail()  { echo -e "${RED}❌ $*${NC}"; exit 1; }
step()  { echo -e "\n${BLUE}━━━ $* ━━━${NC}"; }

# ── 帮助信息 ──────────────────────────────────────────────────────
show_help() {
    echo ""
    echo "╔═══════════════════════════════════════════════╗"
    echo "║       🦀 CoApis Installer v${VERSION}            ║"
    echo "║   Multi-user AI Agent Platform                 ║"
    echo "╚═══════════════════════════════════════════════╝"
    echo ""
    echo "用法: bash install.sh [选项]"
    echo ""
    echo "选项:"
    echo "  (无参数)          标准安装（预构建镜像）"
    echo "  --source          源码构建模式（需要 Git + Node.js）"
    echo "  --with-playwright 包含浏览器自动化服务"
    echo "  --update          仅更新到最新版本"
    echo "  --uninstall       卸载 CoApis"
    echo "  --dir DIR         指定安装目录（默认 /opt/coapis）"
    echo "  --port PORT       指定 Web 端口（默认 4200）"
    echo "  --help            显示此帮助"
    echo ""
    echo "示例:"
    echo "  bash install.sh                          # 标准安装"
    echo "  bash install.sh --source --with-playwright  # 源码构建 + 浏览器服务"
    echo "  bash install.sh --update                  # 更新到最新版"
    echo ""
}

# ── 解析参数 ──────────────────────────────────────────────────────
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --source)
                MODE="source"
                shift
                ;;
            --dev)
                MODE="dev"
                shift
                ;;
            --with-playwright)
                WITH_PLAYWRIGHT=true
                shift
                ;;
            --update)
                UPDATE_ONLY=true
                shift
                ;;
            --uninstall)
                UNINSTALL=true
                shift
                ;;
            --dir)
                INSTALL_DIR="$2"
                shift 2
                ;;
            --port)
                CUSTOM_PORT="$2"
                shift 2
                ;;
            --help|-h)
                show_help
                exit 0
                ;;
            *)
                warn "未知选项: $1"
                show_help
                exit 1
                ;;
        esac
    done
}

# ── Banner ────────────────────────────────────────────────────────
show_banner() {
    echo ""
    echo "╔═══════════════════════════════════════════════╗"
    echo "║       🦀 CoApis Installer v${VERSION}            ║"
    echo "║   Multi-user AI Agent Platform                 ║"
    echo "╚═══════════════════════════════════════════════╝"
    echo ""
    
    case ${MODE} in
        standard) 
            info "安装模式: 标准安装"
            info "镜像版本: ${COAPIS_VERSION}"
            info "镜像地址: ${COAPIS_IMAGE}"
            ;;
        source)   info "安装模式: 源码构建" ;;
        dev)      info "安装模式: 开发模式（本地运行）" ;;
    esac
    
    ${WITH_PLAYWRIGHT} && info "浏览器服务: 包含 Playwright"
    ${UPDATE_ONLY} && info "操作: 更新到最新版本"
    ${UNINSTALL} && info "操作: 卸载 CoApis"
}

# ── 1. 检测环境 ──────────────────────────────────────────────────
check_environment() {
    step "1. 检测环境"
    
    # Docker
    if ! command -v docker &>/dev/null; then
        fail "Docker 未安装。请先安装 Docker:\n   https://docs.docker.com/get-docker/"
    fi
    DOCKER_VERSION=$(docker --version | grep -oP '\d+\.\d+\.\d+' | head -1)
    ok "Docker ${DOCKER_VERSION} 已安装"
    
    # Docker Compose
    if docker compose version &>/dev/null; then
        COMPOSE_CMD="docker compose"
        ok "Docker Compose (plugin) 可用"
    elif command -v docker-compose &>/dev/null; then
        COMPOSE_CMD="docker-compose"
        ok "Docker Compose (standalone) 可用"
    else
        fail "Docker Compose 未安装。请安装 Docker Compose:\n   https://docs.docker.com/compose/install/"
    fi
    
    # 源码模式需要额外工具
    if [[ "${MODE}" == "source" ]] || [[ "${MODE}" == "dev" ]]; then
        # Git
        if ! command -v git &>/dev/null; then
            fail "源码模式需要 Git，请先安装: apt install git"
        fi
        ok "Git $(git --version | awk '{print $3}') 已安装"
        
        # Node.js
        if ! command -v node &>/dev/null; then
            fail "源码模式需要 Node.js，请先安装: https://nodejs.org/"
        fi
        ok "Node.js $(node --version) 已安装"
        
        # npm
        if ! command -v npm &>/dev/null; then
            fail "源码模式需要 npm，请先安装 Node.js"
        fi
        ok "npm $(npm --version) 已安装"
    fi
}

# ── 2. 卸载 ──────────────────────────────────────────────────────
do_uninstall() {
    step "2. 卸载 CoApis"
    
    if [ ! -d "${INSTALL_DIR}" ]; then
        warn "安装目录不存在: ${INSTALL_DIR}"
        exit 0
    fi
    
    echo ""
    warn "即将删除以下内容:"
    echo "   - 安装目录: ${INSTALL_DIR}"
    echo "   - Docker 容器和镜像"
    echo "   - 数据卷 (可选)"
    echo ""
    
    read -p "确认卸载？(y/N): " CONFIRM
    if [[ "${CONFIRM}" != "y" ]] && [[ "${CONFIRM}" != "Y" ]]; then
        info "已取消卸载"
        exit 0
    fi
    
    # 停止并删除容器
    cd "${INSTALL_DIR}"
    ${COMPOSE_CMD} down --remove-orphans 2>/dev/null || true
    
    # 询问是否删除数据
    echo ""
    read -p "是否删除数据卷（包含所有用户数据）？(y/N): " DELETE_DATA
    if [[ "${DELETE_DATA}" == "y" ]] || [[ "${DELETE_DATA}" == "Y" ]]; then
        ${COMPOSE_CMD} down -v 2>/dev/null || true
        rm -rf "${INSTALL_DIR}"
        ok "已删除安装目录和数据"
    else
        ${COMPOSE_CMD} down 2>/dev/null || true
        rm -rf "${INSTALL_DIR}"
        ok "已删除安装目录（保留数据卷）"
    fi
    
    ok "卸载完成"
    exit 0
}

# ── 3. 更新 ──────────────────────────────────────────────────────
do_update() {
    step "3. 更新 CoApis"
    
    if [ ! -d "${INSTALL_DIR}" ]; then
        fail "安装目录不存在: ${INSTALL_DIR}\n请先执行安装"
    fi
    
    cd "${INSTALL_DIR}"
    
    # 标准模式：拉取最新镜像
    if [ -f "docker-compose.yml" ]; then
        info "拉取最新镜像..."
        ${COMPOSE_CMD} pull
        
        info "重启服务..."
        ${COMPOSE_CMD} up -d
        
        ok "更新完成"
        exit 0
    fi
    
    # 源码模式：拉取代码并重新构建
    if [ -d "source" ]; then
        info "更新源码..."
        cd source
        git pull
        
        info "重新构建前端..."
        cd client && npm ci && npm run build && cd ..
        
        info "重新构建并启动服务..."
        docker compose -f docker-compose.build.yml up -d --build
        
        ok "更新完成"
        exit 0
    fi
    
    warn "未找到可更新的安装，请重新安装"
}

# ── 4. 创建安装目录 ──────────────────────────────────────────────
create_install_dir() {
    step "4. 创建安装目录"
    
    info "安装目录: ${INSTALL_DIR}"
    
    if [ -d "${INSTALL_DIR}" ]; then
        if [ -f "${INSTALL_DIR}/docker-compose.yml" ] || [ -d "${INSTALL_DIR}/source" ]; then
            warn "检测到已有安装"
            read -p "是否覆盖现有安装？(y/N): " OVERWRITE
            if [[ "${OVERWRITE}" != "y" ]] && [[ "${OVERWRITE}" != "Y" ]]; then
                info "已取消"
                exit 0
            fi
        fi
    fi
    
    mkdir -p "${INSTALL_DIR}"
    ok "安装目录已创建"
}

# ── 5. 配置 ──────────────────────────────────────────────────────
configure() {
    step "5. 配置"
    
    # 读取已有配置
    if [ -f "${INSTALL_DIR}/.env" ]; then
        info "检测到已有配置"
        read -p "是否使用已有配置？(Y/n): " USE_EXISTING
        if [[ "${USE_EXISTING}" != "n" ]] && [[ "${USE_EXISTING}" != "N" ]]; then
            source "${INSTALL_DIR}/.env"
            ok "使用已有配置"
            return
        fi
    fi
    
    # 交互式配置
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    info "配置向导"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    
    # LLM API Key
    read -p "LLM API Key (如 OpenAI sk-xxx，稍后可配置): " API_KEY
    
    # 访问端口
    if [ -n "${CUSTOM_PORT}" ]; then
        PORT="${CUSTOM_PORT}"
    else
        read -p "Web 访问端口 [4200]: " PORT
        PORT=${PORT:-4200}
    fi
    
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
}

# ── 6. 标准安装 ──────────────────────────────────────────────────
install_standard() {
    step "6. 拉取镜像并启动"
    
    cd "${INSTALL_DIR}"
    
    # 下载 docker-compose.yml
    info "下载 docker-compose.yml..."
    if curl -fsSL "${COMPOSE_URL}" -o "${INSTALL_DIR}/docker-compose.yml" 2>/dev/null; then
        ok "docker-compose.yml 已下载"
    else
        warn "下载失败，自动生成配置..."
        generate_compose_file
    fi
    
    # 如果需要 Playwright，下载对应配置
    if ${WITH_PLAYWRIGHT}; then
        info "下载 Playwright 配置..."
        curl -fsSL "https://raw.githubusercontent.com/${REPO}/main/docker/docker-compose.playwright.yml" \
            -o "${INSTALL_DIR}/docker-compose.playwright.yml" 2>/dev/null || true
    fi
    
    # 拉取镜像
    info "拉取镜像: ${COAPIS_IMAGE}"
    info "（可能需要几分钟...）"
    ${COMPOSE_CMD} pull
    
    # 启动服务
    info "启动服务..."
    ${COMPOSE_CMD} up -d
    
    if ${WITH_PLAYWRIGHT}; then
        info "启动 Playwright 服务..."
        ${COMPOSE_CMD} -f docker-compose.yml -f docker-compose.playwright.yml up -d
    fi
    
    # 等待就绪
    wait_for_ready
    
    ok "安装完成"
}

# ── 7. 源码安装 ──────────────────────────────────────────────────
install_source() {
    step "6. 源码构建安装"
    
    cd "${INSTALL_DIR}"
    
    # 克隆代码
    if [ ! -d "source" ]; then
        info "克隆代码仓库..."
        git clone "https://github.com/${REPO}.git" source
    else
        info "更新代码..."
        cd source && git pull && cd ..
    fi
    
    cd source
    
    # 构建前端
    info "构建前端..."
    cd client
    npm ci
    npm run build
    cd ..
    
    # 配置
    if [ ! -f ".env" ]; then
        info "配置环境变量..."
        cp docker/.env.example .env 2>/dev/null || true
        # 使用主 .env
        cp "${INSTALL_DIR}/.env" .env 2>/dev/null || true
    fi
    
    # 构建并启动
    info "构建 Docker 镜像并启动服务..."
    docker compose -f docker/docker-compose.build.yml up -d --build
    
    # 等待就绪
    wait_for_ready
    
    ok "源码安装完成"
}

# ── 8. 开发模式安装 ──────────────────────────────────────────────
install_dev() {
    step "6. 开发模式安装"
    
    cd "${INSTALL_DIR}"
    
    # 克隆代码（如果还没有）
    if [ ! -d "source" ]; then
        info "克隆代码仓库..."
        git clone "https://github.com/${REPO}.git" source
    fi
    
    cd source
    
    # 安装前端依赖
    info "安装前端依赖..."
    cd client
    npm ci
    
    # 安装后端依赖
    info "安装后端依赖..."
    cd ../server
    pip install -e .
    cd ..
    
    # 配置
    if [ ! -f ".env" ]; then
        cp docker/.env.example .env 2>/dev/null || true
        cp "${INSTALL_DIR}/.env" .env 2>/dev/null || true
    fi
    
    echo ""
    ok "开发环境安装完成"
    echo ""
    info "启动方式:"
    echo "  终端 1 (后端): cd ${INSTALL_DIR}/source/server && python -m coapis run"
    echo "  终端 2 (前端): cd ${INSTALL_DIR}/source/client && npm run dev"
    echo ""
}

# ── 等待服务就绪 ────────────────────────────────────────────────
wait_for_ready() {
    info "等待服务就绪..."
    
    local port="${PORT:-4200}"
    for i in $(seq 1 30); do
        if curl -sf "http://localhost:${port}/api/health" > /dev/null 2>&1; then
            ok "服务就绪"
            return
        fi
        if [ "$i" = "30" ]; then
            warn "服务启动超时，请检查日志: ${COMPOSE_CMD} logs"
        fi
        sleep 2
    done
}

# ── 生成 compose 文件（备用） ───────────────────────────────────
generate_compose_file() {
    cat > "${INSTALL_DIR}/docker-compose.yml" <<COMPOSEEOF
services:
  server:
    image: ${COAPIS_IMAGE}
    container_name: coapis
    ports:
      - "\${COAPIS_PORT:-4200}:8000"
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
}

# ── 9. 输出安装信息 ──────────────────────────────────────────────
show_success() {
    local port="${PORT:-4200}"
    
    echo ""
    echo "╔═══════════════════════════════════════════════╗"
    echo "║       🎉 CoApis 安装成功！                  ║"
    echo "╚═══════════════════════════════════════════════╝"
    echo ""
    echo "  🌐 访问地址:  http://localhost:${port}"
    echo "  👤 默认账号:  admin"
    echo "  🔑 默认密码:  admin123"
    echo "  📁 安装目录:  ${INSTALL_DIR}"
    echo ""
    echo "  常用命令:"
    echo "    启动服务:  cd ${INSTALL_DIR} && ${COMPOSE_CMD} up -d"
    echo "    停止服务:  cd ${INSTALL_DIR} && ${COMPOSE_CMD} down"
    echo "    查看日志:  cd ${INSTALL_DIR} && ${COMPOSE_CMD} logs -f"
    echo "    更新版本:  bash install.sh --update"
    echo ""
    echo "  ⚠️  首次登录后请立即修改默认密码！"
    echo ""
}

# ═══════════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════════
main() {
    parse_args "$@"
    show_banner
    
    # 卸载
    if ${UNINSTALL}; then
        check_environment
        do_uninstall
    fi
    
    # 更新
    if ${UPDATE_ONLY}; then
        check_environment
        do_update
    fi
    
    # 安装流程
    check_environment
    create_install_dir
    configure
    
    case ${MODE} in
        standard) install_standard ;;
        source)   install_source ;;
        dev)      install_dev ;;
    esac
    
    show_success
}

main "$@"
