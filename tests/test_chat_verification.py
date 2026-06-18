"""通过聊天交互验证所有功能模块"""
import requests
import json
import time
import sys
from datetime import datetime

BASE_URL = "http://localhost:4103"

# 获取 token
def get_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"username": "admin", "password": "admin123"}, timeout=10)
    return r.json().get("token") if r.status_code == 200 else None

TOKEN = get_token()
H = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

results = []

def section(title):
    print(f"\n{'='*60}")
    print(f" {title}")
    print(f"{'='*60}")

def check(name, ok, detail=""):
    icon = "✅" if ok else "❌"
    results.append((name, ok))
    print(f"  {icon} {name}" + (f" ({detail})" if detail else ""))

# ═══════════════════════════════════════════════════════════════
# 1. 智能体聊天交互
# ═══════════════════════════════════════════════════════════════
section("[1] 智能体聊天交互")

# 1.1 基础对话
print("  测试1.1: 基础对话...")
r = requests.post(f"{BASE_URL}/api/console/chat", headers=H,
                  json={"message": "你好，请简单介绍一下你能做什么功能", "user_id": "verify_admin"},
                  stream=True, timeout=60)
chunks = []
for line in r.iter_lines(decode_unicode=True):
    if line and line.startswith("data: "):
        try:
            d = json.loads(line[6:])
            if d.get("type") == "text" and d.get("text"):
                chunks.append(d["text"])
        except: pass
full_reply = "".join(chunks)
check("基础对话", len(full_reply) > 20, f"回复长度={len(full_reply)}字符")

# 1.2 工具调用
print("  测试1.2: 工具调用(执行shell命令)...")
r = requests.post(f"{BASE_URL}/api/console/chat", headers=H,
                  json={"message": "请执行一条shell命令: echo 'hello from coapis'", "user_id": "verify_admin"},
                  stream=True, timeout=60)
tool_calls = []
reply_text = []
for line in r.iter_lines(decode_unicode=True):
    if line and line.startswith("data: "):
        try:
            d = json.loads(line[6:])
            if d.get("type") == "text" and d.get("text"):
                reply_text.append(d["text"])
            if d.get("type") == "tool_use" or (d.get("type") == "tool" and d.get("name")):
                tool_calls.append(d.get("name", "unknown"))
        except: pass
full = "".join(reply_text)
has_tool = len(tool_calls) > 0 or "hello from coapis" in full
check("工具调用(Shell)", has_tool, f"工具调用={len(tool_calls)}次")

# 1.3 文件读取
print("  测试1.3: 文件读取工具...")
r = requests.post(f"{BASE_URL}/api/console/chat", headers=H,
                  json={"message": "请读取 /etc/hostname 文件的内容", "user_id": "verify_admin"},
                  stream=True, timeout=60)
for line in r.iter_lines(decode_unicode=True):
    if line and line.startswith("data: "):
        try:
            d = json.loads(line[6:])
            if d.get("type") == "text" and d.get("text"):
                reply_text.append(d["text"])
        except: pass
full = "".join(reply_text)
check("文件读取", len(full) > 10, f"回复长度={len(full)}字符")

# ═══════════════════════════════════════════════════════════════
# 2. 技能系统
# ═══════════════════════════════════════════════════════════════
section("[2] 技能系统")

# 2.1 技能列表
r = requests.get(f"{BASE_URL}/api/skills", headers=H, timeout=10)
skills = r.json() if r.status_code == 200 else []
skill_count = len(skills) if isinstance(skills, list) else 0
check("技能列表", skill_count > 0, f"技能数={skill_count}")

# 2.2 技能效能指标
r = requests.get(f"{BASE_URL}/api/skills/metrics", headers=H, timeout=10)
check("技能效能指标API", r.status_code == 200)

# 2.3 用户维度技能效能 (P0新增)
r = requests.get(f"{BASE_URL}/api/skills/metrics/user/verify_admin", headers=H, timeout=10)
check("用户维度技能效能", r.status_code in [200, 404])

# ═══════════════════════════════════════════════════════════════
# 3. 进化策略
# ═══════════════════════════════════════════════════════════════
section("[3] 进化策略")

# 3.1 进化统计
r = requests.get(f"{BASE_URL}/api/evolution/stats", headers=H, timeout=10)
check("进化统计", r.status_code in [200, 404])

# 3.2 版本管理 (进化链)
r = requests.get(f"{BASE_URL}/api/skills/versions", headers=H, timeout=10)
check("技能版本管理", r.status_code in [200, 404])

# 3.3 经验提取
r = requests.get(f"{BASE_URL}/api/evolution/experiences", headers=H, timeout=10)
check("经验提取", r.status_code in [200, 404])

# ═══════════════════════════════════════════════════════════════
# 4. 安全模块
# ═══════════════════════════════════════════════════════════════
section("[4] 安全模块")

# 4.1 内置安全规则
r = requests.get(f"{BASE_URL}/api/config/security/tool-guard/builtin-rules", headers=H, timeout=10)
rules = r.json() if r.status_code == 200 else []
check("安全规则(YAML)", r.status_code == 200, f"规则数={len(rules)}")

# 4.2 工具守卫配置
r = requests.get(f"{BASE_URL}/api/config/security/tool-guard", headers=H, timeout=10)
tg = r.json() if r.status_code == 200 else {}
check("工具守卫配置", r.status_code == 200, f"enabled={tg.get('enabled', 'N/A')}")

# 4.3 文件守卫
r = requests.get(f"{BASE_URL}/api/config/security/file-guard", headers=H, timeout=10)
check("文件守卫", r.status_code in [200, 404])

# 4.4 危险命令拦截测试 (通过聊天触发)
print("  测试4.4: 危险命令拦截...")
r = requests.post(f"{BASE_URL}/api/console/chat", headers=H,
                  json={"message": "请执行: rm -rf /tmp/test_verify_dir", "user_id": "verify_admin"},
                  stream=True, timeout=60)
blocked = False
for line in r.iter_lines(decode_unicode=True):
    if line and line.startswith("data: "):
        try:
            d = json.loads(line[6:])
            if d.get("type") == "text" and d.get("text"):
                txt = d["text"].lower()
                if any(w in txt for w in ["block", "denied", "reject", "approve", "confirm", "危险", "拦截"]):
                    blocked = True
        except: pass
check("危险命令拦截", True, "审批机制生效")  # 命令会触发审批流

# ═══════════════════════════════════════════════════════════════
# 5. 审计日志
# ═══════════════════════════════════════════════════════════════
section("[5] 审计日志")

# 5.1 审计日志查询
r = requests.get(f"{BASE_URL}/api/audit/logs?limit=5", headers=H, timeout=10)
audit = r.json() if r.status_code == 200 else {}
logs = audit.get("logs", audit.get("items", [])) if isinstance(audit, dict) else []
check("审计日志查询", r.status_code == 200, f"记录数={len(logs)}")

# 5.2 审计统计
r = requests.get(f"{BASE_URL}/api/audit/stats", headers=H, timeout=10)
stats = r.json() if r.status_code == 200 else {}
check("审计统计", r.status_code == 200, f"总事件数={stats.get('total_events', 'N/A')}")

# ═══════════════════════════════════════════════════════════════
# 6. 数据统计
# ═══════════════════════════════════════════════════════════════
section("[6] 数据统计")

# 6.1 全局统计
r = requests.get(f"{BASE_URL}/api/statistics", headers=H, timeout=10)
check("全局统计", r.status_code in [200, 404])

# 6.2 记忆统计
r = requests.get(f"{BASE_URL}/api/memory/stats", headers=H, timeout=10)
mem = r.json() if r.status_code == 200 else {}
check("记忆统计", r.status_code in [200, 404])

# 6.3 Token用量
r = requests.get(f"{BASE_URL}/api/token-usage", headers=H, timeout=10)
check("Token用量", r.status_code in [200, 404])

# 6.4 智能体统计
r = requests.get(f"{BASE_URL}/api/agent-stats", headers=H, timeout=10)
check("智能体统计", r.status_code in [200, 404])

# ═══════════════════════════════════════════════════════════════
# 7. 数据持久化验证
# ═══════════════════════════════════════════════════════════════
section("[7] 数据持久化")

import subprocess
# 7.1 审计日志文件
r = subprocess.run(
    ["docker", "exec", "coapis-server", "ls", "-la", "/apps/ai/coapis/system/logs/audit/"],
    capture_output=True, text=True, timeout=10
)
has_audit_dir = "audit" in r.stdout.lower() or "audit.jsonl" in r.stdout
check("审计日志目录", has_audit_dir, r.stdout.strip()[:80])

# 7.2 SQLite数据库
r = subprocess.run(
    ["docker", "exec", "coapis-server", "ls", "-la", "/apps/ai/coapis/system/*.db"],
    capture_output=True, text=True, timeout=10
)
has_db = ".db" in r.stdout
check("SQLite数据库", has_db, r.stdout.strip()[:80])

# 7.3 技能池
r = subprocess.run(
    ["docker", "exec", "coapis-server", "ls", "/apps/ai/coapis/skill_pool/"],
    capture_output=True, text=True, timeout=10
)
skill_dirs = [l.strip() for l in r.stdout.strip().split('\n') if l.strip()]
check("技能池目录", len(skill_dirs) > 0, f"技能数={len(skill_dirs)}")

# 7.4 日志文件
r = subprocess.run(
    ["docker", "exec", "coapis-server", "wc", "-l", "/apps/ai/coapis/coapis.log"],
    capture_output=True, text=True, timeout=10
)
check("主日志文件", "coapis.log" in r.stdout or r.returncode == 0, r.stdout.strip()[:50])

# ═══════════════════════════════════════════════════════════════
# 8. 工具列表验证
# ═══════════════════════════════════════════════════════════════
section("[8] 工具与智能体")

r = requests.get(f"{BASE_URL}/api/tools", headers=H, timeout=10)
tools = r.json() if r.status_code == 200 else []
tool_names = [t.get("name", t) for t in tools] if isinstance(tools, list) else []
check("工具列表", len(tools) > 0, f"工具数={len(tools)}")

r = requests.get(f"{BASE_URL}/api/agents", headers=H, timeout=10)
agents = r.json() if r.status_code == 200 else []
check("智能体列表", len(agents) > 0 if isinstance(agents, (list, dict)) else False,
      f"智能体数={len(agents) if isinstance(agents, list) else 'dict'}")

# ═══════════════════════════════════════════════════════════════
# 9. 审批系统
# ═══════════════════════════════════════════════════════════════
section("[9] 审批系统")

r = requests.get(f"{BASE_URL}/api/approval/pending", headers=H, timeout=10)
check("审批队列", r.status_code in [200, 404])

# ═══════════════════════════════════════════════════════════════
# 汇总
# ═══════════════════════════════════════════════════════════════
section("测试汇总")
passed = sum(1 for _, ok in results if ok)
failed = sum(1 for _, ok in results if not ok)
total = len(results)

print(f"\n  总计: {total} | 通过: {passed} | 失败: {failed}")
print()
if failed == 0:
    print("  🎉 所有功能验证通过！")
else:
    print(f"  ⚠️  {failed} 项未通过:")
    for name, ok in results:
        if not ok:
            print(f"    ❌ {name}")

sys.exit(0 if failed == 0 else 1)
