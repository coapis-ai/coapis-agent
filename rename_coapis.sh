#!/bin/bash
# ═══════════════════════════════════════════════════════════
# EaterClaw → CoApis 一键改名脚本
# 用法: bash rename_coapis.sh [--dry-run]
# ═══════════════════════════════════════════════════════════
set -euo pipefail

DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

echo "🐝 CoApis Rename Script"
echo "========================"
echo "Mode: $($DRY_RUN && echo 'DRY RUN' || echo 'EXECUTE')"
echo ""

# ── Step 1: Python 包目录重命名 ──
echo "📁 Step 1: Renaming Python package directory..."
if [[ -d "server/eaterclaw" ]]; then
    if $DRY_RUN; then
        echo "  [DRY] mv server/eaterclaw → server/coapis"
    else
        mv server/eaterclaw server/coapis
        echo "  ✅ server/eaterclaw → server/coapis"
    fi
fi

# Enterprise edition
if [[ -d "enterprise/eaterclaw_enterprise" ]]; then
    if $DRY_RUN; then
        echo "  [DRY] mv enterprise/eaterclaw_enterprise → enterprise/coapis_enterprise"
    else
        mv enterprise/eaterclaw_enterprise enterprise/coapis_enterprise
        echo "  ✅ enterprise/eaterclaw_enterprise → enterprise/coapis_enterprise"
    fi
fi

# ── Step 2: Global text replacements in source code ──
echo ""
echo "📝 Step 2: Global text replacements..."

# 2a. Python import paths: from eaterclaw → from coapis, import eaterclaw → import coapis
echo "  2a. Python imports..."
if $DRY_RUN; then
    grep -rl "eaterclaw" server/ --include="*.py" 2>/dev/null | grep -v __pycache__ | wc -l | xargs echo "  [DRY] Would fix imports in"
else
    find server/ -name "*.py" -not -path "*__pycache__*" -exec sed -i 's/from eaterclaw/from coapis/g; s/import eaterclaw/import coapis/g; s/"eaterclaw"/"coapis"/g' {} +
    echo "  ✅ Python imports updated"
fi

# 2b. Python source strings (non-import references)
echo "  2b. Python source strings..."
if $DRY_RUN; then
    grep -rn "eaterclaw" server/ --include="*.py" 2>/dev/null | grep -v __pycache__ | wc -l | xargs echo "  [DRY] Would fix strings in"
else
    find server/ -name "*.py" -not -path "*__pycache__*" -exec sed -i 's/eaterclaw/coapis/g; s/EaterClaw/CoApis/g; s/EATERCLAW/COAPIS/g' {} +
    echo "  ✅ Python strings updated"
fi

# 2c. Frontend source
echo "  2c. Frontend source..."
if $DRY_RUN; then
    grep -rn "eaterclaw\|EaterClaw\|EATERCLAW" client/src/ --include="*.ts" --include="*.tsx" --include="*.less" --include="*.css" 2>/dev/null | wc -l | xargs echo "  [DRY] Would fix frontend in"
else
    find client/src/ -name "*.ts" -o -name "*.tsx" -o -name "*.less" -o -name "*.css" | xargs sed -i 's/eaterclaw/coapis/g; s/EaterClaw/CoApis/g; s/EATERCLAW/COAPIS/g'
    echo "  ✅ Frontend source updated"
fi

# 2d. i18n locales
echo "  2d. i18n locales..."
if $DRY_RUN; then
    echo "  [DRY] Would fix locales"
else
    find client/src/locales/ -name "*.json" | xargs sed -i 's/eaterclaw/coapis/g; s/EaterClaw/CoApis/g; s/EATERCLAW/COAPIS/g'
    echo "  ✅ Locales updated"
fi

# 2e. Config files (JSON, YAML, TOML, etc.)
echo "  2e. Config files..."
if $DRY_RUN; then
    echo "  [DRY] Would fix config files"
else
    # pyproject.toml
    sed -i 's/name = "eaterclaw"/name = "coapis-agent"/g; s/eaterclaw/coapis/g' server/pyproject.toml 2>/dev/null || true
    # package.json
    sed -i 's/"eaterclaw-console"/"coapis-console"/g; s/eaterclaw/coapis/g' client/package.json 2>/dev/null || true
    echo "  ✅ Config files updated"
fi

# ── Step 3: Docker/Deployment ──
echo ""
echo "🐳 Step 3: Docker/Deployment files..."
if $DRY_RUN; then
    echo "  [DRY] Would fix Docker files"
else
    find docker/ -name "*.yaml" -o -name "*.yml" -o -name "*.sh" -o -name "*.env*" -o -name "*.template" | xargs sed -i 's/eaterclaw/coapis/g; s/EaterClaw/CoApis/g; s/EATERCLAW/COAPIS/g'
    # Fix env var names specifically
    find docker/ -name ".env*" | xargs sed -i 's/EATERCLAW_/COAPIS_/g'
    echo "  ✅ Docker files updated"
fi

# ── Step 4: Documentation ──
echo ""
echo "📚 Step 4: Documentation..."
if $DRY_RUN; then
    echo "  [DRY] Would fix docs"
else
    find docs/ -name "*.md" | xargs sed -i 's/eaterclaw/coapis/g; s/EaterClaw/CoApis/g; s/EATERCLAW/COAPIS/g' 2>/dev/null || true
    sed -i 's/eaterclaw/coapis/g; s/EaterClaw/CoApis/g; s/EATERCLAW/COAPIS/g' README.md 2>/dev/null || true
    echo "  ✅ Documentation updated"
fi

# ── Step 5: Website ──
echo ""
echo "🌐 Step 5: Website..."
if $DRY_RUN; then
    echo "  [DRY] Would fix website"
else
    find website/ -name "*.html" -o -name "*.css" -o -name "*.js" | xargs sed -i 's/eaterclaw/coapis/g; s/EaterClaw/CoApis/g; s/EATERCLAW/COAPIS/g' 2>/dev/null || true
    echo "  ✅ Website updated"
fi

# ── Step 6: Rename static files ──
echo ""
echo "🎨 Step 6: Rename static asset files..."
if $DRY_RUN; then
    echo "  [DRY] Would rename static files"
else
    # Logo files
    for f in $(find server/coapis/app/static/ -name "*eaterclaw*" 2>/dev/null); do
        newname=$(echo "$f" | sed 's/eaterclaw/coapis/g')
        mv "$f" "$newname"
        echo "  ✅ $(basename $f) → $(basename $newname)"
    done
    # Script assets
    for f in $(find server/scripts/ -name "*eaterclaw*" 2>/dev/null); do
        newname=$(echo "$f" | sed 's/eaterclaw/coapis/g')
        mv "$f" "$newname"
        echo "  ✅ $(basename $f) → $(basename $newname)"
    done
fi

echo ""
echo "═══════════════════════════════════════════════"
echo "🐝 Rename complete! Next steps:"
echo "  1. git add -A && git commit"
echo "  2. git remote set-url origin <new-repo-url>"
echo "  3. git push -u origin master"
echo "═══════════════════════════════════════════════"
