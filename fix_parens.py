#!/usr/bin/env python3
"""Fix double-parenthesis bug from assign_scenes.py: )) -> )"""
import re, glob, os

os.chdir('/apps/ai/tool-dev/devs/eater-claw')

fixed = 0
for f in sorted(glob.glob('server/coapis/agents/tools/*.py')):
    if '_auto_register' in f or '__init__' in f or 'registry' in f:
        continue
    with open(f) as fh:
        src = fh.read()
    
    # Fix: scene="xxx")) -> scene="xxx")
    new_src = re.sub(r'scene="(\w+)"\)\)', r'scene="\1")', src)
    
    if new_src != src:
        with open(f, 'w') as fh:
            fh.write(new_src)
        fixed += 1

print(f'Fixed {fixed} files')

# Verify
import ast
errors = []
for f in sorted(glob.glob('server/coapis/agents/tools/*.py')):
    if '_auto_register' in f or '__init__' in f or 'registry' in f:
        continue
    try:
        with open(f) as fh:
            ast.parse(fh.read())
    except SyntaxError as e:
        errors.append((f, str(e)))

if errors:
    for f, e in errors:
        print(f'❌ {f}: {e}')
else:
    print('All files parse OK ✅')
