#!/usr/bin/env python3
"""Batch assign scene to all @register_tool decorators based on tool name mapping."""
import re, os

os.chdir('/apps/ai/tool-dev/dev-coapis/coapis-agent')

# Scene assignment map: tool_name -> scene
SCENE_MAP = {
    # core
    'read_file': 'core', 'write_file': 'core', 'edit_file': 'core',
    'grep_search': 'core', 'glob_search': 'core',
    'execute_shell_command': 'core', 'browser_use': 'core',
    'memory_manager': 'core', 'todo_tool': 'core',
    'send_file_to_user': 'core', 'get_current_time': 'core',
    'desktop_screenshot': 'core', 'view_image': 'core',
    'spawn_subagent': 'core', 'chat_with_agent': 'core',
    'submit_to_agent': 'core', 'check_agent_task': 'core',
    'view_video': 'core',
    # coding
    'code_runner': 'coding', 'code_formatter': 'coding', 'code_review': 'coding',
    'code_docgen': 'coding', 'file_diff': 'coding', 'ast_search': 'coding',
    'project_analyzer': 'coding', 'test_runner': 'coding',
    'text_processor': 'coding', 'session_search': 'coding',
    # ops
    'deploy_helper': 'ops', 'perf_monitor': 'ops', 'health_check': 'ops',
    'structured_logger': 'ops', 'trace_ops': 'ops',
    'cron_scheduler': 'ops', 'auto_heal': 'ops', 'tool_stats': 'ops',
    # data
    'data_processor': 'data', 'db_ops': 'data', 'cache_ops': 'data',
    'queue_ops': 'data', 'archive_ops': 'data', 'notes': 'data',
    'batch_ops': 'data',
    # security
    'secret_scan': 'security', 'dependency_audit': 'security',
    'audit_log': 'security', 'crypto_ops': 'security',
    'env_manager': 'security', 'resource_guard': 'security',
    # ai
    'llm_ops': 'ai', 'prompt_builder': 'ai', 'embedding_ops': 'ai',
    'knowledge_base': 'ai', 'rag_search': 'ai', 'image_gen': 'ai',
    'skill_manager': 'ai', 'agent_optimizer': 'ai',
    # collaboration
    'notify_ops': 'collaboration', 'shared_state': 'collaboration',
    'task_delegation': 'collaboration', 'workflow_engine': 'collaboration',
    # other
    'clipboard_ops': 'core', 'http_client': 'core',
    'checkpoint_tool': 'core', 'error_recovery': 'ops',
    'context_manager': 'core',
}

changed_files = []
already_set = []
not_found = []

for f in sorted(os.listdir('server/coapis/agents/tools')):
    if not f.endswith('.py') or f in ('_auto_register.py', '__init__.py', 'registry.py'):
        continue
    fpath = os.path.join('server/coapis/agents/tools', f)
    with open(fpath) as fh:
        src = fh.read()
    
    # Find tool name from @register_tool
    m = re.search(r'@register_tool\((.*?)\)\s*\n', src, re.DOTALL)
    if not m:
        continue
    block = m.group(1)
    name_m = re.search(r'name=["\']([^"\']+)["\']', block)
    if not name_m:
        # try def name
        def_m = re.search(r'@register_tool.*?\n(?:async )?def (\w+)', src, re.DOTALL)
        if def_m:
            tool_name = def_m.group(1)
        else:
            continue
    else:
        tool_name = name_m.group(1)
    
    # Check if scene already set
    if 'scene=' in block:
        already_set.append(tool_name)
        continue
    
    # Get scene from map
    scene = SCENE_MAP.get(tool_name, 'general')
    not_found.append((tool_name, scene))
    
    # Add scene= to @register_tool
    # Insert before closing paren
    new_block = block.rstrip()
    if new_block.endswith(')'):
        new_block = new_block[:-1]
    # Add scene parameter
    new_block += f',\n    scene="{scene}"'
    new_block += ')'
    
    new_src = src.replace(m.group(0), f'@register_tool({new_block})\n')
    
    with open(fpath, 'w') as fh:
        fh.write(new_src)
    changed_files.append((f, tool_name, scene))

print(f'Changed: {len(changed_files)} files')
print(f'Already set: {len(already_set)} tools')
print()
for f, name, scene in changed_files:
    print(f'  {f:40s} {name:30s} -> scene="{scene}"')
if already_set:
    print(f'\nAlready had scene: {", ".join(already_set)}')
