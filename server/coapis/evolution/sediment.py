"""重要事项自动固化：经验池 → AGENTS.md（D3 拍板：自动写入）。

为什么需要这一层
----------------
经验池（approved.jsonl）只走"检索式注入"：话题撞上才进提示词。而小蜜蜂
反馈过反复出现的问题 ——「重要信息只散在记忆里，AGENTS.md 基本没更新，
隔一阵就忘」—— 那是缺一条把**反复验证过的稳定做法**下沉成工作约定的通路。

这里刻意**不用"被注入次数"当门槛**：自己注入自己计数、再据此更用力地注入，
是自我强化的假信号（同类的闭环造假我们刚拆过）。真信号是同一主题被**独立
提取多次**（occurrences）+ 置信度高（confidence），这是外部证据。

安全阀（AGENTS.md 会被注入系统提示词，膨胀即挤占上下文）
--------------------------------------------------------
* 只收 ``preference / lesson / pattern``，不收 skill 类碎片；
* 单条压成一行、截到 :data:`MAX_LINE_CHARS`；
* 总条数封顶 :data:`MAX_ENTRIES_DEFAULT`（约 2KB 量级）；
* 疑似密钥/口令的内容一律不落盘；
* 只改写自己标记的区块，不碰文件其余内容；内容没变就不写盘。

纯函数（:func:`candidates` / :func:`render_block` / :func:`merge_block`）
与 IO（:func:`read_experiences` / :func:`sediment`）严格分开，便于单测。
"""
from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path
from typing import Any, Iterable

from . import paths, recall

logger = logging.getLogger(__name__)

# ── 门槛（拍板值，见 MEMORY.md 2026-11-27）────────────────────────
MIN_OCCURRENCES_DEFAULT = 3     # 同一主题至少被独立记录 3 次
MIN_CONFIDENCE_DEFAULT = 0.9    # 且置信度 ≥0.9
MAX_ENTRIES_DEFAULT = 20        # AGENTS.md 固化区最多 20 条
MAX_LINE_CHARS = 110            # 单条最长 110 字
SEDIMENT_HALF_LIFE_DAYS = 180.0  # 仅用于排序，不做硬淘汰（老规矩依然有效）
ALLOWED_TYPES = frozenset({"preference", "lesson", "pattern"})
SECRET_HINTS = ("token", "password", "passwd", "secret", "api_key", "apikey",
                "密钥", "口令", "密码")

BLOCK_TITLE = "## 自动沉淀的重要事项"
MARK_START = "<!-- coapis:sediment:start -->"
MARK_END = "<!-- coapis:sediment:end -->"
_THROTTLE_FILE = ".sediment_at"


def _now(now: datetime.datetime | None = None) -> datetime.datetime:
    if now is not None:
        return now
    return datetime.datetime.now(datetime.timezone.utc)


def _clean(text: str) -> str:
    """压成单行并截断（防止把多段 markdown 带进 AGENTS.md）。"""
    parts = [ln.strip() for ln in str(text or "").splitlines() if ln.strip()]
    line = " ".join(parts).strip()
    line = line.replace("```", "").replace("\t", " ")
    # 列表/标题符号会让固化区里的层级打架
    while line[:1] in ("#", "-", "*", ">", "|"):
        line = line[1:].strip()
    if len(line) > MAX_LINE_CHARS:
        line = line[:MAX_LINE_CHARS - 1] + "…"
    return line


def _looks_secret(text: str) -> bool:
    low = text.lower()
    return any(h in low for h in SECRET_HINTS)


def candidates(experiences: Iterable[dict], *, now: datetime.datetime | None = None,
               min_occurrences: int = MIN_OCCURRENCES_DEFAULT,
               min_confidence: float = MIN_CONFIDENCE_DEFAULT,
               cap: int = MAX_ENTRIES_DEFAULT,
               allowed_types: frozenset[str] | None = ALLOWED_TYPES,
               ) -> list[dict[str, Any]]:
    """按主题簇筛选"够重要、够稳定"的条目，返回排序后的固化候选。

    打分 = 出现次数 × 置信度 × 新鲜度（半衰期 180 天，只排序不淘汰）。
    """
    clusters: dict[str, list[dict]] = {}
    for exp in experiences or ():
        if not isinstance(exp, dict):
            continue
        etype = str(exp.get("experience_type") or "misc").strip().lower()
        if allowed_types is not None and etype not in allowed_types:
            continue
        clusters.setdefault(recall.cluster_key(exp), []).append(exp)

    out: list[dict[str, Any]] = []
    for key, rows in clusters.items():
        if len(rows) < max(2, min_occurrences):
            continue
        # 门槛看"簇里最高置信度"（这个主题是否可信），代表条却按
        # 置信×新鲜度挑 —— 否则同主题里那条**过期**的旧事实会赢，
        # 把"开发入口 4200"这种已被纠正的旧值固化进工作约定。
        top_conf = max(float(r.get("confidence") or 0.0) for r in rows)
        if top_conf < min_confidence:
            continue
        best = max(rows, key=lambda r: recall.relevance_score(
            r, now=now, hl=SEDIMENT_HALF_LIFE_DAYS))
        conf = float(best.get("confidence") or 0.0)
        text = _clean(best.get("content") or best.get("title") or "")
        if not text or _looks_secret(text):
            continue
        fresh = max(recall.freshness(r, now=now, hl=SEDIMENT_HALF_LIFE_DAYS)
                    for r in rows)
        agents = sorted({str(a) for r in rows for a in (r.get("agent_ids") or [])})
        out.append({
            "key": key,
            "text": text,
            "occurrences": len(rows),
            "confidence": round(conf, 3),
            "freshness": round(fresh, 3),
            "score": round(len(rows) * conf * fresh, 4),
            "types": sorted({str(r.get("experience_type") or "misc") for r in rows}),
            "agents": agents[:5],
        })
    out.sort(key=lambda d: (d["score"], d["occurrences"]), reverse=True)
    return out[:max(0, cap)]


def render_block(items: list[dict[str, Any]], *, now: datetime.datetime | None = None) -> str:
    """渲染固化区块（空列表返回空串 = 不写内容）。"""
    if not items:
        return ""
    stamp = _now(now).strftime("%Y-%m-%d")
    lines = [
        MARK_START,
        BLOCK_TITLE,
        "",
        f"> 由经验池自动沉淀（{stamp}）。判据：同主题被独立记录 ≥{MIN_OCCURRENCES_DEFAULT} "
        f"次且置信度 ≥{MIN_CONFIDENCE_DEFAULT}；上限 {MAX_ENTRIES_DEFAULT} 条。"
        "改动请连经验池一起改，手改会在下次沉淀时被覆盖。",
        "",
    ]
    for it in items:
        meta = f"{it['occurrences']}次·置信{it['confidence']:g}"
        lines.append(f"- {it['text']}（{meta}）")
    lines.append(MARK_END)
    return "\n".join(lines)


def merge_block(md: str, block: str) -> str:
    """把固化区块写进 markdown 文本；只替换自己的标记区，其余原样保留。"""
    body = (md or "").rstrip("\n")
    old_start = body.find(MARK_START)
    old_end = body.find(MARK_END)
    if old_start != -1 and old_end != -1 and old_end > old_start:
        before = body[:old_start].rstrip("\n")
        after = body[old_end + len(MARK_END):].lstrip("\n")
        if not block:
            return (before + "\n\n" + after).strip() + "\n" if (before or after) else ""
        return "\n\n".join(p for p in (before, block, after) if p).strip() + "\n"
    if not block:
        return (md or "")
    return (body + "\n\n" if body else "") + block + "\n"


def read_experiences(path: Path | None = None) -> list[dict]:
    """读经验池账本（JSONL），坏行跳过并告警。"""
    path = Path(path) if path is not None else paths.approved_experiences_file()
    rows: list[dict] = []
    if not paths.report_readable(path, "记忆固化"):
        return rows
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for lineno, raw in enumerate(fh, 1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except ValueError:
                    logger.warning("经验池第 %d 行不是合法 JSON，跳过: %s", lineno, raw[:80])
                    continue
                if isinstance(obj, dict):
                    rows.append(obj)
    except OSError as exc:
        logger.warning("读经验池失败 %s: %s", path, exc)
    return rows


def sediment(workspace_dir: Path | str, *, experiences: list[dict] | None = None,
             now: datetime.datetime | None = None, cap: int = MAX_ENTRIES_DEFAULT,
             dry_run: bool = False) -> dict[str, Any]:
    """把一个智能体的重要事项固化进其 ``AGENTS.md``（幂等，内容不变不写盘）。

    Returns:
        ``{"written": bool, "entries": int, "items": [...], "path": str}``
    """
    ws = Path(workspace_dir)
    target = ws / "AGENTS.md"
    rows = read_experiences() if experiences is None else experiences
    items = candidates(rows, now=now, cap=cap)
    block = render_block(items, now=now)

    existing = ""
    if target.exists():
        try:
            existing = target.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("读 %s 失败: %s", target, exc)
            return {"written": False, "entries": 0, "items": [], "path": str(target),
                    "error": str(exc)}
    merged = merge_block(existing, block)
    result = {"written": False, "entries": len(items), "items": items,
              "path": str(target)}
    if merged == existing:
        result["skipped"] = "unchanged"
        return result
    if dry_run:
        result["skipped"] = "dry_run"
        return result
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(merged, encoding="utf-8")
    except OSError as exc:
        logger.warning("写 %s 失败: %s", target, exc)
        result["error"] = str(exc)
        return result
    result["written"] = True
    logger.info("重要事项已固化进 AGENTS.md: %d 条（%s）", len(items), target)
    return result
