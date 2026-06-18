#!/bin/sh
# CoApis Entrypoint Script
# Auto-initializes workspace on first startup, then starts the server
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Auto-initialize if config.json is missing
if [ ! -f "${COAPIS_WORKING_DIR}/config.json" ]; then
  echo "⚠️  No config.json found in ${COAPIS_WORKING_DIR}"
  echo "📦 Running initialization..."
  if [ -f "${SCRIPT_DIR}/init_workspace.sh" ]; then
    bash "${SCRIPT_DIR}/init_workspace.sh"
  else
    echo "❌ init_workspace.sh not found in ${SCRIPT_DIR}"
    echo "Fallback to coapis init command..."
    coapis init --defaults --accept-security
  fi
  echo "✅ Initialization complete!"
else
  echo "✓ Config found in ${COAPIS_WORKING_DIR}, skipping initialization."
fi

# Set Playwright browsers path to volume (avoids /root/.cache scatter)
export PLAYWRIGHT_BROWSERS_PATH=/app/volume/playwright

# Install browser automation if requested
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

# Start the backend server
echo ""
echo "Starting CoApis backend on port ${COAPIS_PORT:-8000}..."
exec uvicorn coapis.app._app:app --host 0.0.0.0 --port "${COAPIS_PORT:-8000}"
