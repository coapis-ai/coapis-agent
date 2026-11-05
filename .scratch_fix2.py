p = "server/coapis/agents/context/reference_collector.py"
lines = open(p, encoding="utf-8").read().split("\n")

START = "# v17 · F4（拍板 D3-A）：脚本/外部工具**产出**的文件走独立一支。"
si = lines.index(START)
ei = next(i for i in range(si, si + 50) if 'name.startswith("mcp__")' in lines[i])
print("delete lines", si + 1, "to", ei + 1)
seg = "\n".join(lines[si : ei + 1])
assert "def is_script_producer_tool" in seg
del lines[si : ei + 2]  # 连带尾部空行
s = "\n".join(lines)
s = s.replace("for key in SCRIPT_CODE_KEYS:", "for key in _SCRIPT_CODE_KEYS:")
open(p, "w", encoding="utf-8").write(s)

import re

print("def is_script_producer_tool:", s.count("def is_script_producer_tool"))
print("FILE frozenset defs:", s.count("FILE_SCRIPT_PRODUCER_TOOLS = frozenset"))
print("bare SCRIPT_CODE_KEYS defs:", len(re.findall(r"^SCRIPT_CODE_KEYS =", s, re.M)))
print("_SCRIPT_CODE_KEYS defs:", len(re.findall(r"^_SCRIPT_CODE_KEYS =", s, re.M)))
print("refs _SCRIPT_CODE_KEYS:", s.count("_SCRIPT_CODE_KEYS"))
print("refs bare SCRIPT_CODE_KEYS:", len(re.findall(r"(?<!_)SCRIPT_CODE_KEYS", s)))
