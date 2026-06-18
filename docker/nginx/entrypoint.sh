#!/bin/sh
set -e

# 环境变量 → nginx 配置模板替换
# 只替换 COAPIS_ 前缀的变量，避免误伤 nginx 内置变量（$host, $remote_addr 等）
export COAPIS_UPLOAD_MAX_BODY_SIZE="${COAPIS_UPLOAD_MAX_BODY_SIZE:-20}"

# 用 envsubst 仅替换指定变量，生成最终配置
envsubst '$COAPIS_UPLOAD_MAX_BODY_SIZE' \
  < /etc/nginx/conf.d/default.conf.template \
  > /etc/nginx/conf.d/default.conf

echo "[nginx-entrypoint] client_max_body_size = ${COAPIS_UPLOAD_MAX_BODY_SIZE}m"

# 启动 nginx（前台）
exec nginx -g 'daemon off;'
