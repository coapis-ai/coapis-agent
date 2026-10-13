# -*- coding: utf-8 -*-
"""批次 1 桥接 dev 环境功能探针（真实 DB）。

用法：
  容器内（天然指向挂载卷）：``docker exec coapis-server-dev python3 /tmp/probe.py``
  宿主机（需指向挂载卷，否则 coapis.constant 会解析到 /root/.coapis 空库）：
      COAPIS_PROBE_SYSTEM_DIR=/apps/ai/coapis/system python3 tests/probe_mem_bridge_dev.py

线上库无 timeline 数据时（dev 库被重置/新装）探针会自播种一个临时库，
验证桥接逻辑本身，而不是依赖环境里的存量数据 —— 这样它不会因环境空库而恒失败。
"""
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, "/app")

from sqlalchemy import func, select

from coapis.constant import SYSTEM_DIR

# 宿主机上把 SYSTEM_DIR/WORKING_DIR 指向挂载卷（容器内不需要）。
_override = os.environ.get("COAPIS_PROBE_SYSTEM_DIR")
if _override:
    import coapis.constant as _constant
    import coapis.foundation.db_settings as _db_settings
    _sys_dir = Path(os.path.realpath(_override))
    _constant.SYSTEM_DIR = _sys_dir
    _constant.WORKING_DIR = _sys_dir.parent
    _db_settings.SYSTEM_DIR = _sys_dir
    _db_settings.WORKING_DIR = _sys_dir.parent
    SYSTEM_DIR = _sys_dir

from coapis.foundation.repository_factory import RepositoryFactory

RepositoryFactory.initialize(edition="community", data_dir=SYSTEM_DIR)

from coapis.foundation.db.engine import get_session_factory, get_engine, init_engine
from coapis.foundation.db.base import BaseRow
from coapis.foundation.db.models.memory_timeline import MemoryTimeline
from coapis.foundation.memory_timeline import TimelineEntry

sf = get_session_factory()
with sf() as s:
    rows = s.execute(
        select(MemoryTimeline.user_id, func.count())
        .group_by(MemoryTimeline.user_id)
        .order_by(func.count().desc())
        .limit(3)
    ).all()

if rows:
    print("timeline users:", rows)
    uid = rows[0][0]
    print("数据源: 线上库")
else:
    # 线上库为空 → 自播种临时库（不写线上库，避免污染 dev 数据）
    tmp_db = Path(tempfile.mkdtemp(prefix="memprobe_db_")) / "coapis.db"
    init_engine(f"sqlite:///{tmp_db}")
    BaseRow.metadata.create_all(get_engine())
    uid = "probe_user"
    repo = RepositoryFactory.get_memory_timeline_repository()
    now = time.time()
    for i, content in enumerate((
        "**八、项目策划七项核心信息表**（区域范围、期限、目标、任务、子项目、成效、投资估算）",
        "**九、六类常见风险点** 与 **四、四级推进机制**：省级整体部署 → 县域统筹谋划",
    )):
        repo.append(TimelineEntry(
            user_id=uid,
            agent_id="probe",
            session_id="probe_session",
            signal_type="conversation",
            content=f"[记忆台账补充] {content}",
            source="probe_seed",
            importance=0.7,
            created_at=now - i * 60,
        ))
    print(f"数据源: 自播种临时库 {tmp_db}")

from coapis.foundation.timeline_digest import build_timeline_digest

# 宽窗口（90 天）证明真实数据可渲染；生产注入仍用默认 72h
d = build_timeline_digest(user_id=uid, hours=24 * 90)
print("--- digest ---")
print(d[:400])
print("--- end ---")
ok = bool(d)

from coapis.agents.memory.reme_light_memory_manager import ReMeLightMemoryManager

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
