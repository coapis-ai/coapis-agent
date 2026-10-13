# -*- coding: utf-8 -*-
"""R3 消费面 API 端到端探针（打真实 dev 服务）。

链路：登录 → 上传(带 session_id) → 建会话 → attach-chat 补归属 →
按 chat_id 过滤资源契约 → 校验 total/尾巴计数/无引用会话返回空。

用法: python tests/probe_r3_api.py [base_url]
"""

import sys
import uuid

import requests

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:4308"
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not cond else ""))


def main():
    r = requests.post(f"{BASE}/api/auth/login", json={"username": "admin", "password": "admin123"})
    tok = (r.json().get("access_token") or r.json().get("token") or "")
    if not tok:
        print("登录失败:", r.text[:200])
        return 1
    H = {"Authorization": f"Bearer {tok}"}

    sid = f"probe_{uuid.uuid4().hex[:8]}"
    fname = f"r3_probe_{uuid.uuid4().hex[:6]}.md"
    up = requests.post(
        f"{BASE}/api/myfiles/upload",
        headers=H,
        files={"file": (fname, "R3 消费面探针内容", "text/markdown")},
        data={"path": "/", "category": "files", "session_id": sid},
    )
    check("上传成功", up.status_code == 200, up.text[:160])

    # 建会话（chat_id 在首条消息前不存在，所以先上传后补归属）
    cr = requests.post(
        f"{BASE}/api/chats",
        headers={**H, "X-Agent-Id": "user:admin"},
        json={"agent_id": "user:admin", "name": "R3探针会话"},
    )
    j = cr.json() if cr.status_code < 500 else {}
    chat_id = str(j.get("id") or j.get("chat_id") or "")
    check("建会话拿到 chat_id", bool(chat_id), cr.text[:160])
    if not chat_id:
        return 1

    at = requests.post(
        f"{BASE}/api/myfiles/records/attach-chat",
        headers=H,
        json={"session_id": sid, "chat_id": chat_id},
    )
    check("补写会话归属成功", at.status_code == 200 and at.json().get("updated", 0) >= 1, at.text[:160])

    # 1) 按 chat_id 过滤 —— 只应看到本会话引用过的资源
    f1 = requests.get(f"{BASE}/api/myfiles/resources?chat_id={chat_id}&limit=100", headers=H)
    j1 = f1.json()
    paths = [i.get("path") for i in j1.get("items", [])]
    hit = any(fname in str(p) for p in paths)
    check("chat_id 过滤命中本会话文件", hit, str(paths)[:200])
    check("资源行带引用者计数与状态", all("ref_count" in i and "status" in i for i in j1.get("items", [])),
          str(j1.get("items", [])[:1]))

    # 2) 无引用的会话必须返回空（不能全量兜底）
    f2 = requests.get(f"{BASE}/api/myfiles/resources?chat_id=zzz-none&limit=100", headers=H)
    check("无引用会话返回空清单", f2.json().get("items") == [] and f2.json().get("total") == 0,
          str(f2.json())[:200])

    # 3) total 是分页前总数 —— 前端尾巴行靠它，缺了被截断的记录会静默消失
    f3 = requests.get(f"{BASE}/api/myfiles/resources?limit=1", headers=H)
    j3 = f3.json()
    check("limit=1 只返回 1 行", len(j3.get("items", [])) == 1, str(len(j3.get("items", []))))
    check("total 为分页前总数（>1）", int(j3.get("total", 0)) > 1, str(j3.get("total")))

    # 4) 全量清单与 chat 过滤的总数一致性（同一过滤集）
    f4 = requests.get(f"{BASE}/api/myfiles/resources?limit=200", headers=H)
    check("全量 total 不小于本会话过滤 total", int(f4.json().get("total", 0)) >= int(j1.get("total", 0)),
          f"all={f4.json().get('total')} chat={j1.get('total')}")

    failed = [x for x in RESULTS if not x[1]]
    print("=" * 60)
    print(f"PASS {len(RESULTS) - len(failed)}/{len(RESULTS)}")
    for n, _, d in failed:
        print(f"  ❌ {n}: {d}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
