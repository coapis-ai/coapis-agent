#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
# CoApis Workspace Initialization Script
# Creates all necessary directories and files for first-time startup
#
# This script runs automatically on first startup via entrypoint.sh.
# It delegates to the Python initializer for comprehensive setup.
# ═══════════════════════════════════════════════════════════════════
set -e

WORKING_DIR="${COAPIS_WORKING_DIR:-/apps/ai/coapis}"
SYSTEM_DIR="${WORKING_DIR}/system"

echo "=========================================="
echo "CoApis Workspace Initialization"
echo "=========================================="
echo "WORKING_DIR: ${WORKING_DIR}"
echo "=========================================="

# --- 方法1: 使用 Python 初始化器（推荐） ---
echo ""
echo "Attempting Python-based initialization..."

if python3 -c "from coapis.system import initialize_system" 2>/dev/null; then
    echo "Using Python initializer..."
    python3 -c "
import json
from coapis.system import initialize_system

result = initialize_system()
print('Initialization result:')
print(json.dumps(result, indent=2, ensure_ascii=False))

if result['success']:
    print('✅ Initialization completed successfully!')
else:
    print('❌ Initialization failed:', result.get('error', 'Unknown error'))
    exit(1)
"
    echo "✅ Python initialization complete!"
    exit 0
fi

# --- 方法2: 回退到 Shell 初始化（兼容旧版本） ---
echo "Python initializer not available, falling back to shell script..."

# Create core directories
echo ""
echo "Creating directory structure..."

mkdir -p "${WORKING_DIR}/logs"
mkdir -p "${WORKING_DIR}/skills"
mkdir -p "${WORKING_DIR}/agents"
mkdir -p "${WORKING_DIR}/media"
mkdir -p "${WORKING_DIR}/local_models"
mkdir -p "${WORKING_DIR}/memory"
mkdir -p "${WORKING_DIR}/.backups"
mkdir -p "${WORKING_DIR}/custom_channels"
mkdir -p "${WORKING_DIR}/plugins"
mkdir -p "${WORKING_DIR}/models"
mkdir -p "${WORKING_DIR}/skill_pool"
mkdir -p "${SYSTEM_DIR}/.secret"
mkdir -p "${WORKING_DIR}/workspaces"

echo "✓ Directory structure created"

# Create config.json if missing
if [ ! -f "${SYSTEM_DIR}/config.json" ]; then
    cat > "${SYSTEM_DIR}/config.json" << 'CFGEOF'
{
  "version": "0.8.12",
  "channels": {},
  "heartbeat": {
    "enabled": true,
    "every": 60,
    "query": "What should I work on next?"
  },
  "active_hours": {},
  "auth": {
    "enabled": false,
    "secret_key": "CHANGE_ME_TO_RANDOM_STRING"
  },
  "providers": {},
  "workspace": {
    "default_agent_name": "CoApis",
    "default_skills": ["guidance"]
  }
}
CFGEOF
    echo "✓ config.json created"
fi

# Create permissions.json if missing
if [ ! -f "${SYSTEM_DIR}/permissions.json" ]; then
    cat > "${SYSTEM_DIR}/permissions.json" << 'PERMEOF'
{
  "version": "2.0",
  "roles": {
    "user": {
      "name": "用户",
      "modules": "*"
    },
    "admin": {
      "name": "管理员",
      "modules": "*"
    }
  }
}
PERMEOF
    echo "✓ permissions.json created"
fi

# Create users.json if missing
if [ ! -f "${SYSTEM_DIR}/users.json" ]; then
    cat > "${SYSTEM_DIR}/users.json" << 'USEREOF'
{
  "users": {},
  "next_id": 1
}
USEREOF
    echo "✓ users.json created"
fi

# Create token_usage.json if missing
if [ ! -f "${SYSTEM_DIR}/token_usage.json" ]; then
    echo '{"version": 1, "daily": {}, "total": 0}' > "${SYSTEM_DIR}/token_usage.json"
    echo "✓ token_usage.json created"
fi

# Create token_usage_details.json if missing
if [ ! -f "${SYSTEM_DIR}/token_usage_details.json" ]; then
    echo '{"records": []}' > "${SYSTEM_DIR}/token_usage_details.json"
    echo "✓ token_usage_details.json created"
fi

# Create audit_logs.json if missing
if [ ! -f "${SYSTEM_DIR}/audit_logs.json" ]; then
    echo '[]' > "${SYSTEM_DIR}/audit_logs.json"
    echo "✓ audit_logs.json created"
fi

# Create auth.json if missing
if [ ! -f "${SYSTEM_DIR}/auth.json" ]; then
    echo '{"users": {}}' > "${SYSTEM_DIR}/auth.json"
    echo "✓ auth.json created"
fi

echo ""
echo "✅ Shell initialization complete!"
