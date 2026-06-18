# -*- coding: utf-8 -*-
"""端到端全面验证脚本 — 智能体、工具、技能、进化、安全、审计、统计"""
import requests
import json

BASE = "http://localhost:4103"
results = {"pass": 0, "fail": 0, "details": []}


def check(name, condition, detail=""):
    if condition:
        results["pass"] += 1
        results["details"].append(f"  ✓ {name}")
        print(f"  ✓ {name}")
    else:
        results["fail"] += 1
        results["details"].append(f"  ✗ {name}: {detail}")
        print(f"  ✗ {name}: {detail}")


# ── 登录 ──
r = requests.post(f"{BASE}/api/auth/login", json={"username": "admin", "password": "admin123"})
token = r.json().get("token", "")
H = {"Authorization": f"Bearer {token}"}
check("登录获取 Token", bool(token), r.text[:100])

# ── 1. 智能体 ──
print("\n=== 1. 智能体 ===")
r = requests.get(f"{BASE}/api/agents", headers=H)
agents = r.json() if r.status_code == 200 else []
if isinstance(agents, dict):
    agents = agents.get("agents", agents.get("items", []))
check("GET /api/agents", r.status_code == 200, f"{r.status_code}")
check("智能体数量 > 0", len(agents) > 0, f"count={len(agents)}")
for a in agents[:3]:
    print(f"    - {a.get('agent_id','?')} ({a.get('name','?')})")

# ── 2. 工具 ──
print("\n=== 2. 工具 ===")
r = requests.get(f"{BASE}/api/tools", headers=H)
tools = r.json() if r.status_code == 200 else []
if isinstance(tools, dict):
    tools = tools.get("tools", tools.get("items", []))
check("GET /api/tools", r.status_code == 200, f"{r.status_code}")
check("工具数量 > 10", len(tools) > 10, f"count={len(tools)}")

# ── 3. 技能 ──
print("\n=== 3. 技能 ===")
r = requests.get(f"{BASE}/api/skills", headers=H)
skills = r.json() if r.status_code == 200 else []
if isinstance(skills, dict):
    skills = skills.get("skills", skills.get("items", []))
check("GET /api/skills", r.status_code == 200, f"{r.status_code}")
check("技能数量 > 0", len(skills) > 0, f"count={len(skills)}")
for s in skills[:3]:
    print(f"    - {s.get('name','?')} v{s.get('version','?')}")

# ── 4. 审计日志 ──
print("\n=== 4. 审计日志 ===")
r = requests.get(f"{BASE}/api/audit/logs?limit=10", headers=H)
if r.status_code == 200:
    data = r.json()
    logs = data if isinstance(data, list) else data.get("logs", data.get("items", []))
else:
    logs = []
check("GET /api/audit/logs", r.status_code == 200, f"{r.status_code}")
check("审计日志有数据", len(logs) > 0, f"count={len(logs)}")
for l in logs[:3]:
    etype = l.get("event_type", l.get("type", "?"))
    desc = l.get("description", l.get("message", ""))[:50]
    print(f"    - [{etype}] {desc}")

# ── 5. 审计统计 ──
print("\n=== 5. 审计统计 ===")
r = requests.get(f"{BASE}/api/audit/stats", headers=H)
check("GET /api/audit/stats", r.status_code == 200, f"{r.status_code}")
if r.status_code == 200:
    stats = r.json()
    print(f"    - {json.dumps(stats, ensure_ascii=False)[:200]}")

# ── 6. 安全规则 ──
print("\n=== 6. 安全规则 ===")
r = requests.get(f"{BASE}/api/config/security/tool-guard/builtin-rules", headers=H)
check("GET /api/config/security/tool-guard/builtin-rules", r.status_code == 200, f"{r.status_code}")
if r.status_code == 200:
    rules = r.json()
    if isinstance(rules, dict):
        rules = rules.get("rules", rules.get("items", []))
    check("安全规则数量 > 20", len(rules) > 20, f"count={len(rules)}")
    print(f"    - {len(rules)} 条内置规则")

# ── 7. 技能效能指标（进化策略） ──
print("\n=== 7. 进化策略验证 ===")
r = requests.get(f"{BASE}/api/skills/metrics?limit=5", headers=H)
check("GET /api/skills/metrics", r.status_code == 200, f"{r.status_code}")
if r.status_code == 200:
    metrics = r.json()
    if isinstance(metrics, dict):
        metrics = metrics.get("metrics", metrics.get("items", []))
    print(f"    - 技能效能指标: {len(metrics)} 条")

# 用户维度指标
r = requests.get(f"{BASE}/api/skills/metrics/user/admin", headers=H)
check("GET /api/skills/metrics/user/admin", r.status_code == 200, f"{r.status_code}")
if r.status_code == 200:
    user_metrics = r.json()
    print(f"    - admin 用户维度: {json.dumps(user_metrics, ensure_ascii=False)[:150]}")

# ── 8. 角色配额验证 ──
print("\n=== 8. 记忆配额 ===")
r = requests.get(f"{BASE}/api/memory/quota", headers=H)
check("GET /api/memory/quota", r.status_code in [200, 404], f"{r.status_code}")
if r.status_code == 200:
    quota = r.json()
    print(f"    - {json.dumps(quota, ensure_ascii=False)[:150]}")

# ── 9. 知识流动统计 ──
print("\n=== 9. 知识流动 ===")
r = requests.get(f"{BASE}/api/evolution/knowledge-flow/stats", headers=H)
check("GET /api/evolution/knowledge-flow/stats", r.status_code in [200, 404], f"{r.status_code}")
if r.status_code == 200:
    kf = r.json()
    print(f"    - {json.dumps(kf, ensure_ascii=False)[:150]}")

# ── 10. 跨 Agent 进化 ──
print("\n=== 10. 跨 Agent 进化 ===")
r = requests.get(f"{BASE}/api/evolution/cross-agent/stats", headers=H)
check("GET /api/evolution/cross-agent/stats", r.status_code in [200, 404], f"{r.status_code}")
if r.status_code == 200:
    ca = r.json()
    print(f"    - {json.dumps(ca, ensure_ascii=False)[:150]}")

# ── 总结 ──
print("\n" + "=" * 50)
print(f"验证结果: {results['pass']} 通过 / {results['fail']} 失败 / {results['pass']+results['fail']} 总计")
if results["fail"] > 0:
    print("\n失败项:")
    for d in results["details"]:
        if "✗" in d:
            print(f"  {d}")
print("=" * 50)
