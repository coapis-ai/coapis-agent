"""记忆后端注册表现状：remelight 解析到哪个类，有没有 summarize 入口。"""
import sys

sys.path.insert(0, "/app")

from coapis.agents.memory.base_memory_manager import (  # noqa: E402
    get_memory_manager_backend,
    memory_registry,
)

print("已注册后端:", memory_registry.list_registered())

for name in memory_registry.list_registered() + ["remelight", "file", ""]:
    try:
        cls = get_memory_manager_backend(name)
    except Exception as exc:  # noqa: BLE001
        print(f"  {name!r:12s} -> 解析失败 {type(exc).__name__}: {exc}")
        continue
    print(
        f"  {name!r:12s} -> {cls.__module__}.{cls.__name__}"
        f"  add_summarize_task={'有' if callable(getattr(cls, 'add_summarize_task', None)) else '无'}"
        f"  summarize={'有' if callable(getattr(cls, 'summarize', None)) else '无'}"
        f"  compact_summary={'有' if callable(getattr(cls, 'compact_summary', None)) else '无'}"
        f"  dream_write={'有' if callable(getattr(cls, 'dream_write', None)) else '无'}"
    )
