# -*- coding: utf-8 -*-
"""批次 1 桥接 dev 环境功能探针（真实 DB）。"""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, "/app")

from sqlalchemy import func, select

from coapis.constant import SYSTEM_DIR
from coapis.foundation.repository_factory import RepositoryFactory
RepositoryFactory.initialize(edition="community", data_dir=SYSTEM_DIR)

from coapis.foundation.db.engine import get_session_factory
from coapis.foundation.db.models.memory_timeline import MemoryTimeline

sf = get_session_factory()
with sf() as s:
    rows = s.execute(
        select(MemoryTimeline.user_id, func.count())
        .group_by(MemoryTimeline.user_id)
        .order_by(func.count().desc())
        .limit(3)
    ).all()
print("timeline users:", rows)
assert rows, "no timeline rows"
uid = rows[0][0]

from coapis.foundation.timeline_digest import build_timeline_digest

# 宽窗口（90 天）证明真实数据可渲染；生产注入仍用默认 72h
d = build_timeline_digest(user_id=uid, hours=24 * 90)
print("--- digest ---")
print(d[:400])
print("--- end ---")
ok = bool(d)

from coapis.agents.memory.reme_light_memory_manager import ReMeLightMemoryManager
from coapis.foundation.repository_factory import RepositoryFactory

ws = tempfile.mkdtemp(prefix="memprobe_")
os.makedirs(os.path.join(ws, "memory"), exist_ok=True)
open(os.path.join(ws, "MEMORY.md"), "w").write("# probe\n")
mgr = ReMeLightMemoryManager(working_dir=ws, agent_id="probe", username=uid)
trows = RepositoryFactory.get_memory_timeline_repository().recent(
    user_id=uid, hours=24 * 90, limit=5
)
sample = (trows[0]["content"] or "")[:12] if trows else "部署"
resp = asyncio.new_event_loop().run_until_complete(
    mgr.memory_search(sample, max_results=5)
)
txt = "".join(b.get("text", "") for b in resp.content if isinstance(b, dict))
print("--- search resp ---")
print(txt[:600])
print("--- end ---")
ok = ok and ("记忆台账补充" in txt)
print("PROBE_" + ("OK" if ok else "FAIL"))
sys.exit(0 if ok else 1)
