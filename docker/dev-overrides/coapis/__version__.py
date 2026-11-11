# dev 版本覆盖层 —— 运行时产物（git 里的值只是占位，不是真值）
#
# 机制：docker/dev/docker-compose.yml 把本文件单文件挂载到容器 /app/coapis/__version__.py，
#       容器启动时 entrypoint.sh 按环境变量 COAPIS_VERSION 覆写本文件内容。
#
# 为什么本文件必须保留在 git 里（不许 rm --cached / gitignore）：
#   单文件 bind mount 要求宿主源文件存在；缺失时 Docker 会把挂载源创建成目录，
#   而 entrypoint.sh 有 `set -e`，`cat >` 写目录直接失败 → 容器起不来。
#
# 为什么不再 commit 它的内容：
#   版本真值由 compose 的 COAPIS_VERSION 决定，容器每次启动自行覆写。
#   人为 commit "同步版本号" 会制造仓库值/运行值两套真相（旧 commit ed0a43a 即此病）。
#   本地纪律：git update-index --skip-worktree docker/dev-overrides/coapis/__version__.py
#
# 版本真值一律实测取：curl -s http://127.0.0.1:<后端端口>/api/version
__version__ = "0.0.0-dev"
