"""重启后的 Context budget 读数明细（含 sys/tools/pct/window/src）。"""
import re
import subprocess

LOG = "/apps/ai/coapis/coapis.log"
SINCE = "2026-10-17 19:26:00"  # UTC = CST 03:26 重启

out = subprocess.run(["tail", "-c", "8000000", LOG], capture_output=True, text=True).stdout
TS = re.compile(r"(2026-\d\d-\d\d \d\d:\d\d:\d\d)")
lines = out.splitlines()
kept = [l for l in lines if (t := TS.search(l)) and t.group(1) >= SINCE]

rows = [l for l in kept if "Context budget" in l]
print(f"重启后 Context budget 行数 = {len(rows)}")
for r in rows[-6:]:
    print("  ", r.strip()[:230])

print("\n--- 重启后其他关键行 ---")
for pat, label in [
    (r"window|Window", "窗口"),
    (r"compaction|Compaction", "压缩"),
    (r"equip|group", "工具组"),
    (r"skill", "技能"),
]:
    hits = [l for l in kept if re.search(pat, l)]
    print(f"  {label}: {len(hits)}")
    for h in hits[-3:]:
        print("      ", h.strip()[:190])
