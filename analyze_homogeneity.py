#!/usr/bin/env python3
"""Deep homogeneity analysis: params overlap, desc overlap, low-value detection, cross-scene overlap."""
import re, glob, os
from collections import defaultdict

os.chdir('/apps/ai/tool-dev/devs/eater-claw')

tools = []
for f in sorted(glob.glob('server/coapis/agents/tools/*.py')):
    bn = os.path.basename(f)
    if bn in ('_auto_register.py', '__init__.py', 'registry.py', 'utils.py'):
        continue
    with open(f) as fh:
        src = fh.read()
    m = re.search(r'@register_tool\((.*?)\)\s*\n(?:async )?def (\w+)', src, re.DOTALL)
    if not m:
        continue
    block, fname = m.group(1), m.group(2)

    def grab(pat):
        x = re.search(pat, block)
        return x.group(1) if x else ''

    name = grab(r'name=["\']([^"\']+)["\']') or fname
    desc = grab(r'description=["\']([^"\']+)["\']')
    tags = re.findall(r'["\']([^"\']+)["\']', re.search(r'tags=\[(.*?)\]', block).group(1)) if re.search(r'tags=\[(.*?)\]', block) else []
    scene = grab(r'scene=["\']([^"\']+)["\']') or 'general'

    func_m = re.search(r'(?:async )?def ' + fname + r'\((.*?)\)', src, re.DOTALL)
    params = []
    if func_m:
        for line in func_m.group(1).split('\n'):
            p = line.strip().rstrip(',').split(':')[0].strip()
            if p and p != 'self':
                params.append(p)

    lines = len([l for l in src.split('\n') if l.strip() and not l.strip().startswith('#')])
    tools.append(dict(name=name, file=bn, desc=desc, tags=tags, scene=scene, params=params, lines=lines))

def kw(desc):
    return set(re.findall(r'[a-zA-Z_]{3,}', desc.lower())) | set(re.findall(r'[\u4e00-\u9fff]{2,4}', desc))

# 1. Param-identical groups
print("=" * 80)
print("1. 参数完全相同的工具组")
print("=" * 80)
pg = defaultdict(list)
for t in tools:
    pg[tuple(sorted(t['params']))].append(t)
for params, group in sorted(pg.items(), key=lambda x: -len(x[1])):
    if len(group) > 1:
        print(f"\n  params: {params}")
        for t in group:
            print(f"    {t['name']:30s} [{t['scene']:14s}] {t['desc'][:80]}")

# 2. Desc keyword overlap
print("\n\n" + "=" * 80)
print("2. 描述关键词高重叠对 (>=5 共同词)")
print("=" * 80)
pairs = []
for i in range(len(tools)):
    for j in range(i+1, len(tools)):
        c = kw(tools[i]['desc']) & kw(tools[j]['desc'])
        if len(c) >= 5:
            pairs.append((tools[i], tools[j], c))
pairs.sort(key=lambda x: -len(x[2]))
for t1, t2, c in pairs[:20]:
    print(f"\n  {t1['name']:30s} <-> {t2['name']:30s}  ({len(c)} 共同词)")
    print(f"    共同: {', '.join(sorted(c)[:12])}")
    print(f"    [{t1['name']}]: {t1['desc'][:90]}")
    print(f"    [{t2['name']}]: {t2['desc'][:90]}")

# 3. Same scene + tag overlap
print("\n\n" + "=" * 80)
print("3. 同场景 + 多标签重叠 (score >= 6)")
print("=" * 80)
by_scene = defaultdict(list)
for t in tools:
    by_scene[t['scene']].append(t)
for scene in sorted(by_scene):
    st = by_scene[scene]
    scored = []
    for i in range(len(st)):
        for j in range(i+1, len(st)):
            ct = set(st[i]['tags']) & set(st[j]['tags'])
            ck = kw(st[i]['desc']) & kw(st[j]['desc'])
            score = len(ct) * 3 + len(ck)
            if score >= 6:
                scored.append((st[i], st[j], ct, ck, score))
    scored.sort(key=lambda x: -x[4])
    for t1, t2, ct, ck, s in scored:
        print(f"  [{scene}] {t1['name']} <-> {t2['name']}  (score={s})")
        print(f"    tags: {ct or '-'}  keywords: {', '.join(sorted(ck)[:8]) or '-'}")

# 4. Low-value / weak tools
print("\n\n" + "=" * 80)
print("4. 疑似低价值工具 (弱信号 >= 3)")
print("=" * 80)
for t in sorted(tools, key=lambda x: (len(x['params']), len(x['tags']), len(x['desc']))):
    w = (1 if len(t['params']) <= 1 else 0) + (1 if len(t['tags']) <= 2 else 0) + (1 if len(t['desc']) < 30 else 0) + (1 if t['lines'] < 50 else 0)
    if w >= 3:
        print(f"  {t['name']:30s} [{t['scene']:14s}] weak={w}  params={t['params'][:3]}  tags={t['tags'][:3]}  lines={t['lines']}")
        print(f"    {t['desc'][:100]}")

# 5. Cross-scene concept sharing
print("\n\n" + "=" * 80)
print("5. 跨场景概念共享")
print("=" * 80)
ak = defaultdict(list)
for t in tools:
    for k in kw(t['desc']):
        if len(k) >= 3:
            ak[k].append(t)
for k, ts in sorted(ak.items(), key=lambda x: -len(x[1])):
    scenes = set(t['scene'] for t in ts)
    if len(scenes) > 1 and len(ts) > 1:
        ns = [f"{t['name']}({t['scene']})" for t in ts[:5]]
        print(f"  '{k}' -> {', '.join(ns)}")

# 6. Merge candidates (actionable)
print("\n\n" + "=" * 80)
print("6. 具体合并/清理建议")
print("=" * 80)
# code_formatter + code_docgen + code_review
print("\n  [coding] code_formatter + code_docgen + code_review → code_quality")
print("    三者都做代码质量相关：格式化 + 文档生成 + 审查")
print("    合并为 action 参数切换模式: format / docgen / review")

# knowledge_base + rag_search + embedding_ops
print("\n  [ai] knowledge_base + rag_search + embedding_ops → knowledge_rag")
print("    三者是 RAG 链条：embedding → 入库 → 检索")
print("    合并为统一知识管理工具: ingest / search / manage")

# perf_monitor + health_check + trace_ops
print("\n  [ops] perf_monitor + health_check + trace_ops → sys_monitor")
print("    三者都是监控：性能 + 健康 + 追踪")
print("    合并为统一监控工具: perf / health / trace")

# api_mock + schema_validate
print("\n  [general] api_mock + schema_validate → api_tools")
print("    两者都做 API 开发辅助")
print("    合并为统一 API 工具: mock / validate")

# checkpoint + error_recovery
print("\n  [ops] checkpoint_tool + error_recovery → fault_tolerance")
print("    checkpoint 做快照，error_recovery 做恢复，天然一对")
print("    合并为统一容错工具: checkpoint / recover")

# db_ops + cache_ops + queue_ops
print("\n  [data] db_ops + cache_ops + queue_ops → data_store")
print("    三者都是数据存储抽象")
print("    合并为统一存储工具: db / cache / queue")

# Summary
print("\n\n" + "=" * 80)
print("合并效果预估")
print("=" * 80)
print(f"  当前工具数: {len(tools)}")
merges = [
    ("code_formatter+code_docgen+code_review", 3, 1),
    ("knowledge_base+rag_search+embedding_ops", 3, 1),
    ("perf_monitor+health_check+trace_ops", 3, 1),
    ("api_mock+schema_validate", 2, 1),
    ("checkpoint_tool+error_recovery", 2, 1),
    ("db_ops+cache_ops+queue_ops", 3, 1),
]
saved = sum(old - new for _, old, new in merges)
print(f"  合并后: {len(tools) - saved} (减少 {saved} 个)")
print(f"  合并组数: {len(merges)}")
for names, old, new in merges:
    print(f"    {names}: {old} → {new}")
