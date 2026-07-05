# ═══════════════════════════════════════════════════════════════════
# CoApis Dockerfile — 源码构建版
# Build context: .. (项目根目录)
# Usage: cd docker && docker compose -f docker-compose.playwright.yml up -d --build
# ═══════════════════════════════════════════════════════════════════

FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONPATH=/app

# System dependencies (including Playwright browser deps)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    build-essential \
    libssl-dev \
    libffi-dev \
    ffmpeg \
    xclip \
    # Playwright Chromium dependencies
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

# App directory
WORKDIR /app

# Copy server package (the main Python package)
COPY server/coapis ./coapis
COPY server/pyproject.toml ./pyproject.toml
COPY server/setup.py ./setup.py

# Copy pre-built frontend (console)
RUN mkdir -p ./coapis/console
COPY client/dist ./coapis/console

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Install browser-use + playwright packages (Chromium runs in separate container)
RUN pip install --no-cache-dir playwright browser-use \
    && echo "✅ browser-use + playwright packages installed in image"

# Copy deployment scripts
COPY server/deploy/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY server/deploy/init_workspace.sh /usr/local/bin/init_workspace.sh
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/init_workspace.sh

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=60s \
    CMD curl -sf http://localhost:8000/api/health || exit 1

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
