#!/usr/bin/env python3
"""Analyze all registered tools: scene distribution, token estimation, overlap."""
import re, json, glob, os
from collections import Counter, defaultdict

os.chdir('/apps/ai/tool-dev/dev-coapis/coapis-agent')

tools = []
for f in sorted(glob.glob('server/coapis/agents/tools/*.py')):
    basename = os.path.basename(f)
    if '_auto_register' in basename or '__init__' in basename or 'registry' in basename:
        continue
    with open(f) as fh:
        src = fh.read()
    m = re.search(r'@register_tool\((.*?)\)\s*\n(?:async )?def (\w+)', src, re.DOTALL)
    if not m:
        continue
    block = m.group(1)
    fname = m.group(2)

    name_m = re.search(r'name=["\']([^"\']+)["\']', block)
    desc_m = re.search(r'description=["\']([^"\']+)["\']', block)
    tags_m = re.search(r'tags=\[(.*?)\]', block)
    scene_m = re.search(r'scene=["\']([^"\']+)["\']', block)

    tool_name = name_m.group(1) if name_m else fname
    tool_desc = desc_m.group(1)[:150] if desc_m else '(no desc)'
    tool_tags = re.findall(r'["\']([^"\']+)["\']', tags_m.group(1)) if tags_m else []
    tool_scene = scene_m.group(1) if scene_m else 'general'

    # token estimate: ~2 for name, desc_len/3 for desc, 2 per tag
    est_tokens = 2 + len(tool_desc) // 3 + len(tool_tags) * 2

    tools.append({
        'name': tool_name,
        'file': basename,
        'desc': tool_desc,
        'tags': tool_tags,
        'scene': tool_scene,
        'est_tokens': est_tokens,
    })

total_tokens = sum(t['est_tokens'] for t in tools)
print(f'Total tools: {len(tools)}')
print(f'Estimated total LLM tokens for all tools: ~{total_tokens}')
print()

# Scene distribution
scene_counts = Counter(t['scene'] for t in tools)
print('=== Scene Distribution ===')
for scene, count in scene_counts.most_common():
    tokens = sum(t['est_tokens'] for t in tools if t['scene'] == scene)
    print(f'  {scene:20s}: {count:2d} tools, ~{tokens:5d} tokens')

# Tag frequency
all_tags = []
for t in tools:
    all_tags.extend(t['tags'])
tag_counts = Counter(all_tags)
print()
print('=== Top 20 Tags ===')
for tag, count in tag_counts.most_common(20):
    print(f'  {tag:30s}: {count}')

# Find potential merges (tools with overlapping tags and same scene)
print()
print('=== Potential Overlap / Merge Candidates ===')
by_scene = defaultdict(list)
for t in tools:
    by_scene[t['scene']].append(t)

for scene, scene_tools in sorted(by_scene.items()):
    if len(scene_tools) < 2:
        continue
    # Find pairs with high tag overlap
    for i in range(len(scene_tools)):
        for j in range(i+1, len(scene_tools)):
            t1, t2 = scene_tools[i], scene_tools[j]
            common = set(t1['tags']) & set(t2['tags'])
            if len(common) >= 2:
                print(f'  [{scene}] {t1["name"]} <-> {t2["name"]}')
                print(f'    shared tags: {common}')
                print(f'    {t1["name"]}: {t1["desc"][:80]}')
                print(f'    {t2["name"]}: {t2["desc"][:80]}')
                print()

# Per-scene tool list
print()
print('=== Full Tool List by Scene ===')
for scene in sorted(by_scene.keys()):
    scene_tools = by_scene[scene]
    scene_tokens = sum(t['est_tokens'] for t in scene_tools)
    print(f'\n--- {scene} ({len(scene_tools)} tools, ~{scene_tokens} tokens) ---')
    for t in sorted(scene_tools, key=lambda x: x['name']):
        tags_str = ', '.join(t['tags'][:5])
        print(f'  {t["name"]:30s} | {tags_str:55s} | ~{t["est_tokens"]:3d}t')

# Token savings analysis
print()
print('=== Token Savings Scenarios ===')
# Scenario 1: Only load scene-relevant tools
print('Scenario 1: Scene-based dynamic injection')
for scene in sorted(by_scene.keys()):
    scene_tools = by_scene[scene]
    scene_tokens = sum(t['est_tokens'] for t in scene_tools)
    other_tokens = total_tokens - scene_tokens
    print(f'  If only [{scene}] loaded: {scene_tokens}/{total_tokens} tokens ({scene_tokens*100//total_tokens}%)')

# Scenario 2: Core + scene
core_names = {'read_file', 'write_file', 'edit_file', 'grep_search', 'glob_search',
              'execute_shell_command', 'browser_use', 'memory_manager', 'todo_tool',
              'send_file_to_user', 'get_current_time', 'desktop_screenshot', 'view_image',
              'spawn_subagent', 'chat_with_agent'}
core_tools = [t for t in tools if t['name'] in core_names]
core_tokens = sum(t['est_tokens'] for t in core_tools)
print(f'\nScenario 2: Core ({len(core_tools)} tools) + per-scene addon')
print(f'  Core tokens: ~{core_tokens}')
for scene in sorted(by_scene.keys()):
    scene_tools = by_scene[scene]
    scene_tokens = sum(t['est_tokens'] for t in scene_tools)
    combined = core_tokens + scene_tokens
    print(f'  Core + [{scene}]: {combined}/{total_tokens} tokens ({combined*100//total_tokens}%)')

# Scenario 3: Low-frequency removal
low_freq = {'audit_log', 'dependency_audit', 'embedding_ops', 'queue_ops', 
            'cache_ops', 'db_ops', 'notify_ops', 'shared_state', 'task_delegation',
            'structured_logger', 'trace_ops', 'health_check', 'changelog_gen',
            'schema_validate', 'api_mock', 'code_docgen', 'prompt_builder',
            'agent_optimizer', 'skill_manager', 'resource_guard', 'auto_heal'}
low_freq_tools = [t for t in tools if t['name'] in low_freq]
low_freq_tokens = sum(t['est_tokens'] for t in low_freq_tools)
print(f'\nScenario 3: Remove {len(low_freq_tools)} low-frequency tools')
print(f'  Saved: ~{low_freq_tokens} tokens ({low_freq_tokens*100//total_tokens}%)')
print(f'  Remaining: ~{total_tokens - low_freq_tokens} tokens')
