#!/bin/bash
# 修复残留的 coapis 引用
cd /apps/ai/tool-dev/dev-coapis/coapis-agent

grep -ri "coapis\|CoApis\|COAPIS" \
  --include="*.py" --include="*.ts" --include="*.tsx" \
  --include="*.json" --include="*.yaml" --include="*.yml" \
  --include="*.env" --include="*.sh" --include="*.html" \
  --include="*.less" --include="*.css" --include="*.toml" \
  -rl 2>/dev/null \
  | grep -v node_modules \
  | grep -v __pycache__ \
  | grep -v .git \
  | grep -v dist \
  | grep -v rename_coapis \
  | grep -v fix_residual \
  | grep -v package-lock.json \
  | while IFS= read -r f; do
    sed -i 's/coapis/coapis/g; s/CoApis/CoApis/g; s/COAPIS/COAPIS/g; s/Coapis/Coapis/g' "$f"
    echo "fixed: $f"
done

echo "=== verification ==="
remaining=$(grep -ri "coapis\|CoApis\|COAPIS" \
  --include="*.py" --include="*.ts" --include="*.tsx" \
  --include="*.json" --include="*.yaml" --include="*.yml" \
  --include="*.env" --include="*.sh" --include="*.html" \
  --include="*.less" --include="*.css" --include="*.toml" \
  -rl 2>/dev/null \
  | grep -v node_modules \
  | grep -v __pycache__ \
  | grep -v .git \
  | grep -v dist \
  | grep -v rename_coapis \
  | grep -v fix_residual \
  | grep -v package-lock.json \
  | wc -l)
echo "remaining files: $remaining"
