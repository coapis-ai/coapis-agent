# ═══════════════════════════════════════════════════════════════════
# CoApis Dockerfile — 多目标构建（min / full）
#
# Build context: .. (项目根目录)
#
# 构建命令：
#   最小镜像: docker build --target min -t coapis-agent_min:VERSION .
#   全量镜像: docker build --target full -t coapis-agent:VERSION .
#   向后兼容: docker tag coapis-agent:VERSION coapis-agent:latest
#
# 体积参考：min ~1.0GB | full ~2.0GB
# ═══════════════════════════════════════════════════════════════════

# ───────────────────────────────────────────────────────────────────
# Stage 1: builder — 编译阶段（安装 build-essential，编译 C 扩展）
# ───────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

ENV DEBIAN_FRONTEND=noninteractive

# 编译依赖（只在这一层需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libssl-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# 先 COPY 依赖描述文件（很少变，缓存稳定）
COPY server/pyproject.toml ./pyproject.toml
COPY server/setup.py ./setup.py

# 创建最小包结构，让 pip install 能读取动态版本号
# 版本号为临时值，仅用于安装依赖；运行时使用 COPY 的完整源码
RUN mkdir -p coapis && \
    echo "__version__ = '0.0.0'" > coapis/__version__.py && \
    echo "" > coapis/__init__.py

# 安装依赖到独立前缀（改源码不触发重新安装）
RUN pip install --prefix=/install --no-cache-dir . && \
    rm -rf /install/lib/python3.11/site-packages/coapis*


# ───────────────────────────────────────────────────────────────────
# Stage 2: runtime-base — 运行时基础（只装运行时系统库，无编译工具）
# ───────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime-base

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONPATH=/app

# 只装运行时必需的系统库（不装 build-essential/gcc/g++）
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    ffmpeg \
    xclip \
    # Playwright Chromium 运行时依赖（min 镜像可选，full 镜像必需）
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libatspi2.0-0 \
    libwayland-client0 \
    && rm -rf /var/lib/apt/lists/*

# Node.js 20.x LTS — 供 stdio 类 MCP server 使用（npx/node 启动）
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

# 预装文档处理库（python-docx 用于生成 Word 文档，免 L2 审批阻塞）
RUN pip install --no-cache-dir python-docx==1.1.0 && \
    rm -rf /root/.cache/pip

# 从 builder 阶段复制编译好的 Python 包
COPY --from=builder /install /usr/local

WORKDIR /app

# 复制应用代码
COPY server/coapis ./coapis

# 复制预构建的前端
RUN mkdir -p ./coapis/console
COPY client/dist ./coapis/console

# 复制部署脚本
COPY server/deploy/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY server/deploy/init_workspace.sh /usr/local/bin/init_workspace.sh
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/init_workspace.sh

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=60s \
    CMD curl -sf http://localhost:8000/api/health || exit 1

EXPOSE 8000


# ───────────────────────────────────────────────────────────────────
# Stage 3: min — 最小镜像（核心 + browser-use，渠道包运行时按需装）
# ───────────────────────────────────────────────────────────────────
FROM runtime-base AS min

# 浏览器自动化 Python API（Chromium 在独立容器运行）
RUN pip install --no-cache-dir playwright browser-use \
    && echo "✅ min image: playwright + browser-use installed"

ENV COAPIS_IMAGE_VARIANT=min

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]


# ───────────────────────────────────────────────────────────────────
# Stage 4: full — 全量镜像（所有渠道 + 浏览器 + 全部可选依赖，离线可用）
# ───────────────────────────────────────────────────────────────────
FROM runtime-base AS full

# 浏览器自动化
RUN pip install --no-cache-dir playwright browser-use \
    && echo "✅ browser-use + playwright installed"

# 渠道 SDK（直接安装，不依赖 pyproject.toml）
RUN pip install --no-cache-dir \
    "discord-py>=2.3" \
    "dingtalk-stream>=0.24.3" \
    "alibabacloud-dingtalk>=2.2.42" \
    "lark-oapi>=1.5.3" \
    "python-telegram-bot>=20.0" \
    "twilio>=9.10.2" \
    "matrix-nio>=0.24.0" \
    && echo "✅ channel SDKs installed"

ENV COAPIS_IMAGE_VARIANT=full

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
