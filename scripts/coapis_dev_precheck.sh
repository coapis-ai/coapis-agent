#!/usr/bin/env bash
# 判断中枢 dev 预检一键入口（v14 §批次0）
#
# 用法：
#   bash scripts/coapis_dev_precheck.sh              # 自动选环境
#   COAPIS_DEV_CONTAINER=xxx bash scripts/coapis_dev_precheck.sh
#
# 两种 dev 部署，脚本都支持（v14 踩过的坑：尺子只能在一种环境跑，导致两次
# 体检口径对不上）：
#   1) 企业版 dev 容器：容器内有 COAPIS_DATABASE_URL（PostgreSQL）→ 进容器跑；
#   2) 社区版 dev 容器：SQLite，库文件挂在宿主 ${_DEV_DIR}/system/coapis.db
#      → 直接在宿主跑（宿主 venv + 仓库 server 目录进 PYTHONPATH）。
# 跑出来的第一行会写明连的是哪个库、几行、档位尺子是哪把、什么方言。
#
# 只读脚本：不改代码、不改配置、不写库。
set -euo pipefail

_repo="$(cd "$(dirname "$0")/.." && pwd)"
_dev_dir="${COAPIS_DEV_DIR:-/apps/ai/coapis-dev}"
_VENV="${COAPIS_PRECHECK_PY:-$_repo/../.venv-test/bin/python}"
_entry="$_repo/scripts/dev_precheck_db.py"
_pg_container="${COAPIS_PG_CONTAINER:-coapis-dev-coapis-server}"
_sqlite_container="${COAPIS_SQLITE_CONTAINER:-coapis-server-dev}"

_pick_container() {
    for c in "$@"; do
        if docker inspect "$c" >/dev/null 2>&1 \
           && [ "$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null)" = "true" ]; then
            echo "$c"; return 0
        fi
    done
    return 1
}

_url_in() {  # 容器里有 COAPIS_DATABASE_URL 就回显，没有回空
    docker exec "$1" printenv COAPIS_DATABASE_URL 2>/dev/null || true
}

if [ -n "${COAPIS_DEV_CONTAINER:-}" ]; then
    container="$COAPIS_DEV_CONTAINER"
    url="$(_url_in "$container")"
    [ -z "$url" ] && { echo "容器 $container 里没有 COAPIS_DATABASE_URL，无法预检" >&2; exit 1; }
    mode="容器 $container"
elif container="$(_pick_container "$_pg_container")" && [ -n "$(_url_in "$container")" ]; then
    url="$(_url_in "$container")"
    mode="容器 $container（PostgreSQL）"
elif container="$(_pick_container "$_sqlite_container")" && [ -f "$_dev_dir/system/coapis.db" ]; then
    url="sqlite:///${_dev_dir}/system/coapis.db"
    mode="宿主 SQLite（$_dev_dir/system/coapis.db，容器 $_sqlite_container 挂载）"
else
    echo "找不到可用的 dev 环境：既没有跑着的 PostgreSQL dev 容器，也没有 $_dev_dir/system/coapis.db" >&2
    exit 1
fi

[ -x "$_VENV" ] || _VENV="$(command -v python3)"
[ -f "$_entry" ] || { echo "预检脚本不存在：$_entry" >&2; exit 1; }

echo "== 判断中枢预检 · 数据源：$mode =="
if [ "${mode#容器}" != "$mode" ]; then
    # 容器模式：脚本和包都在镜像里，用镜像内的路径（宿主路径在容器里不存在）
    docker exec -w /app "$container" python3 "/app/scripts/$(basename "$_entry")" --url "$url"
else
    # 宿主模式：档位尺子（LEVELS）直接 import 仓库代码，和线上同一把
    PYTHONPATH="$_repo/server" "$_VENV" "$_entry" --url "$url"
fi
