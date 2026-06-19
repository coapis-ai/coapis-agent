#!/bin/sh
# ═══════════════════════════════════════════════════════════════════
# CoApis Entrypoint Script
# Auto-initializes workspace on first startup, then starts the server
# ═══════════════════════════════════════════════════════════════════
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKING_DIR="${COAPIS_WORKING_DIR:-/apps/ai/coapis}"
SYSTEM_DIR="${WORKING_DIR}/system"

echo "=========================================="
echo "CoApis Server Starting"
echo "=========================================="
echo "WORKING_DIR: ${WORKING_DIR}"
echo "SYSTEM_DIR:  ${SYSTEM_DIR}"
echo "=========================================="

# --- Auto-initialize if needed ---
# Check if core config files exist
NEED_INIT=false
if [ ! -f "${SYSTEM_DIR}/config.json" ]; then
    echo "⚠️  No config.json found"
    NEED_INIT=true
fi
if [ ! -f "${SYSTEM_DIR}/permissions.json" ]; then
    echo "⚠️  No permissions.json found"
    NEED_INIT=true
fi
if [ ! -f "${SYSTEM_DIR}/users.json" ]; then
    echo "⚠️  No users.json found"
    NEED_INIT=true
fi

if [ "${NEED_INIT}" = "true" ]; then
    echo ""
    echo "📦 Running initialization..."
    if [ -f "${SCRIPT_DIR}/init_workspace.sh" ]; then
        bash "${SCRIPT_DIR}/init_workspace.sh"
    else
        echo "❌ init_workspace.sh not found, trying coapis init..."
        coapis init --defaults --accept-security 2>/dev/null || true
    fi
    echo "✅ Initialization complete!"
else
    echo "✓ Core config files found, skipping initialization."
fi

# --- Set Playwright browsers path ---
export PLAYWRIGHT_BROWSERS_PATH=/app/volume/playwright

# --- Install browser automation if requested ---
if [ "${COAPIS_INSTALL_BROWSER}" = "1" ]; then
    if ! playwright --version > /dev/null 2>&1; then
        echo ""
        echo "🌐 Installing browser automation dependencies..."
        pip install --no-cache-dir playwright
        playwright install-deps chromium
        playwright install chromium
        echo "✅ Browser dependencies installed!"
    else
        echo "✓ Browser automation already installed."
    fi
else
    if playwright --version > /dev/null 2>&1; then
        echo "✓ Browser automation available."
    else
        echo "ℹ️  Browser automation not installed. Set COAPIS_INSTALL_BROWSER=1 to enable."
    fi
fi

# --- Run application-level migration ---
echo ""
echo "Running application migration..."
python3 -c "
import sys
sys.path.insert(0, '/app')
try:
    from coapis.app.migration import migrate_legacy_workspace_to_default_agent
    migrate_legacy_workspace_to_default_agent()
    print('✓ Application migration complete')
except Exception as e:
    print(f'⚠ Migration skipped: {e}')
" 2>/dev/null || echo "⚠ Application migration skipped"

# --- Start the backend server ---
echo ""
echo "🚀 Starting CoApis backend on port ${COAPIS_PORT:-8000}..."
exec uvicorn coapis.app._app:app --host 0.0.0.0 --port "${COAPIS_PORT:-8000}"
