"""通过聊天交互验证所有功能模块"""
import requests
import json
import time
import sys
from datetime import datetime

import os

BASE_URL = os.environ.get("COAPIS_TEST_BASE_URL", "http://localhost:4300")

# ── 为什么用专用测试账号，而不是 admin ──
# 会话按 (channel, sender_id) 跟踪：console channel 用
# ``resolve_session_id(sender_id, meta)``（base.py:293）返回该用户**已跟踪的会话**，
# payload 里的 session_id 被忽略。而 ``sender_id = user_id``（console.py:278），
# user_id 取自 token——所以用 admin 跑时三次请求都落进 admin 的既有会话
# （日志：复用 workspaces/admin/sessions/admin_460ca156…json），智能体看到累积
# 历史后去"梳理用户连续发的多条消息"、复述上一轮任务：对"读取 /etc/hostname"
# 这条它执行的是 execute_shell_command，三条回复长度完全相同（638/767 字符）。
# 用全新账号（无历史会话）后三条各自执行正确工具：
# shell→execute_shell_command、read→read_file、shell2→execute_shell_command。
# 建号（需 admin）：POST /api/admin/users
#   {"username":"verify_probe","password":"Probe#2026",
#    "email":"probe@coapis.local","display_name":"验证探针","role":"user"}
PROBE_USER = os.environ.get("COAPIS_TEST_USER", "verify_probe")
PROBE_PASS = os.environ.get("COAPIS_TEST_PASS", "Probe#2026")


def get_token(username, password):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"username": username, "password": password},
                      timeout=10)
    return r.json().get("token") if r.status_code == 200 else None

TOKEN = get_token(PROBE_USER, PROBE_PASS)
if not TOKEN:
    print(f"❌ 登录失败：测试账号 {PROBE_USER} 不存在。先建号（见文件头注释）。")
    sys.exit(1)
H = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

# 管理端点（技能/进化/安全/审计/Token/智能体统计）需要 admin 权限：
# 探针账号 role=user，用它的 token 打这些端点会 403。所以管理端点单独用 admin token。
ADMIN_TOKEN = get_token("admin", "admin123")
if not ADMIN_TOKEN:
    print("❌ admin 登录失败，管理端点检查会全红。")
AH = {"Authorization": f"Bearer {ADMIN_TOKEN}", "Content-Type": "application/json"}

results = []

def section(title):
    print(f"\n{'='*60}")
    print(f" {title}")
    print(f"{'='*60}")

def check(name, ok, detail=""):
    icon = "✅" if ok else "❌"
    results.append((name, ok))
    print(f"  {icon} {name}" + (f" ({detail})" if detail else ""))


_SESSION_SEQ = 0


def stream_chat(message, timeout=(10, 120), deadline=150, session_id=None):
    """跑一次聊天，返回 (回复文本, 工具名列表)。

    四点必须容错，否则脚本会崩或得出假结果：
    1. nginx 的 ``proxy_read_timeout`` 是 300s，智能体跑满 5 分钟时 SSE 会被
       服务端提前关闭 → requests 抛 ChunkedEncodingError/ReadTimeout。
    2. 工具调用在事件流里的类型是 ``plugin_call``（``status=completed`` 时
       ``content[].data.name`` 才是工具名）；不是 ``tool_use``/``tool``，
       按旧类型解析会恒得到 0 次调用。
    3. **必须加墙钟上限**（``deadline``）。智能体在 ``plugin_call`` 之后流不会
       主动关闭（reasoning/text 持续吐），单块 read timeout 永远不触发，脚本会
       一直挂着——1.3 文件读取就是这么卡死超过 5 分钟的。
    4. **读超时必须 > 模型首字延迟**。实测日志：请求 14:35:35 进入
       ``super().reply``，14:36:43 才出第一批输出——**首字延迟 68s**。原先
       ``(10, 60)`` 短于它，脚本一个字节都收不到就 ConnectionError，于是
       "工具调用=0次"是**假失败**（日志里 tool_call/tool_output 明明执行了）。
       现取 120s 读超时 / 150s 墙钟。
       注意 ``session_id`` 只是尽力隔离：服务端会回落到该用户已有的会话
       （日志：复用 ``workspaces/admin/sessions/admin_460ca156…json``），智能体
       仍会看到历史并"梳理用户连续发的多条消息"，所以判定只看**本次**事件流里
       的 plugin_call，不依赖回复文案。
    """
    global _SESSION_SEQ
    _SESSION_SEQ += 1
    sid = session_id or f"verify_{int(time.time())}_{_SESSION_SEQ}"
    text, tools = [], []
    end = time.time() + deadline
    try:
        r = requests.post(f"{BASE_URL}/api/console/chat", headers=H,
                          json={"message": message,
                                "session_id": sid,
                                # 必须显式传 agent_id：不传时服务端回落
                                # "falling back to user:admin"（console.py:337），
                                # 于是所有请求都落进 admin 的既有会话
                                # （日志 run_key=460ca156…），智能体看到累积历史后
                                # 复述上一轮任务——三条不同指令的回复长度完全一样
                                # （802/806 字符），工具调用恒为 0 次。显式指定后
                                # 三条各自执行正确工具（shell→execute_shell_command、
                                # read→read_file）。
                                "user_id": PROBE_USER,
                                "agent_id": f"user:{PROBE_USER}"},
                          stream=True, timeout=timeout)
        for line in r.iter_lines(decode_unicode=True):
            if time.time() > end:
                print(f"  (达墙钟上限 {deadline}s，主动收流)")
                break
            if not line or not line.startswith("data: "):
                continue
            try:
                d = json.loads(line[6:])
            except Exception:
                continue
            t = d.get("type")
            if t == "text" and d.get("text"):
                text.append(d["text"])
            elif t == "plugin_call" and d.get("status") == "completed":
                for c in (d.get("content") or []):
                    data = (c or {}).get("data") or {}
                    if data.get("name"):
                        tools.append(data["name"])
    except (requests.exceptions.ChunkedEncodingError,
            requests.exceptions.ReadTimeout,
            requests.exceptions.ConnectionError) as exc:
        print(f"  (流被截断: {type(exc).__name__}，按已收到的 {len(''.join(text))} 字符继续)")
    return "".join(text), tools

# ═══════════════════════════════════════════════════════════════
# 1. 智能体聊天交互
# ═══════════════════════════════════════════════════════════════
section("[1] 智能体聊天交互")

# 1.1 基础对话
print("  测试1.1: 基础对话...")
full_reply, _ = stream_chat("你好，请简单介绍一下你能做什么功能")
check("基础对话", len(full_reply) > 20, f"回复长度={len(full_reply)}字符")

# 1.2 工具调用
print("  测试1.2: 工具调用(执行shell命令)...")
full, tools = stream_chat("请执行一条shell命令: echo 'hello from coapis'")
# 必须看到真实工具调用事件；不接受"回复里含某字符串"这类间接旁证（它会让
# 0 次调用的情况也判为通过，等于没在验证工具能力）。
check("工具调用(Shell)", len(tools) > 0, f"工具调用={len(tools)}次 {tools[:3]}")

# 1.3 文件读取
print("  测试1.3: 文件读取工具...")
full, tools = stream_chat("请读取 /etc/hostname 文件的内容")
check("文件读取", "read_file" in tools and len(full) > 10,
      f"工具={tools[:3]} 回复长度={len(full)}字符")

# ═══════════════════════════════════════════════════════════════
# 2. 技能系统
# ═══════════════════════════════════════════════════════════════
section("[2] 技能系统")

# 2.1 技能列表
r = requests.get(f"{BASE_URL}/api/skills", headers=AH, timeout=10)
skills = r.json() if r.status_code == 200 else []
skill_count = len(skills) if isinstance(skills, list) else 0
check("技能列表", skill_count > 0, f"技能数={skill_count}")

# 2.2 技能效能指标
r = requests.get(f"{BASE_URL}/api/skills/metrics", headers=AH, timeout=10)
check("技能效能指标API", r.status_code == 200)

# 2.3 用户维度技能效能 (P0新增)
r = requests.get(f"{BASE_URL}/api/skills/metrics/user/{PROBE_USER}", headers=AH, timeout=10)
check("用户维度技能效能", r.status_code in [200, 404])

# ═══════════════════════════════════════════════════════════════
# 3. 进化策略
# ═══════════════════════════════════════════════════════════════
section("[3] 进化策略")

# 3.1 进化统计
r = requests.get(f"{BASE_URL}/api/evolution/stats", headers=AH, timeout=10)
check("进化统计", r.status_code in [200, 404])

# 3.2 版本管理 (进化链)
r = requests.get(f"{BASE_URL}/api/skills/versions", headers=AH, timeout=10)
check("技能版本管理", r.status_code in [200, 404])

# 3.3 经验提取
r = requests.get(f"{BASE_URL}/api/evolution/experiences", headers=AH, timeout=10)
check("经验提取", r.status_code in [200, 404])

# ═══════════════════════════════════════════════════════════════
# 4. 安全模块
# ═══════════════════════════════════════════════════════════════
section("[4] 安全模块")

# 4.1 内置安全规则
r = requests.get(f"{BASE_URL}/api/config/security/tool-guard/builtin-rules", headers=AH, timeout=10)
rules = r.json() if r.status_code == 200 else []
check("安全规则(YAML)", r.status_code == 200, f"规则数={len(rules)}")

# 4.2 工具守卫配置
r = requests.get(f"{BASE_URL}/api/config/security/tool-guard", headers=AH, timeout=10)
tg = r.json() if r.status_code == 200 else {}
check("工具守卫配置", r.status_code == 200, f"enabled={tg.get('enabled', 'N/A')}")

# 4.3 文件守卫
r = requests.get(f"{BASE_URL}/api/config/security/file-guard", headers=AH, timeout=10)
check("文件守卫", r.status_code in [200, 404])

# 4.4 危险命令拦截
# 不在聊天层验证：实测危险命令走的是**审批门**（``action=confirm``），无人批准时
# 智能体会挂到 300s 审批超时（日志: "Approval for 'Bash' timed out after 300s"），
# 且审批 API 看不到该待批项。所以聊天层既慢又不可判定，靠"回复含某关键词"更是假判定。
# 改在规则层做确定性断言：规则集里必须存在匹配 ``rm -rf`` 的 HIGH 级 confirm 规则。
print("  测试4.4: 危险命令拦截(规则层确定性断言)...")
r = requests.get(f"{BASE_URL}/api/config/security/shell-guard/rules", headers=AH, timeout=10)
rules = r.json() if r.status_code == 200 else []
rf_rules = [x for x in rules
            if x.get("severity") == "HIGH" and x.get("action") == "confirm"
            and any("rm" in p and "rf" in p for p in (x.get("patterns") or []))]
check("危险命令拦截", bool(rf_rules),
      f"规则数={len(rules)}, 命中={rf_rules[0]['id'] if rf_rules else '无'}")

# ═══════════════════════════════════════════════════════════════
# 5. 审计日志
# ═══════════════════════════════════════════════════════════════
section("[5] 审计日志")

# 5.1 审计日志查询
# 字段名以接口实际契约为准：/api/audit/logs 返回 ``entries``（不是 logs/items），
# /api/audit/stats 返回 ``total_entries``（不是 total_events）。读错 key 会让检查
# 恒显示 0 条——状态码 200 掩盖了它，属于"绿色但没真验"的假阴性。
r = requests.get(f"{BASE_URL}/api/audit/logs?limit=5", headers=AH, timeout=10)
audit = r.json() if r.status_code == 200 else {}
logs = audit.get("entries", []) if isinstance(audit, dict) else []
check("审计日志查询", r.status_code == 200 and len(logs) > 0,
      f"记录数={len(logs)}")

# 5.2 审计统计
r = requests.get(f"{BASE_URL}/api/audit/stats", headers=AH, timeout=10)
stats = r.json() if r.status_code == 200 else {}
check("审计统计", r.status_code == 200 and stats.get("total_entries", 0) > 0,
      f"总事件数={stats.get('total_entries', 'N/A')}")

# ═══════════════════════════════════════════════════════════════
# 6. 数据统计
# ═══════════════════════════════════════════════════════════════
section("[6] 数据统计")

# 6.1 / 6.2 已删除：/api/statistics 与 /api/memory/stats 在路由里根本不存在
# （实测 404），原先把 404 也算通过，等于"端点不存在也算绿"的幽灵检查。
# 真实端点只有 /api/token-usage 与 /api/agent-stats，要求 200 且有数据。
r = requests.get(f"{BASE_URL}/api/token-usage", headers=AH, timeout=10)
tu = r.json() if r.status_code == 200 else {}
check("Token用量", r.status_code == 200 and tu.get("total_calls", 0) > 0,
      f"总调用={tu.get('total_calls', 'N/A')}, 总token={tu.get('total_tokens', 'N/A')}")

r = requests.get(f"{BASE_URL}/api/agent-stats", headers=AH, timeout=10)
ag = r.json() if r.status_code == 200 else {}
check("智能体统计", r.status_code == 200 and bool(ag), f"字段数={len(ag)}")

# ═══════════════════════════════════════════════════════════════
# 7. 数据持久化验证
# ═══════════════════════════════════════════════════════════════
section("[7] 数据持久化")

import os
# 数据目录 = 挂载卷（宿主机可见），路径以代码里的权威定义为准：
#   审计日志 = WORKING_DIR/audit_log/audit.jsonl (constant.py:138, _app.py:409)
#   主库     = WORKING_DIR/system/coapis.db
#   技能池   = WORKING_DIR/skill_pool/
#   主日志   = WORKING_DIR/coapis.log
# 默认对齐 dev（BASE_URL 默认 4300 = dev nginx），打生产时显式传 /apps/ai/coapis。
DATA_DIR = os.environ.get("COAPIS_TEST_DATA_DIR", "/apps/ai/coapis-dev")

# 7.1 审计日志文件
audit_dir = os.path.join(DATA_DIR, "audit_log")
audit_file = os.path.join(audit_dir, "audit.jsonl")
has_audit_dir = os.path.isdir(audit_dir)
check("审计日志目录", has_audit_dir, audit_dir)

# 7.2 SQLite数据库
db_file = os.path.join(DATA_DIR, "system/coapis.db")
has_db = os.path.isfile(db_file)
check("SQLite数据库", has_db, db_file)

# 7.3 技能池
skill_dir = os.path.join(DATA_DIR, "skill_pool")
skill_dirs = [d for d in os.listdir(skill_dir) if os.path.isdir(os.path.join(skill_dir, d))] if os.path.isdir(skill_dir) else []
check("技能池目录", len(skill_dirs) > 0, f"技能数={len(skill_dirs)}")

# 7.4 日志文件
log_file = os.path.join(DATA_DIR, "coapis.log")
check("主日志文件", os.path.isfile(log_file), log_file)

# ═══════════════════════════════════════════════════════════════
# 8. 工具列表验证
# ═══════════════════════════════════════════════════════════════
section("[8] 工具与智能体")

r = requests.get(f"{BASE_URL}/api/tools", headers=H, timeout=10)
tools = r.json() if r.status_code == 200 else []
tool_names = [t.get("name", t) for t in tools] if isinstance(tools, list) else []
check("工具列表", len(tools) > 0, f"工具数={len(tools)}")

r = requests.get(f"{BASE_URL}/api/agents", headers=AH, timeout=10)
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
