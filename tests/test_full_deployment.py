"""全面部署验证测试 - 智能体、工具、技能、进化、安全、审计、统计

两种用法：
  1. pytest：``pytest tests/test_full_deployment.py``（每个 test_* 函数用 assert）
  2. 独立脚本：``python3 tests/test_full_deployment.py``（跑全部并打印汇总）

目标环境用 env 指定（默认 dev：nginx=4300 / server=4308）：
  COAPIS_TEST_BASE_URL / COAPIS_TEST_SERVER_URL
  COAPIS_TEST_NGINX_CONTAINER / COAPIS_TEST_DATA_DIR
"""
import requests
import json
import time
import sys
import os
import subprocess
from datetime import datetime

BASE_URL = os.environ.get("COAPIS_TEST_BASE_URL", "http://localhost:4300")
#: 服务端直连（绕过 nginx）；dev 拓扑：nginx=4300, server=4308
SERVER_URL = os.environ.get("COAPIS_TEST_SERVER_URL", "http://localhost:4308")
#: nginx 容器名（容器间通信验证用）；dev 为 coapis-nginx-dev
NGINX_CONTAINER = os.environ.get("COAPIS_TEST_NGINX_CONTAINER", "coapis-nginx-dev")
#: 数据目录（持久化验证用）
# 默认对齐 dev：BASE_URL/SERVER_URL/NGINX_CONTAINER 都是 dev，数据目录也必须是
# dev 挂载卷 /apps/ai/coapis-dev（compose 里 /apps/ai/coapis-dev:/apps/ai/coapis）。
# 打生产时显式传 COAPIS_TEST_DATA_DIR=/apps/ai/coapis。
DATA_DIR = os.environ.get("COAPIS_TEST_DATA_DIR", "/apps/ai/coapis-dev")
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
    except Exception:
        pass
    return None

AUTH_TOKEN = get_auth_token()
HEADERS = {"Authorization": f"Bearer {AUTH_TOKEN}"} if AUTH_TOKEN else {}

def run_check(name, fn):
    """脚本模式下的运行器：执行 fn 并记录 PASS/FAIL/ERROR。

    刻意不叫 ``test`` —— pytest 会把名为 test 的函数当测试收集（缺参数即报错）。
    """
    try:
        outcome = fn()
        # 断言式测试返回 None（断言失败会抛异常，落到下面的 except），
        # 只有显式返回 False 才算 FAIL。
        ok = outcome is None or bool(outcome)
        status = "PASS" if ok else "FAIL"
        RESULTS.append((name, status, ""))
        print(f"  {'✅' if ok else '❌'} {name}")
        return ok
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
    assert r.status_code == 200, f"health got {r.status_code}"

def test_docs():
    r = requests.get(f"{BASE_URL}/docs", timeout=10)
    # docs 可能被禁用 (COAPIS_OPENAPI_DOCS=false)
    assert r.status_code in [200, 404], f"docs got {r.status_code}"

# ═══════════════════════════════════════════════════════════════
# 2. 智能体管理
# ═══════════════════════════════════════════════════════════════
def test_agents_list():
    r = requests.get(f"{BASE_URL}/api/agents", headers=HEADERS, timeout=10)
    data = r.json()
    assert r.status_code == 200 and isinstance(data, (list, dict)), f"agents got {r.status_code}"

def test_tools_list():
    r = requests.get(f"{BASE_URL}/api/tools", headers=HEADERS, timeout=10)
    data = r.json()
    assert r.status_code == 200 and isinstance(data, (list, dict)), f"tools got {r.status_code}"

# ═══════════════════════════════════════════════════════════════
# 3. 技能管理
# ═══════════════════════════════════════════════════════════════
def test_skills_list():
    r = requests.get(f"{BASE_URL}/api/skills", headers=HEADERS, timeout=10)
    data = r.json()
    assert r.status_code == 200 and isinstance(data, (list, dict)), f"skills got {r.status_code}"

def test_skills_metrics():
    r = requests.get(f"{BASE_URL}/api/skills/metrics", headers=HEADERS, timeout=10)
    assert r.status_code == 200, f"skills/metrics got {r.status_code}"

# ═══════════════════════════════════════════════════════════════
# 4. 进化策略
# ═══════════════════════════════════════════════════════════════
def test_evolution_stats():
    r = requests.get(f"{BASE_URL}/api/evolution/stats", headers=HEADERS, timeout=10)
    assert r.status_code in [200, 404], f"evolution/stats got {r.status_code}"

def test_skill_metrics_user():
    r = requests.get(f"{BASE_URL}/api/skills/metrics/user/test-user", headers=HEADERS, timeout=10)
    assert r.status_code in [200, 404, 422], f"skills/metrics/user got {r.status_code}"

# ═══════════════════════════════════════════════════════════════
# 5. 安全模块
# ═══════════════════════════════════════════════════════════════
def test_security_rules():
    # 安全规则端点路径为 /api/config/security/tool-guard/builtin-rules
    r = requests.get(f"{BASE_URL}/api/config/security/tool-guard/builtin-rules", headers=HEADERS, timeout=10)
    data = r.json() if r.status_code == 200 else []
    rules_count = len(data) if isinstance(data, list) else 0
    assert r.status_code == 200 and rules_count >= 20, f"builtin rules count={rules_count}"

def test_security_config():
    r = requests.get(f"{BASE_URL}/api/config/security/tool-guard", headers=HEADERS, timeout=10)
    assert r.status_code in [200, 404], f"tool-guard config got {r.status_code}"

# ═══════════════════════════════════════════════════════════════
# 6. 审计日志
# ═══════════════════════════════════════════════════════════════
def test_audit_logs():
    r = requests.get(f"{BASE_URL}/api/audit/logs", headers=HEADERS, timeout=10)
    assert r.status_code == 200, f"audit/logs got {r.status_code}"

def test_audit_stats():
    r = requests.get(f"{BASE_URL}/api/audit/stats", headers=HEADERS, timeout=10)
    assert r.status_code == 200, f"audit/stats got {r.status_code}"

# ═══════════════════════════════════════════════════════════════
# 7. 数据统计
# ═══════════════════════════════════════════════════════════════
def test_statistics():
    r = requests.get(f"{BASE_URL}/api/statistics", headers=HEADERS, timeout=10)
    assert r.status_code in [200, 404], f"statistics got {r.status_code}"

def test_memory_stats():
    r = requests.get(f"{BASE_URL}/api/memory/stats", headers=HEADERS, timeout=10)
    assert r.status_code in [200, 404], f"memory/stats got {r.status_code}"

# ═══════════════════════════════════════════════════════════════
# 8. 数据持久化验证
# ═══════════════════════════════════════════════════════════════
def test_data_persistence():
    # 验证关键数据目录存在
    dirs_to_check = ["logs", "system", "workspaces"]
    missing = [d for d in dirs_to_check if not os.path.exists(os.path.join(DATA_DIR, d))]
    assert not missing, f"缺失目录: {missing}"
    # 审计日志：权威位置 = WORKING_DIR/audit_log/audit.jsonl
    # （constant.py:138 AUDIT_LOG_DIR，_app.py:409 audit_log_path）
    audit_log = os.path.join(DATA_DIR, "audit_log/audit.jsonl")
    assert os.path.exists(audit_log), f"审计日志不存在: {audit_log}"

# ═══════════════════════════════════════════════════════════════
# 9. 容器间通信验证
# ═══════════════════════════════════════════════════════════════
def test_container_communication():
    result = subprocess.run(
        ["docker", "exec", NGINX_CONTAINER, "wget", "-q", "-O-",
         "http://server:8000/api/health"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, f"nginx->server 不通: {result.stderr[:120]}"

# ═══════════════════════════════════════════════════════════════
# 10. 端口映射验证
# ═══════════════════════════════════════════════════════════════
def test_port_mapping_server():
    r = requests.get(f"{SERVER_URL}/api/health", timeout=10)
    assert r.status_code == 200, f"server:{SERVER_URL} got {r.status_code}"

def test_port_mapping_nginx():
    r = requests.get(f"{BASE_URL}/", timeout=10)
    assert r.status_code in [200, 301, 302], f"nginx:{BASE_URL} got {r.status_code}"

# ═══════════════════════════════════════════════════════════════
# 运行所有测试（脚本模式）
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("CoApis 全面部署验证测试")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"目标: BASE={BASE_URL} SERVER={SERVER_URL} NGINX_CONTAINER={NGINX_CONTAINER} DATA_DIR={DATA_DIR}")
    print("=" * 60)
    print()

    print("[1] 基础健康检查")
    run_check("健康检查 API", test_health)
    run_check("API 文档", test_docs)
    print()

    print("[2] 智能体管理")
    run_check("智能体列表", test_agents_list)
    run_check("工具列表", test_tools_list)
    print()

    print("[3] 技能管理")
    run_check("技能列表", test_skills_list)
    run_check("技能效能指标", test_skills_metrics)
    print()

    print("[4] 进化策略")
    run_check("进化统计", test_evolution_stats)
    run_check("用户维度技能效能", test_skill_metrics_user)
    print()

    print("[5] 安全模块")
    run_check("安全规则 (29条内置)", test_security_rules)
    run_check("安全配置", test_security_config)
    print()

    print("[6] 审计日志")
    run_check("审计日志查询", test_audit_logs)
    run_check("审计统计", test_audit_stats)
    print()

    print("[7] 数据统计")
    run_check("统计信息", test_statistics)
    run_check("记忆统计", test_memory_stats)
    print()

    print("[8] 数据持久化")
    run_check("数据目录完整性", test_data_persistence)
    print()

    print("[9] 网络连通性")
    run_check("容器间通信 (nginx->server)", test_container_communication)
    run_check(f"端口映射 (server->{SERVER_URL})", test_port_mapping_server)
    run_check(f"端口映射 (nginx->{BASE_URL})", test_port_mapping_nginx)
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
