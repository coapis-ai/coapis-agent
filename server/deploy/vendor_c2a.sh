#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# vendor_c2a.sh — 将 coapis-c2a 独立项目的 Python 包 vendor 进 build context
#
# coapis 对 C2A 采用「本地路径依赖」（依赖方案 A）：
#   - 前端：vite alias 直接引用 ../../coapis-c2a/typescript/c2a-renderer-react/src
#   - 后端：镜像构建时把 c2a_protocol / c2a_tools 拷入 server/_vendor_c2a 再 pip install
#
# 用法（在 docker compose build 之前执行）：
#   bash server/deploy/vendor_c2a.sh
#
# 环境变量：
#   C2A_ROOT — coapis-c2a 项目根目录（默认：与本仓库同级的 coapis-c2a/）
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
C2A_ROOT="${C2A_ROOT:-$(dirname "$REPO_ROOT")/coapis-c2a}"
DEST="$REPO_ROOT/server/_vendor_c2a"

if [ ! -d "$C2A_ROOT/server/c2a_protocol" ] || [ ! -d "$C2A_ROOT/server/c2a_tools" ]; then
  echo "❌ 未找到 coapis-c2a 的 Python 包：$C2A_ROOT/server/{c2a_protocol,c2a_tools}" >&2
  echo "   可用 C2A_ROOT=/path/to/coapis-c2a 指定项目位置" >&2
  exit 1
fi

rm -rf "$DEST"
mkdir -p "$DEST"
cp -r "$C2A_ROOT/server/c2a_protocol" "$DEST/"
cp -r "$C2A_ROOT/server/c2a_tools" "$DEST/"

# 清理构建产物，保持镜像干净
find "$DEST" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find "$DEST" -name "*.egg-info" -type d -exec rm -rf {} + 2>/dev/null || true

echo "✅ 已 vendor coapis-c2a 到 $DEST（c2a_protocol + c2a_tools）"
