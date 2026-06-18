#!/bin/bash
# 修复残留的 eaterclaw 引用
cd /apps/ai/tool-dev/devs/eater-claw

grep -ri "eaterclaw\|EaterClaw\|EATERCLAW" \
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
    sed -i 's/eaterclaw/coapis/g; s/EaterClaw/CoApis/g; s/EATERCLAW/COAPIS/g; s/Eaterclaw/Coapis/g' "$f"
    echo "fixed: $f"
done

echo "=== verification ==="
remaining=$(grep -ri "eaterclaw\|EaterClaw\|EATERCLAW" \
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
