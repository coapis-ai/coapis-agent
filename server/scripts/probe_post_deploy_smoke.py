"""Post-deploy smoke，按时间戳精确过滤（重启之后才算）。"""
import re
import subprocess
import sys

LOG = "/apps/ai/coapis/coapis.log"
# 日志时间戳是容器时区（UTC），宿主是 Asia/Shanghai(+8)。
# dev 后端重启于 CST 03:26 = UTC 19:26。
SINCE = "2026-10-17 19:26:00"

out = subprocess.run(["bash", "-c", f"tail -c 8000000 {LOG}"], capture_output=True, text=True).stdout

TS = re.compile(r"(2026-\d\d-\d\d \d\d:\d\d:\d\d)")


def ts_of(line):
    m = TS.search(line)
    return m.group(1) if m else None


lines = out.splitlines()
# 时间戳在日志里单调（同一文件追加），取 >= SINCE 的行
kept = [l for l in lines if (t := ts_of(l)) and t >= SINCE]
print(f"重启后日志行 = {len(kept)}  (窗口 {SINCE} 起)")

PATTERNS = {
    "NameError": r"NameError",
    "TypeError": r"TypeError",
    "压缩不可拟合(旧)": r"skipping the call",
    "压缩适配(新)": r"sending the best fit|fitted \d+ -> \d+ chars",
    "抽取超时": r"LLM extraction failed",
    "上下文超限": r"Range of input length|context_length_exceeded",
    "异常栈": r"Traceback \(most recent call last\)",
}
for label, pat in PATTERNS.items():
    hits = [l for l in kept if re.search(pat, l)]
    print(f"  {label:18s} {len(hits):3d}")
    for h in hits[-2:]:
        print("      ", h.strip()[:150])

fixed = [int(m.group(1)) for l in kept if (m := re.search(r"fixed=(\d+)", l))]
if fixed:
    print(f"\nfixed: 最新={fixed[-1]} 最大={max(fixed)} 样本={len(fixed)}")
