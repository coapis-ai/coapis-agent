"""Container-side verification that B1-B7 are live (not just in the source tree)."""
import re
import sys

ROOT = "/app/coapis"

CHECKS = [
    ("B1 browser 兼容层", f"{ROOT}/agents/tools/browser_control.py",
     [r"_legacy_path", r"paths_json: str = \"\""]),
    ("B2 模块级 executor", f"{ROOT}/agents/tools/browser_control.py",
     [r"^def _get_executor", r"^_executor:"]),
    ("B3 压缩 map-reduce", f"{ROOT}/agents/context/context_budget.py",
     [r"async def _compact_map_reduce", r"if self\.map_reduce", r"def _chunk_rows|def _split_rows|chunks"]),
    ("B3 禁止整块丢弃", f"{ROOT}/agents/context/context_budget.py",
     [r"skeleton|骨架"]),
    ("B4 抽取分片+退避", f"{ROOT}/evolution/experience_extractor.py",
     [r"shard|chunk|分片", r"backoff|退避|retry"]),
    ("B5 强制分页", f"{ROOT}/agents/tools/doc_reader.py",
     [r"_PAGINATE_SIZE_BYTES", r"mode == \"index\", \"head\"|index\+head"]),
    ("B5 文档组预激活", f"{ROOT}/agents/tools/groups.py",
     [r"\"doc_reader\"", r"mode=index"]),
    ("B6 计划骨架注入", f"{ROOT}/agents/react_agent.py",
     [r"_maybe_arm_plan|Plan skeleton armed"]),
    ("B7 截断升级", f"{ROOT}/agents/utils/tool_message_utils.py",
     [r"head.*tail|中段|middle"]),
]

ok = 0
for label, path, pats in CHECKS:
    try:
        src = open(path, encoding="utf-8").read()
    except OSError as exc:
        print(f"  ✗ {label:22s} 读不到 {path}: {exc}")
        continue
    hits = [p for p in pats if re.search(p, src, re.M)]
    good = len(hits) == len(pats)
    ok += good
    print(f"  {'✓' if good else '✗'} {label:22s} {len(hits)}/{len(pats)}  "
          f"{'缺: ' + str([p for p in pats if p not in hits]) if not good else ''}")

print(f"\n容器内落地 {ok}/{len(CHECKS)}")
