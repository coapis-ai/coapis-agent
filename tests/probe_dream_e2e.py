# -*- coding: utf-8 -*-
"""E2E probe: dream pipeline (F1/F2) + deliverables API (F3/F4) on live dev.

Run INSIDE the dev server container:
    cd docker/dev && docker compose exec server python /app/tests/probe_dream_e2e.py

Creates a throwaway user ``e2emem``, exercises the full path, asserts,
then cleans up every trace (DB rows, workspace dir, uploaded file).
Exit code 0 = all green.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import sys
import time
import uuid
import urllib.error
import urllib.request

sys.path.insert(0, "/app")
os.environ.setdefault("AGENTSCOPE_PLATFORM", "local")
try:
    import agentscope_runtime  # noqa: F401
except ImportError:
    import types
    _m = types.ModuleType("agentscope_runtime")
    _m.engine = types.SimpleNamespace(AppBuilder=object)
    sys.modules["agentscope_runtime"] = _m

from sqlalchemy import delete as sa_delete
from sqlalchemy import func
from sqlalchemy import select

USER = "e2emem"
PWD = "e2emem-pass-123"
SALT = "e2emem-salt"
BASE = "http://127.0.0.1:8000"

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        PASS.append(name)
        print(f"  PASS  {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL  {name}  {detail}")


def http(method: str, path: str, token: str | None = None,
         body: dict | None = None, raw: bytes | None = None,
         ctype: str = "application/json") -> tuple[int, dict]:
    url = BASE + path
    data = None
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = ctype
    if raw is not None:
        data = raw
        headers["Content-Type"] = ctype
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode() or "{}")
            return resp.status, payload
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode() or "{}")
        except Exception:
            payload = {}
        return e.code, payload


def main() -> int:
    from coapis.constant import DATA_DIR, WORKSPACES_DIR
    from coapis.foundation.db.engine import init_engine, get_session_factory
    from coapis.foundation.db_settings import resolve_db_path
    from coapis.foundation.repository_factory import RepositoryFactory
    from coapis.foundation.db.models.files import FileRecord
    from coapis.foundation.db.models.memory import Memory
    from coapis.foundation.db.models.memory_timeline import MemoryTimeline
    from coapis.foundation.db.models.user import User

    db_path = f"sqlite:///{resolve_db_path()}"
    print(f"== bootstrapping against {db_path}")
    init_engine(db_path)
    RepositoryFactory.initialize(
        edition=os.getenv("COAPIS_EDITION", "community"), data_dir=DATA_DIR)
    sf = get_session_factory()

    # ── setup: throwaway user (wipe stale traces first, idempotent) ────
    now = time.time()
    ph = hashlib.sha256((SALT + PWD).encode()).hexdigest()
    uid = str(uuid.uuid4())
    with sf() as s:
        s.execute(sa_delete(FileRecord).where(FileRecord.user_id == USER))
        s.execute(sa_delete(MemoryTimeline).where(MemoryTimeline.user_id == USER))
        s.execute(sa_delete(Memory).where(Memory.user_id == USER))
        s.execute(sa_delete(User).where(User.username == USER))
        s.commit()
    stale_ws = WORKSPACES_DIR / USER
    if stale_ws.exists():
        shutil.rmtree(stale_ws, ignore_errors=True)
    with sf() as s:
        s.add(User(id=uid, username=USER, password_hash=ph, salt=SALT,
                   display_name="E2EMem Probe", role="user", is_active=1,
                   created_at=now, updated_at=now))
        s.commit()
    print(f"== user {USER} created ({uid})")

    # ── PART A: deliverables API over HTTP ──────────────────────────────
    print("\n== PART A: deliverables API ==")
    code, res = http("POST", "/api/auth/login",
                     body={"username": USER, "password": PWD, "expires_in": 3600})
    # NOTE: files router prefix is /api/myfiles
    check("A1 login", code == 200 and res.get("token"), f"code={code} res={res}")
    token = res.get("token", "")

    # multipart upload
    boundary = "----probeboundary42"
    fname = "e2e_probe_report.txt"
    mp = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{fname}"\r\n'
        f"Content-Type: text/plain\r\n\r\n"
        f"E2E probe artifact line\n"
        f"\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="path"\r\n\r\n/\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="category"\r\n\r\nfiles\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="overwrite"\r\n\r\nfalse\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="relative_path"\r\n\r\n\r\n'
        f"--{boundary}--\r\n"
    ).encode()
    code, res = http("POST", "/api/myfiles/upload", token=token, raw=mp,
                     ctype=f"multipart/form-data; boundary={boundary}")
    check("A2 upload", code == 200, f"code={code} res={res}")

    code, res = http("GET", "/api/myfiles/deliverables", token=token)
    items = res.get("items", [])
    check("A3 deliverables lists file", code == 200 and res.get("total") == 1
          and any(i.get("title") == fname for i in items),
          f"code={code} res={res}")

    rec_code, rec = http("GET", "/api/myfiles/records", token=token)
    rows = rec.get("items", [])
    hit = next((r for r in rows if r.get("file_path") in (f"/{fname}", fname)),
               None)
    fid = hit.get("id") if hit else None
    check("A4 records row exposes id", rec_code == 200 and fid is not None,
          f"code={rec_code} res={rec}")

    if fid is not None:
        code, res = http("PATCH", f"/api/myfiles/records/{fid}/status", token=token,
                         body={"status": "archived"})
        check("A5 patch status->archived", code == 200 and res.get("success"),
              f"code={code} res={res}")
        code, res = http("GET", "/api/myfiles/deliverables?status=archived", token=token)
        check("A6 deliverables filter archived", code == 200
              and any(i.get("status") == "archived" for i in res.get("items", [])),
              f"code={code} res={res}")
        code, res = http("POST", f"/api/myfiles/records/{fid}/archive", token=token)
        check("A7 archive endpoint", code == 200 and res.get("success"),
              f"code={code} res={res}")

    code, res = http("DELETE", f"/api/myfiles/delete?path=/{fname}&category=files",
                     token=token)
    check("A8 delete file", code == 200, f"code={code} res={res}")

    # ── PART B: dream pipeline in-process ───────────────────────────────
    print("\n== PART B: dream pipeline ==")
    from types import SimpleNamespace
    from coapis.agents.memory.reme_light_memory_manager import ReMeLightMemoryManager
    from coapis.app.crons.manager import CronManager

    ws = WORKSPACES_DIR / USER
    sess_dir = ws / "sessions"
    sess_dir.mkdir(parents=True, exist_ok=True)
    transcript = {
        "agent": {"memory": {"content": [[
            {"role": "user", "content": "我们决定采用方案B来做集成。"},
            {"role": "assistant", "content": "好的。另外我建议以后都用中文汇报。"},
            {"role": "user", "content": "计划月底前交付第一版。"},
        ]]}},
    }
    (sess_dir / "probe_sess.json").write_text(
        json.dumps(transcript, ensure_ascii=False), encoding="utf-8")

    # pre-seed an ancient timeline row to prove 90-day pruning
    old_ts = now - 120 * 86400
    with sf() as s:
        s.add(MemoryTimeline(
            user_id=USER, session_id="ancient-session", signal_type="goal",
            content="远古目标，应被90天保留期剪枝", importance=0.9,
            dedup_key=f"e2e-ancient-{uuid.uuid4()}",
            created_at=old_ts, updated_at=old_ts,
        ))
        s.commit()

    mm = ReMeLightMemoryManager(
        working_dir=str(ws), agent_id=f"user:{USER}", username=USER)
    runner = SimpleNamespace(memory_backend=mm, memory_manager=None)
    cm = CronManager(repo=SimpleNamespace(), runner=runner,
                     channel_manager=SimpleNamespace(),
                     agent_id=f"user:{USER}", owner_user_id=USER)

    day = time.strftime("%Y-%m-%d")
    t0 = time.monotonic()
    asyncio.run(cm._dream_callback())
    print(f"  (first dream callback took {int((time.monotonic()-t0)*1000)} ms)")

    with sf() as s:
        outcome = s.scalar(select(Memory).where(
            Memory.user_id == USER, Memory.title == f"dream:{day}").limit(1))
        oc_status = ""
        if outcome is not None:
            m = re.match(r"status=(\w+)", outcome.content or "")
            oc_status = m.group(1) if m else ""
        check("B1 outcome row recorded (status in content)",
              outcome is not None and outcome.scope == "agent"
              and oc_status in ("skipped", "success", "partial", "failed"),
              f"outcome={outcome.to_dict() if outcome else None}")
        dup_count = int(s.scalar(select(func.count()).select_from(Memory).where(
            Memory.user_id == USER, Memory.title == f"dream:{day}")) or 0)
        check("B1b exactly one outcome row (no user/agent dup)",
              dup_count == 1, f"count={dup_count}")

        sig_rows = s.scalars(select(MemoryTimeline).where(
            MemoryTimeline.user_id == USER,
            MemoryTimeline.source == "dream_signal_scan")).all()
        types_found = {r.signal_type for r in sig_rows}
        check("B2 signals scanned into timeline",
              {"decision", "preference", "goal"} <= types_found,
              f"types={types_found}")

        promo = s.scalars(select(Memory).where(
            Memory.user_id == USER, Memory.source == "timeline")).all()
        promo_cats = {m.category for m in promo}
        check("B3 signals promoted to long-term memories",
              {"decision", "preference", "goal"} <= promo_cats,
              f"cats={promo_cats}")

        stamped = [r for r in sig_rows if r.promoted_at is not None]
        check("B4 promoted rows stamped", len(stamped) == len(sig_rows)
              and len(stamped) > 0,
              f"stamped={len(stamped)}/{len(sig_rows)}")

        ancient = s.scalar(select(MemoryTimeline).where(
            MemoryTimeline.user_id == USER,
            MemoryTimeline.session_id == "ancient-session"))
        check("B5 ancient row pruned by maintenance", ancient is None)

    # idempotency: second run must not duplicate anything
    n_sig_before = len(sig_rows)
    n_promo_before = len(promo)
    asyncio.run(cm._dream_callback())
    with sf() as s:
        n_sig_after = int(s.scalar(select(func.count()).select_from(MemoryTimeline).where(
            MemoryTimeline.user_id == USER,
            MemoryTimeline.source == "dream_signal_scan")) or 0)
        n_mem_after = int(s.scalar(select(func.count()).select_from(Memory).where(
            Memory.user_id == USER, Memory.source == "timeline")) or 0)
        n_outcome_after = int(s.scalar(select(func.count()).select_from(Memory).where(
            Memory.user_id == USER, Memory.title == f"dream:{day}")) or 0)
    check("B6 second run idempotent (signals)", n_sig_after == n_sig_before,
          f"{n_sig_before}->{n_sig_after}")
    check("B6b second run idempotent (memories)", n_mem_after == n_promo_before,
          f"{n_promo_before}->{n_mem_after}")
    check("B6c second run idempotent (outcome)", n_outcome_after == 1,
          f"count={n_outcome_after}")

    # ── cleanup ─────────────────────────────────────────────────────────
    print("\n== cleanup ==")
    with sf() as s:
        s.execute(sa_delete(MemoryTimeline).where(MemoryTimeline.user_id == USER))
        s.execute(sa_delete(Memory).where(Memory.user_id == USER))
        s.execute(sa_delete(FileRecord).where(FileRecord.user_id == USER))
        s.execute(sa_delete(User).where(User.username == USER))
        s.commit()
    if ws.exists():
        shutil.rmtree(ws, ignore_errors=True)
    with sf() as s:
        leftovers = (
            int(s.scalar(select(func.count()).select_from(Memory).where(
                Memory.user_id == USER)) or 0)
            + int(s.scalar(select(func.count()).select_from(MemoryTimeline).where(
                MemoryTimeline.user_id == USER)) or 0)
            + int(s.scalar(select(func.count()).select_from(FileRecord).where(
                FileRecord.user_id == USER)) or 0)
            + int(s.scalar(select(func.count()).select_from(User).where(
                User.username == USER)) or 0)
        )
    check("C1 all traces removed", leftovers == 0 and not ws.exists(),
          f"leftovers={leftovers} ws_exists={ws.exists()}")

    print(f"\n== RESULT: {len(PASS)} passed, {len(FAIL)} failed ==")
    if FAIL:
        print("FAILED CHECKS:", FAIL)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
