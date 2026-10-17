"""E2E probe (in-container): the three paths that used to crash (B1/B2).

1. screenshot with no path  -> was ``NameError: name 'path' is not defined``
2. file_upload              -> was ``NameError: name 'paths_json' is not defined``
3. legacy kwargs (filename/file_path/screenshot_type/width/height/level)
                            -> was ``TypeError: unexpected keyword argument``

Expected now: a normal tool response (an error message is fine — what must
not happen is NameError/TypeError escaping the tool).
"""
import asyncio
import sys

sys.path.insert(0, "/app")

from coapis.agents.tools.browser_control import browser_use  # noqa: E402

CASES = [
    ("screenshot 无 path", dict(action="screenshot")),
    ("screenshot 传 filename", dict(action="screenshot", filename="x.png")),
    ("screenshot 传 file_path+screenshot_type", dict(action="screenshot", file_path="y.png", screenshot_type="jpeg")),
    ("file_upload 无参", dict(action="file_upload")),
    ("file_upload 带 paths_json", dict(action="file_upload", paths_json='["/tmp/a.txt"]')),
    ("pdf 传 snapshot_filename", dict(action="pdf", snapshot_filename="z.pdf")),
    ("console_messages 传 level", dict(action="console_messages", level="info")),
    ("resize 传 width/height", dict(action="resize", width=1200, height=800)),
    ("list_cdp_targets 传 port_min/port_max", dict(action="list_cdp_targets", port_min=9000, port_max=9100)),
    ("network_requests 传 include_static", dict(action="network_requests", include_static=True)),
]


def _text(resp) -> str:
    out = []
    for block in getattr(resp, "content", []) or []:
        out.append(block.get("text", "") if isinstance(block, dict) else getattr(block, "text", ""))
    return " | ".join(out)[:220]


async def main():
    bad = 0
    for label, kwargs in CASES:
        try:
            resp = await browser_use(**kwargs)
            print(f"  OK   {label:42s} -> {_text(resp)}")
        except NameError as exc:
            bad += 1
            print(f"  NameError {label:42s} -> {exc}")
        except TypeError as exc:
            bad += 1
            print(f"  TypeError {label:42s} -> {exc}")
        except Exception as exc:  # noqa: BLE001
            print(f"  other  {label:42s} -> {type(exc).__name__}: {exc}")
    print(f"\n必崩(NameError/TypeError)计数 = {bad}")
    return bad


if __name__ == "__main__":
    sys.exit(1 if asyncio.run(main()) else 0)
