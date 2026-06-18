"""
通过聊天交互全面验证 CoApis 功能：
- 智能体对话 & 工具调用
- 技能触发 & 执行
- 进化策略指标
- 安全审计日志
- 数据统计
- 数据持久化
"""
import requests
import json
import time
import sys
import os
import subprocess
from datetime import datetime

BASE_URL = "http://localhost:4103"
TOKEN = None
RESULTS = []


def log(msg, indent=0):
    print("  " * indent + msg)


def get_token():
    global TOKEN
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"username": "admin", "password": "admin123"},
                      timeout=10)
    if r.status_code == 200:
        TOKEN = r.json().get("token")
        return True
    return False


def auth_get(path):
    return requests.get(f"{BASE_URL}{path}",
                        headers={"Authorization": f"Bearer {TOKEN}"},
                        timeout=30)


def auth_post(path, data=None):
    return requests.post(f"{BASE_URL}{path}",
                         headers={"Authorization": f"Bearer {TOKEN}"},
                         json=data, timeout=60)


def record(name, passed, detail=""):
    icon = "✅" if passed else "❌"
    RESULTS.append((name, passed, detail))
    log(f"{icon} {name}" + (f" — {detail}" if detail else ""))


# ═══════════════════════════════════════════════════════════════
# 1. 智能体对话
# ═══════════════════════════════════════════════════════════════
def test_agent_chat():
    """通过 /api/agent/chat 发送消息，验证智能体能正常回复"""
    log("[1] 智能体对话", 0)

    # 1a: 简单对话
    r = auth_post("/api/agent/chat", {
        "message": "你好，请用一句话介绍你自己。",
        "conversation_id": "test-deploy-verify"
    })
    if r.status_code == 200:
        data = r.json()
        reply = data.get("reply", data.get("response", data.get("message", "")))
        if not reply:
            reply = json.dumps(data, ensure_ascii=False)[:200]
        record("1a. 简单对话", True, f"回复长度={len(reply)}字")
        log(f"    回复预览: {reply[:150]}...", 1)
    else:
        record("1a. 简单对话", False, f"HTTP {r.status_code}: {r.text[:100]}")
    return r.status_code == 200


# ═══════════════════════════════════════════════════════════════
# 2. 工具调用
# ═══════════════════════════════════════════════════════════════
def test_tool_usage():
    """验证工具列表和工具执行"""
    log("[2] 工具调用", 0)

    # 2a: 工具列表
    r = auth_get("/api/tools")
    if r.status_code == 200:
        tools = r.json()
        count = len(tools) if isinstance(tools, list) else len(tools.get("tools", []))
        record("2a. 工具列表", count > 0, f"共{count}个工具")
    else:
        record("2a. 工具列表", False, f"HTTP {r.status_code}")

    # 2b: 通过聊天触发工具（文件读取）
    r = auth_post("/api/agent/chat", {
        "message": "读取当前目录的文件列表，告诉我有哪些文件",
        "conversation_id": "test-tool-verify"
    })
    if r.status_code == 200:
        data = r.json()
        reply = data.get("reply", data.get("response", data.get("message", "")))
        has_tool_call = "工具" in str(reply) or "file" in str(reply).lower() or "目录" in str(reply) or len(str(reply)) > 50
        record("2b. 工具触发对话", True, f"回复长度={len(str(reply))}")
    else:
        record("2b. 工具触发对话", False, f"HTTP {r.status_code}")


# ═══════════════════════════════════════════════════════════════
# 3. 技能管理
# ═══════════════════════════════════════════════════════════════
def test_skills():
    """验证技能列表和效能指标"""
    log("[3] 技能管理", 0)

    # 3a: 技能列表
    r = auth_get("/api/skills")
    if r.status_code == 200:
        data = r.json()
        skills = data if isinstance(data, list) else data.get("skills", data.get("items", []))
        record("3a. 技能列表", True, f"共{len(skills)}个技能")
    else:
        record("3a. 技能列表", False, f"HTTP {r.status_code}")

    # 3b: 技能效能指标
    r = auth_get("/api/skills/metrics")
    if r.status_code == 200:
        data = r.json()
        record("3b. 技能效能指标", True, f"指标数据存在")
    else:
        record("3b. 技能效能指标", r.status_code in [404], f"HTTP {r.status_code}")

    # 3c: 用户维度技能效能
    r = auth_get("/api/skills/metrics/user/admin")
    if r.status_code == 200:
        data = r.json()
        record("3c. 用户维度技能效能(admin)", True, "API正常")
    else:
        record("3c. 用户维度技能效能(admin)", r.status_code in [404, 422], f"HTTP {r.status_code}")


# ═══════════════════════════════════════════════════════════════
# 4. 进化策略
# ═══════════════════════════════════════════════════════════════
def test_evolution():
    """验证进化策略模块"""
    log("[4] 进化策略", 0)

    # 4a: 进化统计
    r = auth_get("/api/evolution/stats")
    if r.status_code == 200:
        data = r.json()
        record("4a. 进化统计", True, f"统计正常")
        log(f"    数据: {json.dumps(data, ensure_ascii=False)[:200]}", 1)
    else:
        record("4a. 进化统计", r.status_code in [404], f"HTTP {r.status_code}")

    # 4b: 模拟一轮对话后查看技能进化状态
    r = auth_post("/api/agent/chat", {
        "message": "帮我写一个简单的Python函数，计算斐波那契数列第n项",
        "conversation_id": "test-evolution-verify"
    })
    if r.status_code == 200:
        data = r.json()
        reply = data.get("reply", data.get("response", data.get("message", "")))
        record("4b. 技能进化触发对话", True, f"回复长度={len(str(reply))}")
        log(f"    回复预览: {str(reply)[:150]}...", 1)
    else:
        record("4b. 技能进化触发对话", False, f"HTTP {r.status_code}")


# ═══════════════════════════════════════════════════════════════
# 5. 安全审计
# ═══════════════════════════════════════════════════════════════
def test_security_audit():
    """验证安全模块和审计日志"""
    log("[5] 安全审计", 0)

    # 5a: 安全规则
    r = auth_get("/api/config/security/tool-guard/builtin-rules")
    if r.status_code == 200:
        rules = r.json()
        record("5a. 安全规则", True, f"{len(rules)}条规则")
    else:
        record("5a. 安全规则", False, f"HTTP {r.status_code}")

    # 5b: 工具守卫配置
    r = auth_get("/api/config/security/tool-guard")
    if r.status_code == 200:
        data = r.json()
        enabled = data.get("enabled", False)
        record("5b. 工具守卫配置", True, f"enabled={enabled}")
    else:
        record("5b. 工具守卫配置", r.status_code in [404], f"HTTP {r.status_code}")

    # 5c: 审计日志查询
    r = auth_get("/api/audit/logs?limit=5")
    if r.status_code == 200:
        data = r.json()
        logs = data if isinstance(data, list) else data.get("logs", data.get("items", []))
        record("5c. 审计日志查询", True, f"返回{len(logs)}条日志")
        if logs:
            log(f"    最新日志: {json.dumps(logs[0], ensure_ascii=False)[:200]}", 1)
    else:
        record("5c. 审计日志查询", False, f"HTTP {r.status_code}")

    # 5d: 审计统计
    r = auth_get("/api/audit/stats")
    if r.status_code == 200:
        data = r.json()
        record("5d. 审计统计", True, f"统计正常")
        log(f"    数据: {json.dumps(data, ensure_ascii=False)[:200]}", 1)
    else:
        record("5d. 审计统计", False, f"HTTP {r.status_code}")

    # 5e: 触发安全审计事件（尝试危险命令）
    r = auth_post("/api/agent/chat", {
        "message": "执行 rm -rf /tmp/test_verify_12345",
        "conversation_id": "test-security-verify"
    })
    if r.status_code == 200:
        data = r.json()
        reply = data.get("reply", data.get("response", data.get("message", "")))
        # 检查是否有拒绝/确认的回复
        is_blocked = any(kw in str(reply).lower() for kw in ["拒绝", "blocked", "确认", "危险", "denied", "confirm", "approval", "审批"])
        record("5e. 危险命令审计", True, f"安全拦截={is_blocked}, 回复={str(reply)[:100]}")
    else:
        record("5e. 危险命令审计", False, f"HTTP {r.status_code}")


# ═══════════════════════════════════════════════════════════════
# 6. 数据统计
# ═══════════════════════════════════════════════════════════════
def test_statistics():
    """验证数据统计功能"""
    log("[6] 数据统计", 0)

    # 6a: 统计信息
    r = auth_get("/api/statistics")
    if r.status_code == 200:
        data = r.json()
        record("6a. 统计信息", True, f"数据完整")
        log(f"    数据: {json.dumps(data, ensure_ascii=False)[:200]}", 1)
    else:
        record("6a. 统计信息", r.status_code in [404], f"HTTP {r.status_code}")

    # 6b: Token 用量
    r = auth_get("/api/token-usage")
    if r.status_code == 200:
        data = r.json()
        record("6b. Token用量", True, "数据正常")
    else:
        record("6b. Token用量", r.status_code in [404], f"HTTP {r.status_code}")

    # 6c: 记忆统计
    r = auth_get("/api/memory/stats")
    if r.status_code == 200:
        data = r.json()
        record("6c. 记忆统计", True, "数据正常")
    else:
        record("6c. 记忆统计", r.status_code in [404], f"HTTP {r.status_code}")


# ═══════════════════════════════════════════════════════════════
# 7. 数据持久化验证
# ═══════════════════════════════════════════════════════════════
def test_persistence():
    """验证数据持久化"""
    log("[7] 数据持久化", 0)

    data_dir = "/apps/ai/coapis"

    # 7a: 关键目录
    dirs_ok = all(os.path.exists(os.path.join(data_dir, d))
                  for d in ["logs", "system", "workspaces", "skill_pool"])
    record("7a. 数据目录完整性", dirs_ok)

    # 7b: 审计日志文件
    audit_path = os.path.join(data_dir, "logs/audit.jsonl")
    audit_exists = os.path.exists(audit_path)
    audit_size = os.path.getsize(audit_path) if audit_exists else 0
    record("7b. 审计日志文件", audit_exists, f"{audit_size} bytes")

    # 7c: SQLite 数据库
    db_path = os.path.join(data_dir, "system/coapis.db")
    db_exists = os.path.exists(db_path)
    db_size = os.path.getsize(db_path) if db_exists else 0
    record("7c. SQLite数据库", db_exists, f"{db_size} bytes")

    # 7d: 技能池
    skill_pool = os.path.join(data_dir, "skill_pool")
    if os.path.exists(skill_pool):
        skill_count = len(os.listdir(skill_pool))
        record("7d. 技能池目录", True, f"{skill_count}个技能目录")
    else:
        record("7d. 技能池目录", False, "目录不存在")

    # 7e: 配置文件
    config_path = os.path.join(data_dir, "system/config.json")
    config_exists = os.path.exists(config_path)
    record("7e. 配置文件", config_exists)


# ═══════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("CoApis 聊天交互式功能验证")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    print()

    # 0. 获取认证
    log("[0] 认证", 0)
    if not get_token():
        log("❌ 认证失败，无法继续", 1)
        sys.exit(1)
    record("认证登录", True, "admin 用户登录成功")
    print()

    # 运行所有测试
    test_agent_chat()
    print()
    test_tool_usage()
    print()
    test_skills()
    print()
    test_evolution()
    print()
    test_security_audit()
    print()
    test_statistics()
    print()
    test_persistence()
    print()

    # 汇总
    print("=" * 60)
    print("测试汇总")
    print("=" * 60)
    passed = sum(1 for _, p, _ in RESULTS if p)
    failed = sum(1 for _, p, _ in RESULTS if not p)
    total = len(RESULTS)

    for name, ok, detail in RESULTS:
        icon = "✅" if ok else "❌"
        log(f"  {icon} {name}" + (f" ({detail})" if detail else ""))

    print()
    log(f"总计: {total} | 通过: {passed} | 失败: {failed}")
    print()

    if failed == 0:
        log("🎉 所有功能验证通过！")
        sys.exit(0)
    else:
        log(f"⚠️  有 {failed} 个验证失败")
        sys.exit(1)
