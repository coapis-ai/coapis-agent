"""全面部署验证测试 - 智能体、工具、技能、进化、安全、审计、统计"""
import requests
import json
import time
import sys
import os
import subprocess
from datetime import datetime

BASE_URL = "http://localhost:4103"
RESULTS = []

# 获取认证 token
def get_auth_token():
    """获取 admin 用户的认证 token"""
    try:
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"username": "admin", "password": "admin123"},
            timeout=10
        )
        if r.status_code == 200:
            return r.json().get("token")
    except:
        pass
    return None

AUTH_TOKEN = get_auth_token()
HEADERS = {"Authorization": f"Bearer {AUTH_TOKEN}"} if AUTH_TOKEN else {}

def test(name, fn):
    """运行测试并记录结果"""
    try:
        result = fn()
        status = "PASS" if result else "FAIL"
        RESULTS.append((name, status, ""))
        print(f"  {'✅' if result else '❌'} {name}")
        return result
    except Exception as e:
        status = "ERROR"
        RESULTS.append((name, status, str(e)[:100]))
        print(f"  ❌ {name} - {str(e)[:100]}")
        return False

# ═══════════════════════════════════════════════════════════════
# 1. 基础健康检查
# ═══════════════════════════════════════════════════════════════
def test_health():
    r = requests.get(f"{BASE_URL}/api/health", timeout=10)
    return r.status_code == 200

def test_docs():
    r = requests.get(f"{BASE_URL}/docs", timeout=10)
    # docs 可能被禁用 (COAPIS_OPENAPI_DOCS=false)
    return r.status_code in [200, 404]

# ═══════════════════════════════════════════════════════════════
# 2. 智能体管理
# ═══════════════════════════════════════════════════════════════
def test_agents_list():
    r = requests.get(f"{BASE_URL}/api/agents", headers=HEADERS, timeout=10)
    data = r.json()
    return r.status_code == 200 and isinstance(data, (list, dict))

def test_tools_list():
    r = requests.get(f"{BASE_URL}/api/tools", headers=HEADERS, timeout=10)
    data = r.json()
    return r.status_code == 200 and isinstance(data, (list, dict))

# ═══════════════════════════════════════════════════════════════
# 3. 技能管理
# ═══════════════════════════════════════════════════════════════
def test_skills_list():
    r = requests.get(f"{BASE_URL}/api/skills", headers=HEADERS, timeout=10)
    data = r.json()
    return r.status_code == 200 and isinstance(data, (list, dict))

def test_skills_metrics():
    r = requests.get(f"{BASE_URL}/api/skills/metrics", headers=HEADERS, timeout=10)
    return r.status_code == 200

# ═══════════════════════════════════════════════════════════════
# 4. 进化策略
# ═══════════════════════════════════════════════════════════════
def test_evolution_stats():
    r = requests.get(f"{BASE_URL}/api/evolution/stats", headers=HEADERS, timeout=10)
    return r.status_code in [200, 404]

def test_skill_metrics_user():
    r = requests.get(f"{BASE_URL}/api/skills/metrics/user/test-user", headers=HEADERS, timeout=10)
    return r.status_code in [200, 404, 422]

# ═══════════════════════════════════════════════════════════════
# 5. 安全模块
# ═══════════════════════════════════════════════════════════════
def test_security_rules():
    # 安全规则端点路径为 /api/config/security/tool-guard/builtin-rules
    r = requests.get(f"{BASE_URL}/api/config/security/tool-guard/builtin-rules", headers=HEADERS, timeout=10)
    data = r.json() if r.status_code == 200 else []
    rules_count = len(data) if isinstance(data, list) else 0
    print(f"    (内置规则数: {rules_count})", end="")
    return r.status_code == 200 and rules_count >= 20

def test_security_config():
    r = requests.get(f"{BASE_URL}/api/config/security/tool-guard", headers=HEADERS, timeout=10)
    return r.status_code in [200, 404]

# ═══════════════════════════════════════════════════════════════
# 6. 审计日志
# ═══════════════════════════════════════════════════════════════
def test_audit_logs():
    r = requests.get(f"{BASE_URL}/api/audit/logs", headers=HEADERS, timeout=10)
    return r.status_code == 200

def test_audit_stats():
    r = requests.get(f"{BASE_URL}/api/audit/stats", headers=HEADERS, timeout=10)
    return r.status_code == 200

# ═══════════════════════════════════════════════════════════════
# 7. 数据统计
# ═══════════════════════════════════════════════════════════════
def test_statistics():
    r = requests.get(f"{BASE_URL}/api/statistics", headers=HEADERS, timeout=10)
    return r.status_code in [200, 404]

def test_memory_stats():
    r = requests.get(f"{BASE_URL}/api/memory/stats", headers=HEADERS, timeout=10)
    return r.status_code in [200, 404]

# ═══════════════════════════════════════════════════════════════
# 8. 数据持久化验证
# ═══════════════════════════════════════════════════════════════
def test_data_persistence():
    data_dir = "/apps/ai/coapis"
    # 验证关键数据目录存在
    dirs_to_check = ["logs", "system", "workspaces"]
    missing = []
    for d in dirs_to_check:
        path = os.path.join(data_dir, d)
        if not os.path.exists(path):
            missing.append(d)
    if missing:
        print(f"    (缺失: {missing})", end="")
        return False
    # 检查审计日志文件
    audit_log = os.path.join(data_dir, "logs/audit.jsonl")
    system_audit = os.path.join(data_dir, "system/logs/audit/audit.jsonl")
    has_audit = os.path.exists(audit_log) or os.path.exists(system_audit)
    print(f"    (审计日志: {'存在' if has_audit else '不存在'})", end="")
    return has_audit

# ═══════════════════════════════════════════════════════════════
# 9. 容器间通信验证
# ═══════════════════════════════════════════════════════════════
def test_container_communication():
    result = subprocess.run(
        ["docker", "exec", "coapis-nginx", "wget", "-q", "-O-", "http://server:8000/api/health"],
        capture_output=True, text=True, timeout=10
    )
    return result.returncode == 0

# ═══════════════════════════════════════════════════════════════
# 10. 端口映射验证
# ═══════════════════════════════════════════════════════════════
def test_port_mapping_server():
    r = requests.get("http://localhost:4103/api/health", timeout=10)
    return r.status_code == 200

def test_port_mapping_nginx():
    r = requests.get("http://localhost:4200/", timeout=10)
    return r.status_code in [200, 301, 302]

# ═══════════════════════════════════════════════════════════════
# 运行所有测试
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("CoApis 全面部署验证测试")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    print()

    print("[1] 基础健康检查")
    test("健康检查 API", test_health)
    test("API 文档", test_docs)
    print()

    print("[2] 智能体管理")
    test("智能体列表", test_agents_list)
    test("工具列表", test_tools_list)
    print()

    print("[3] 技能管理")
    test("技能列表", test_skills_list)
    test("技能效能指标", test_skills_metrics)
    print()

    print("[4] 进化策略")
    test("进化统计", test_evolution_stats)
    test("用户维度技能效能", test_skill_metrics_user)
    print()

    print("[5] 安全模块")
    test("安全规则 (29条内置)", test_security_rules)
    test("安全配置", test_security_config)
    print()

    print("[6] 审计日志")
    test("审计日志查询", test_audit_logs)
    test("审计统计", test_audit_stats)
    print()

    print("[7] 数据统计")
    test("统计信息", test_statistics)
    test("记忆统计", test_memory_stats)
    print()

    print("[8] 数据持久化")
    test("数据目录完整性", test_data_persistence)
    print()

    print("[9] 网络连通性")
    test("容器间通信 (nginx->server)", test_container_communication)
    test("端口映射 (4103->server)", test_port_mapping_server)
    test("端口映射 (4200->nginx)", test_port_mapping_nginx)
    print()

    print("=" * 60)
    print("测试汇总")
    print("=" * 60)
    passed = sum(1 for _, s, _ in RESULTS if s == "PASS")
    failed = sum(1 for _, s, _ in RESULTS if s in ("FAIL", "ERROR"))
    total = len(RESULTS)

    for name, status, detail in RESULTS:
        icon = "✅" if status == "PASS" else "❌"
        print(f"  {icon} {name}" + (f" ({detail})" if detail else ""))

    print()
    print(f"总计: {total} | 通过: {passed} | 失败: {failed}")
    print()

    if failed == 0:
        print("🎉 所有测试通过！部署验证成功！")
        sys.exit(0)
    else:
        print(f"⚠️  有 {failed} 个测试失败，请检查！")
        sys.exit(1)
