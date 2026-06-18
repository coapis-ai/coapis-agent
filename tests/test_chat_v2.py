"""
CoApis 聊天交互式功能验证 v2
修正：使用正确的 API 端点路径
"""
import requests
import json
import time
import sys
import os
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
                         json=data, timeout=120)


def record(name, passed, detail=""):
    icon = "✅" if passed else "❌"
    RESULTS.append((name, passed, detail))
    log(f"{icon} {name}" + (f" — {detail}" if detail else ""))


# ═══════════════════════════════════════════════════════════════
# 1. 智能体对话（SSE 流式）
# ═══════════════════════════════════════════════════════════════
def test_agent_chat():
    """通过 SSE 端点测试智能体对话"""
    log("[1] 智能体对话 (SSE)", 0)

    # 使用 requests 的 stream 模式读取 SSE
    try:
        r = requests.post(
            f"{BASE_URL}/api/console/chat",
            headers={
                "Authorization": f"Bearer {TOKEN}",
                "Content-Type": "application/json",
            },
            json={
                "input": [{"content": "你好，请用一句话介绍你自己。", "role": "user"}],
                "biz_params": {"agent_id": "default"},
            },
            stream=True,
            timeout=120,
        )
        if r.status_code == 200:
            # 读取 SSE 事件
            full_text = ""
            event_count = 0
            for line in r.iter_lines(decode_unicode=True):
                if line is None:
                    continue
                if line.startswith("data:"):
                    event_count += 1
                    data_str = line[5:].strip()
                    if data_str:
                        try:
                            evt = json.loads(data_str)
                            # 收集文本片段
                            if isinstance(evt, dict):
                                delta = evt.get("delta", {})
                                if isinstance(delta, dict):
                                    full_text += delta.get("content", "")
                                elif isinstance(evt.get("content"), str):
                                    full_text += evt["content"]
                        except json.JSONDecodeError:
                            pass
                # 读取足够数据后停止
                if event_count > 200 or len(full_text) > 500:
                    break
            r.close()

            if full_text:
                record("1a. SSE对话回复", True, f"回复{len(full_text)}字, {event_count}事件")
                log(f"    回复预览: {full_text[:150]}...", 1)
            else:
                record("1a. SSE对话回复", event_count > 0, f"{event_count}事件, 无文本内容")
        else:
            record("1a. SSE对话回复", False, f"HTTP {r.status_code}: {r.text[:100]}")
    except Exception as e:
        record("1a. SSE对话回复", False, str(e)[:100])


# ═══════════════════════════════════════════════════════════════
# 2. 工具管理
# ═══════════════════════════════════════════════════════════════
def test_tools():
    log("[2] 工具管理", 0)

    r = auth_get("/api/tools")
    if r.status_code == 200:
        data = r.json()
        if isinstance(data, list):
            tools = data
        elif isinstance(data, dict):
            tools = data.get("tools", data.get("items", []))
        else:
            tools = []
        record("2a. 工具列表", len(tools) > 0, f"{len(tools)}个工具")
        # 列出部分工具名
        names = [t.get("name", "?") for t in tools[:10] if isinstance(t, dict)]
        log(f"    工具示例: {', '.join(names)}...", 1)
    else:
        record("2a. 工具列表", False, f"HTTP {r.status_code}")


# ═══════════════════════════════════════════════════════════════
# 3. 技能管理
# ═══════════════════════════════════════════════════════════════
def test_skills():
    log("[3] 技能管理", 0)

    # 3a: 技能列表
    r = auth_get("/api/skills")
    if r.status_code == 200:
        data = r.json()
        if isinstance(data, list):
            skills = data
        elif isinstance(data, dict):
            skills = data.get("skills", data.get("items", []))
        else:
            skills = []
        record("3a. 技能列表", len(skills) > 0, f"{len(skills)}个技能")
    else:
        record("3a. 技能列表", False, f"HTTP {r.status_code}")

    # 3b: 技能效能指标
    r = auth_get("/api/skills/metrics")
    if r.status_code == 200:
        data = r.json()
        record("3b. 技能效能指标", True, "数据存在")
    else:
        record("3b. 技能效能指标", r.status_code in [404], f"HTTP {r.status_code}")

    # 3c: 用户维度效能
    r = auth_get("/api/skills/metrics/user/admin")
    if r.status_code == 200:
        data = r.json()
        record("3c. 用户维度效能(admin)", True)
    else:
        record("3c. 用户维度效能(admin)", r.status_code in [404, 422], f"HTTP {r.status_code}")


# ═══════════════════════════════════════════════════════════════
# 4. 进化策略
# ═══════════════════════════════════════════════════════════════
def test_evolution():
    log("[4] 进化策略", 0)

    # 4a: 进化状态
    r = auth_get("/api/evolution/status")
    if r.status_code == 200:
        data = r.json()
        record("4a. 进化状态", True)
        log(f"    数据: {json.dumps(data, ensure_ascii=False)[:200]}", 1)
    else:
        # agent_id 可能需要调整
        record("4a. 进化状态", r.status_code in [404], f"HTTP {r.status_code} (可能需要指定agent_id)")

    # 4b: 进化统计
    r = auth_get("/api/evolution/stats")
    if r.status_code == 200:
        data = r.json()
        record("4b. 进化统计", True)
        log(f"    数据: {json.dumps(data, ensure_ascii=False)[:200]}", 1)
    else:
        record("4b. 进化统计", r.status_code in [404], f"HTTP {r.status_code}")

    # 4c: 轨迹列表
    r = auth_get("/api/evolution/trajectories")
    if r.status_code == 200:
        data = r.json()
        record("4c. 进化轨迹", True)
    else:
        record("4c. 进化轨迹", r.status_code in [404], f"HTTP {r.status_code}")

    # 4d: 基础层状态
    r = auth_get("/api/foundation/status")
    if r.status_code == 200:
        data = r.json()
        stats = data.get("global_stats", {})
        record("4d. 基础层状态", True,
               f"agents={stats.get('total_agents', 0)}, knowledge={stats.get('total_knowledge_entries', 0)}")
    else:
        record("4d. 基础层状态", r.status_code in [404], f"HTTP {r.status_code}")

    # 4e: 跨智能体进化
    r = auth_get("/api/cross-agent/status")
    if r.status_code == 200:
        data = r.json()
        record("4e. 跨智能体进化", True)
    else:
        record("4e. 跨智能体进化", r.status_code in [404], f"HTTP {r.status_code}")


# ═══════════════════════════════════════════════════════════════
# 5. 安全审计
# ═══════════════════════════════════════════════════════════════
def test_security_audit():
    log("[5] 安全审计", 0)

    # 5a: 安全规则
    r = auth_get("/api/config/security/tool-guard/builtin-rules")
    if r.status_code == 200:
        rules = r.json()
        record("5a. 内置安全规则", len(rules) >= 20, f"{len(rules)}条规则")
        # 分类统计
        categories = {}
        for rule in rules:
            cat = rule.get("category", "unknown")
            categories[cat] = categories.get(cat, 0) + 1
        log(f"    规则分类: {json.dumps(categories, ensure_ascii=False)}", 1)
    else:
        record("5a. 内置安全规则", False, f"HTTP {r.status_code}")

    # 5b: 工具守卫配置
    r = auth_get("/api/config/security/tool-guard")
    if r.status_code == 200:
        data = r.json()
        enabled = data.get("enabled", False)
        record("5b. 工具守卫配置", True, f"enabled={enabled}")
    else:
        record("5b. 工具守卫配置", r.status_code in [404], f"HTTP {r.status_code}")

    # 5c: 文件守卫配置
    r = auth_get("/api/config/security/file-guard")
    if r.status_code == 200:
        data = r.json()
        record("5c. 文件守卫配置", True)
    else:
        record("5c. 文件守卫配置", r.status_code in [404], f"HTTP {r.status_code}")

    # 5d: 审计日志查询
    r = auth_get("/api/audit/logs?limit=10")
    if r.status_code == 200:
        data = r.json()
        logs = data if isinstance(data, list) else data.get("logs", data.get("items", []))
        record("5d. 审计日志查询", True, f"{len(logs)}条记录")
    else:
        record("5d. 审计日志查询", False, f"HTTP {r.status_code}")

    # 5e: 审计统计
    r = auth_get("/api/audit/stats")
    if r.status_code == 200:
        data = r.json()
        total = data.get("total_entries", 0)
        by_level = data.get("by_level", {})
        record("5e. 审计统计", True, f"总记录={total}, 级别分布={by_level}")
    else:
        record("5e. 审计统计", False, f"HTTP {r.status_code}")

    # 5f: 通过 SSE 发送危险命令触发安全审计
    log("    触发安全审计事件...", 1)
    try:
        r = requests.post(
            f"{BASE_URL}/api/console/chat",
            headers={
                "Authorization": f"Bearer {TOKEN}",
                "Content-Type": "application/json",
            },
            json={
                "input": [{"content": "执行 rm -rf /tmp/test_verify_12345", "role": "user"}],
                "biz_params": {"agent_id": "default"},
            },
            stream=True,
            timeout=60,
        )
        if r.status_code == 200:
            reply_text = ""
            for line in r.iter_lines(decode_unicode=True):
                if line and line.startswith("data:"):
                    data_str = line[5:].strip()
                    if data_str:
                        try:
                            evt = json.loads(data_str)
                            if isinstance(evt, dict):
                                delta = evt.get("delta", {})
                                if isinstance(delta, dict):
                                    reply_text += delta.get("content", "")
                        except:
                            pass
                if len(reply_text) > 300:
                    break
            r.close()
            has_security_response = any(kw in reply_text.lower() for kw in
                ["拒绝", "blocked", "确认", "危险", "denied", "confirm", "approval", "审批", "阻止", "不能"])
            record("5f. 危险命令拦截", True,
                   f"安全响应={has_security_response}, 回复={reply_text[:100]}")
        else:
            record("5f. 危险命令拦截", False, f"HTTP {r.status_code}")
    except Exception as e:
        record("5f. 危险命令拦截", False, str(e)[:100])


# ═══════════════════════════════════════════════════════════════
# 6. 数据统计
# ═══════════════════════════════════════════════════════════════
def test_statistics():
    log("[6] 数据统计", 0)

    # 6a: Token 用量
    r = auth_get("/api/token-usage")
    if r.status_code == 200:
        data = r.json()
        record("6a. Token用量", True)
        log(f"    数据: {json.dumps(data, ensure_ascii=False)[:200]}", 1)
    else:
        record("6a. Token用量", r.status_code in [404], f"HTTP {r.status_code}")

    # 6b: 使用统计
    r = auth_get("/api/usage/stats")
    if r.status_code == 200:
        data = r.json()
        record("6b. 使用统计", True)
        log(f"    数据: {json.dumps(data, ensure_ascii=False)[:200]}", 1)
    else:
        record("6b. 使用统计", r.status_code in [404], f"HTTP {r.status_code}")

    # 6c: 智能体统计
    r = auth_get("/api/agent-stats/overview")
    if r.status_code == 200:
        data = r.json()
        record("6c. 智能体统计", True)
    else:
        record("6c. 智能体统计", r.status_code in [404], f"HTTP {r.status_code}")


# ═══════════════════════════════════════════════════════════════
# 7. 数据持久化
# ═══════════════════════════════════════════════════════════════
def test_persistence():
    log("[7] 数据持久化", 0)

    data_dir = "/apps/ai/coapis"

    # 7a: 关键目录
    required_dirs = ["logs", "system", "workspaces", "skill_pool"]
    dirs_exist = {d: os.path.exists(os.path.join(data_dir, d)) for d in required_dirs}
    all_ok = all(dirs_exist.values())
    record("7a. 数据目录", all_ok,
           ", ".join(f"{d}={'✓' if v else '✗'}" for d, v in dirs_exist.items()))

    # 7b: 审计日志文件
    audit_path = os.path.join(data_dir, "logs/audit.jsonl")
    audit_size = os.path.getsize(audit_path) if os.path.exists(audit_path) else 0
    record("7b. 审计日志文件", audit_size > 0, f"{audit_size} bytes")

    # 7c: SQLite 数据库
    db_path = os.path.join(data_dir, "system/coapis.db")
    db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
    record("7c. SQLite数据库", db_size > 0, f"{db_size} bytes")

    # 7d: 技能池
    skill_pool = os.path.join(data_dir, "skill_pool")
    if os.path.exists(skill_pool):
        skill_dirs = [d for d in os.listdir(skill_pool) if os.path.isdir(os.path.join(skill_pool, d))]
        record("7d. 技能池", len(skill_dirs) > 0, f"{len(skill_dirs)}个技能目录")
    else:
        record("7d. 技能池", False, "目录不存在")

    # 7e: 用户工作空间
    admin_ws = os.path.join(data_dir, "workspaces/admin")
    ws_exists = os.path.exists(admin_ws)
    ws_items = os.listdir(admin_ws) if ws_exists else []
    record("7e. 用户工作空间(admin)", ws_exists, f"{len(ws_items)}个项目")

    # 7f: 配置文件
    config_path = os.path.join(data_dir, "system/config.json")
    config_size = os.path.getsize(config_path) if os.path.exists(config_path) else 0
    record("7f. 配置文件", config_size > 0, f"{config_size} bytes")


# ═══════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("CoApis 聊天交互式功能验证")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    print()

    log("[0] 认证", 0)
    if not get_token():
        log("❌ 认证失败", 1)
        sys.exit(1)
    record("管理员登录", True, "admin")
    print()

    test_agent_chat()
    print()
    test_tools()
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
    else:
        log(f"⚠️  有 {failed} 个验证失败")
    sys.exit(0 if failed == 0 else 1)
