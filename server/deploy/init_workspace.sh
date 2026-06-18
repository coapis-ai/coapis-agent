#!/bin/bash
# CoApis Workspace Initialization Script
# Creates all necessary directories and files for first-time startup
# This script runs automatically on first startup via entrypoint.sh
set -e

WORKING_DIR="${COAPIS_WORKING_DIR:-/apps/ai/coapis}"
SYSTEM_DIR="${WORKING_DIR}/system"
WORKSPACES_DIR="${WORKING_DIR}/workspaces"

echo "=========================================="
echo "CoApis Workspace Initialization"
echo "=========================================="
echo "WORKING_DIR:    ${WORKING_DIR}"
echo "SYSTEM_DIR:     ${SYSTEM_DIR}"
echo "WORKSPACES_DIR: ${WORKSPACES_DIR}"
echo "=========================================="

# --- Create directory structure ---
echo ""
echo "Creating directory structure..."

# Core directories under WORKING_DIR
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

# System directory (unified system-level configs and data)
mkdir -p "${SYSTEM_DIR}/.secret"

# Workspaces directory (user-level data, isolated per user)
mkdir -p "${WORKSPACES_DIR}"

echo "✓ Directory structure created"

# --- Create essential files ---
echo ""
echo "Creating essential files..."

# config.json (in SYSTEM_DIR) - only if not exists
if [ ! -f "${SYSTEM_DIR}/config.json" ]; then
    cat > "${SYSTEM_DIR}/config.json" << 'CFGEOF'
{
  "channels": {},
  "heartbeat": {
    "enabled": true,
    "every": 60,
    "query": "What should I work on next?"
  },
  "active_hours": {},
  "auth": {
    "enabled": false,
    "secret_key": "default-secret-key-change-me"
  },
  "user_system": {
    "enabled": false,
    "points": {
      "login_daily": 5,
      "first_login": 20,
      "chat_per_session": 2,
      "agent_create": 10,
      "skill_create": 15,
      "mcp_config": 5,
      "doc_import": 3,
      "weekly_streak": 30,
      "monthly_streak": 100,
      "daily_cap": 50
    },
    "token_quota": {
      "L0": 100000,
      "L1": 1000000,
      "L2": 5000000,
      "L3": 20000000,
      "L4": -1
    },
    "rate_limit": {
      "L0": 10,
      "L1": 10,
      "L2": 50,
      "L3": 200,
      "L4": 1000
    }
  },
  "providers": {},
  "workspace": {
    "default_agent_name": "CoApis",
    "default_skills": ["guidance"]
  }
}
CFGEOF
    echo "✓ config.json created in SYSTEM_DIR"
else
    echo "⚠ config.json already exists in SYSTEM_DIR, skipping"
fi

# permissions.json (in SYSTEM_DIR) - only if not exists
if [ ! -f "${SYSTEM_DIR}/permissions.json" ]; then
    cat > "${SYSTEM_DIR}/permissions.json" << 'PERMEOF'
{
  "admin": {
    "modules": ["*"],
    "actions": ["*"]
  },
  "user": {
    "modules": ["chat", "myspace", "skills", "channels", "cron", "config"],
    "actions": ["read", "write"]
  }
}
PERMEOF
    echo "✓ permissions.json created"
else
    echo "⚠ permissions.json already exists, skipping"
fi

# users.json (in SYSTEM_DIR) - only if not exists
if [ ! -f "${SYSTEM_DIR}/users.json" ]; then
    echo '{"users":{},"next_id":1}' > "${SYSTEM_DIR}/users.json"
    echo "✓ users.json created in SYSTEM_DIR"
else
    echo "⚠ users.json already exists in SYSTEM_DIR, skipping"
fi

# auth.json (in SYSTEM_DIR) - only if not exists
if [ ! -f "${SYSTEM_DIR}/auth.json" ]; then
    echo '{"tokens":{},"sessions":{}}' > "${SYSTEM_DIR}/auth.json"
    echo "✓ auth.json created in SYSTEM_DIR"
else
    echo "⚠ auth.json already exists in SYSTEM_DIR, skipping"
fi

# skill_pool/skill.json - only if not exists
if [ ! -f "${WORKING_DIR}/skill_pool/skill.json" ]; then
    echo '{"skills":{}}' > "${WORKING_DIR}/skill_pool/skill.json"
    echo "✓ skill_pool/skill.json created"
else
    echo "⚠ skill_pool/skill.json already exists, skipping"
fi

# token_usage.json (in SYSTEM_DIR) - only if not exists
if [ ! -f "${SYSTEM_DIR}/token_usage.json" ]; then
    echo '{"usage":{}}' > "${SYSTEM_DIR}/token_usage.json"
    echo "✓ token_usage.json created in SYSTEM_DIR"
else
    echo "⚠ token_usage.json already exists in SYSTEM_DIR, skipping"
fi

echo ""
echo "=========================================="
echo "Initialization Complete!"
echo "=========================================="
