"""资源契约消费面 E2E 探针（真实聊天链路）。

**真值来源是服务端落盘的会话文件**，不是 SSE。实测：SSE 流里不推 tool_use
事件（只推文本增量），而 ``_persist_chat_messages`` 会把 tool_call/tool_output
写进 ``workspaces/<user>/sessions/*.json``。所以断言读会话文件。

``resolve_session_id`` 在已有跟踪会话时会复用同一个 session（忽略请求里的
session_id），因此探针读"最新的会话文件"，按 tool_use 的入参匹配断言。

验证四件事：
  1. ``resource_search`` 在真实智能体上被模型调用（注册链通）。
  2. 发现模式（scope='' + query=''）列出资源面，结果带 source 标签，
     且工作区里的文档（docx/pdf/图片）也能被看见——只扫文本后缀会让
     智能体在自己的工作区里瞎掉。
  3. 单面检索（scope=file）能命中真实文件。
  4. 非法 scope 记入 errors 不崩；纯对话链路仍正常。

用法：python tests/probe_resource_search.py
"""

import glob
import json
import os
import sys
import time
import uuid

import requests

BASE_URL = os.environ.get("COAPIS_TEST_BASE_URL", "http://localhost:4300")
USER = os.environ.get("COAPIS_TEST_USER", "admin")
SESSIONS_DIR = os.environ.get(
    "COAPIS_TEST_SESSIONS_DIR",
    f"/apps/ai/coapis-dev/workspaces/{USER}/sessions",
)
TOKEN = None
RESULTS: list = []


def check(name: str, cond: bool, detail: str = ""):
    RESULTS.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not cond else ""))


def get_token():
    global TOKEN
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"username": "admin", "password": "admin123"},
        timeout=15,
    )
    if r.status_code != 200:
        raise SystemExit(f"login failed: HTTP {r.status_code} {r.text[:120]}")
    TOKEN = r.json().get("token")


def newest_session_file() -> str:
    files = glob.glob(os.path.join(SESSIONS_DIR, "*.json"))
    return max(files, key=os.path.getmtime) if files else ""


def tool_blocks(path: str) -> list:
    """递归抓 tool_use / tool_result 块。"""
    data = json.load(open(path))
    out: list = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") in ("tool_use", "tool_result"):
                out.append(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    return out


def chat(prompt: str, agent_id: str = "default", timeout: int = 180) -> str:
    """跑一轮真实对话，返回文本回复。"""
    r = requests.post(
        f"{BASE_URL}/api/console/chat",
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
        json={
            "input": [{"content": prompt, "role": "user"}],
            "biz_params": {"agent_id": agent_id},
            "session_id": f"probe_res_{uuid.uuid4().hex[:10]}",
        },
        stream=True,
        timeout=timeout,
    )
    if r.status_code != 200:
        return f"__HTTP_ERROR__ {r.status_code}: {r.text[:120]}"
    text = ""
    for line in r.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data:"):
            continue
        try:
            evt = json.loads(line[5:])
        except json.JSONDecodeError:
            continue
        if evt.get("object") == "content" and evt.get("type") == "text" and evt.get("delta"):
            text += evt.get("text") or ""
        if evt.get("object") == "response" and evt.get("status") == "completed":
            break
    r.close()
    return text


def pair(blocks: list, tool_name: str) -> list:
    """把 tool_use 与对应 tool_result 配对。"""
    results = {b.get("id"): b for b in blocks if b.get("type") == "tool_result"}
    pairs = []
    for b in blocks:
        if b.get("type") == "tool_use" and b.get("name") == tool_name:
            res = results.get(b.get("id"), {})
            payload = ""
            for c in res.get("output") or []:
                if isinstance(c, dict) and c.get("type") == "text":
                    payload += c.get("text") or ""
            pairs.append({"input": b.get("input") or {}, "result": payload})
    return pairs


def main() -> int:
    get_token()

    # 会话文件会复用（resolve_session_id 复用已跟踪 session），所以只断言
    # 本轮新增的 tool 块：先记基线数量，跑完再取增量。
    base_path = newest_session_file()
    baseline = len(pair(tool_blocks(base_path), "resource_search")) if base_path else 0

    # ── 1. 发现模式 ─────────────────────────────────────────────
    chat(
        "只调用一次 resource_search 工具，参数 scope='' 且 query=''（发现模式）。"
        "不要调用其它工具。把工具返回的 sources 计数原样告诉我。",
    )
    # ── 2. 单面检索命中真实文件 ────────────────────────────────
    chat("只调用一次 resource_search，参数 scope='file'、query='报告'。把命中的 ref 列表告诉我。")
    # ── 3. 非法 scope ─────────────────────────────────────────
    chat("只调用一次 resource_search，参数 scope='zzz'、query='x'。把返回的 hint 告诉我。")
    # ── 4. 纯对话 ─────────────────────────────────────────────
    plain = chat("用一句话回答：1+1 等于几？不要调用任何工具。")

    time.sleep(2)
    path = newest_session_file()
    if not path:
        check("会话文件存在", False, SESSIONS_DIR)
        return 1
    all_pairs = pair(tool_blocks(path), "resource_search")
    pairs = all_pairs[baseline:]
    check("模型调用 resource_search", len(pairs) >= 3, f"new pairs={len(pairs)} (baseline {baseline})")

    # 1) 发现模式：入参正确 + 带 source + 含 file 面 + 文档可见
    disc = [p for p in pairs if p["input"].get("scope", "") == "" and p["input"].get("query", "") == ""]
    check("发现模式入参正确", len(disc) >= 1, f"inputs={[p['input'] for p in pairs]}")
    d = disc[0]["result"] if disc else ""
    check("发现结果带 source 标签", '"source"' in d, d[:160])
    check("发现结果含 file 面", '"source": "file"' in d, d[:160])
    check(
        "工作区文档可见（docx/pdf/图片不被文本后缀过滤掉）",
        any(x in d for x in (".docx", ".pdf", ".png", ".jpg")),
        d[:200],
    )

    # 2) file 面检索命中
    fs = [p for p in pairs if p["input"].get("scope") == "file" and p["input"].get("query")]
    check("file 面检索被调用", len(fs) >= 1, f"inputs={[p['input'] for p in pairs]}")
    fr = fs[0]["result"] if fs else ""
    check("file 检索有命中", '"total": 0' not in fr and '"ref"' in fr, fr[:200])

    # 3) 非法 scope 记入 errors
    bad = [p for p in pairs if p["input"].get("scope") == "zzz"]
    check("非法 scope 记入 errors", "errors" in (bad[0]["result"] if bad else ""), fr[:120])

    # 4) 纯对话链路完好
    check("纯对话仍正常", len(plain) > 0 and not plain.startswith("__HTTP_ERROR__"), plain[:80])

    total = len(RESULTS)
    passed = sum(1 for _, p, _ in RESULTS if p)
    print("=" * 60)
    print(f"PASS {passed}/{total}")
    for n, p, d in RESULTS:
        if not p:
            print(f"  FAIL {n}: {d}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
