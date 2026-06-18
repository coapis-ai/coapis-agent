"""SKILL.md 版本管理 — 解析 frontmatter、自动递增版本、历史存档、回滚。

数据结构：
  system/skill_evolution/history/{skill_name}/v1.0.md
  system/skill_evolution/history/{skill_name}/v1.1.md
  system/skill_evolution/history/{skill_name}/v2.0.md

每次 save_skill 时自动：
  1. 解析 SKILL.md frontmatter 中的 version 字段（默认 "1.0"）
  2. 递增 minor 版本（1.0 → 1.1, 1.1 → 1.2）
  3. 将旧版本内容存入 history 目录
  4. 更新 frontmatter 中的 version 字段
"""

from __future__ import annotations

import logging
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _get_history_dir() -> Path:
    """版本历史根目录：system/skill_evolution/history/"""
    wd = os.environ.get("COAPIS_WORKING_DIR")
    if wd:
        p = Path(wd) / "system" / "skill_evolution" / "history"
    else:
        p = Path(__file__).resolve().parent.parent.parent.parent / "system" / "skill_evolution" / "history"
    p.mkdir(parents=True, exist_ok=True)
    return p


def parse_frontmatter(content: str) -> dict[str, str]:
    """解析 SKILL.md 的 YAML frontmatter，返回 key-value dict。"""
    if not content.startswith("---"):
        return {}
    end = content.find("---", 3)
    if end < 0:
        return {}
    fm_block = content[3:end].strip()
    result: dict[str, str] = {}
    for line in fm_block.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        result[key.strip()] = value.strip()
    return result


def get_version(content: str) -> str:
    """从 SKILL.md frontmatter 提取 version，不存在则返回 '1.0'。"""
    fm = parse_frontmatter(content)
    return fm.get("version", "1.0")


def bump_version(version: str) -> str:
    """递增 minor 版本：'1.0' → '1.1', '1.1' → '1.2', '2.5' → '2.6'。"""
    match = re.match(r"^(\d+)\.(\d+)$", version.strip())
    if not match:
        return "1.1"
    major, minor = int(match.group(1)), int(match.group(2))
    return f"{major}.{minor + 1}"


def set_version_in_content(content: str, new_version: str) -> str:
    """更新 SKILL.md frontmatter 中的 version 字段。如不存在则添加。"""
    if not content.startswith("---"):
        # 无 frontmatter，添加一个
        return f"---\nversion: {new_version}\n---\n{content}"

    end = content.find("---", 3)
    if end < 0:
        return f"---\nversion: {new_version}\n---\n{content}"

    fm_block = content[3:end]
    rest = content[end + 3:]

    # 替换或添加 version
    if "version:" in fm_block:
        fm_block = re.sub(
            r"version:\s*[\d.]+",
            f"version: {new_version}",
            fm_block,
        )
    else:
        fm_block = fm_block.rstrip() + f"\nversion: {new_version}\n"

    return f"---\n{fm_block}---{rest}"


def archive_version(
    skill_name: str,
    version: str,
    content: str,
) -> Path:
    """将指定版本的 SKILL.md 存入历史目录，返回存档路径。"""
    hist_dir = _get_history_dir() / skill_name
    hist_dir.mkdir(parents=True, exist_ok=True)
    target = hist_dir / f"v{version}.md"
    target.write_text(content, encoding="utf-8")
    logger.info("Archived skill '%s' version %s to %s", skill_name, version, target)
    return target


def archive_skill_dir_version(
    skill_name: str,
    version: str,
    skill_dir: Path,
) -> Path | None:
    """将整个技能目录存入历史（支持多文件技能）。返回存档目录路径。"""
    if not skill_dir.exists():
        return None
    hist_dir = _get_history_dir() / skill_name / f"v{version}"
    if hist_dir.exists():
        shutil.rmtree(hist_dir)
    shutil.copytree(skill_dir, hist_dir)
    logger.info(
        "Archived skill dir '%s' v%s (%d files) to %s",
        skill_name,
        version,
        len(list(hist_dir.rglob("*"))),
        hist_dir,
    )
    return hist_dir


def list_versions(skill_name: str) -> list[dict[str, Any]]:
    """列出某技能的所有历史版本，按版本号排序。"""
    hist_dir = _get_history_dir() / skill_name
    if not hist_dir.exists():
        return []
    versions = []
    for item in sorted(hist_dir.iterdir()):
        if item.is_file() and item.name.startswith("v") and item.name.endswith(".md"):
            version = item.name[1:-3]  # v1.0.md → 1.0
            stat = item.stat()
            content = item.read_text(encoding="utf-8")
            fm = parse_frontmatter(content)
            versions.append({
                "version": version,
                "archived_at": datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat(),
                "size_bytes": stat.st_size,
                "description": fm.get("description", "")[:200],
            })
        elif item.is_dir() and item.name.startswith("v"):
            version = item.name[1:]  # v1.0 → 1.0
            stat = item.stat()
            file_count = len(list(item.rglob("*")))
            # 读取 SKILL.md 获取描述
            skill_md = item / "SKILL.md"
            desc = ""
            if skill_md.exists():
                fm = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
                desc = fm.get("description", "")[:200]
            versions.append({
                "version": version,
                "archived_at": datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat(),
                "size_bytes": sum(f.stat().st_size for f in item.rglob("*") if f.is_file()),
                "file_count": file_count,
                "description": desc,
            })
    # 按版本号排序
    def _ver_key(v: dict) -> tuple[int, int]:
        parts = v["version"].split(".")
        try:
            return (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
        except (ValueError, IndexError):
            return (0, 0)

    versions.sort(key=_ver_key)
    return versions


def get_version_content(skill_name: str, version: str) -> str | None:
    """获取指定版本的 SKILL.md 内容。"""
    hist_dir = _get_history_dir() / skill_name
    # 尝试单文件格式
    target = hist_dir / f"v{version}.md"
    if target.exists():
        return target.read_text(encoding="utf-8")
    # 尝试目录格式
    target_dir = hist_dir / f"v{version}"
    if target_dir.exists():
        skill_md = target_dir / "SKILL.md"
        if skill_md.exists():
            return skill_md.read_text(encoding="utf-8")
    return None


def save_metrics_snapshot(skill_name: str, version: str, metrics: dict) -> None:
    """保存技能版本的效能指标快照，用于版本间对比。"""
    snapshot_dir = _get_history_dir() / skill_name
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_file = snapshot_dir / f"v{version}_metrics.json"
    import json
    data = {
        "skill_name": skill_name,
        "version": version,
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
        "metrics": metrics,
    }
    snapshot_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Saved metrics snapshot for %s v%s", skill_name, version)


def compare_versions(skill_name: str, old_version: str, new_version: str) -> dict | None:
    """对比两个版本的效能指标快照。

    Returns:
        包含各维度变化和告警信息的字典，任一快照不存在时返回 None。
    """
    import json

    def _load_snapshot(version: str) -> dict | None:
        snapshot_file = _get_history_dir() / skill_name / f"v{version}_metrics.json"
        if not snapshot_file.exists():
            return None
        try:
            return json.loads(snapshot_file.read_text(encoding="utf-8"))
        except Exception:
            return None

    old_snap = _load_snapshot(old_version)
    new_snap = _load_snapshot(new_version)
    if not old_snap or not new_snap:
        return None

    old_m = old_snap.get("metrics", {})
    new_m = new_snap.get("metrics", {})

    dimensions = ["precision", "reliability", "effectiveness", "satisfaction", "robustness", "composite_score"]
    changes = {}
    alerts = []
    threshold = -0.1  # 效能下降超过 10% 告警

    for dim in dimensions:
        old_val = old_m.get(dim, 0)
        new_val = new_m.get(dim, 0)
        delta = new_val - old_val
        changes[dim] = {
            "old": round(old_val, 4),
            "new": round(new_val, 4),
            "delta": round(delta, 4),
            "delta_pct": round(delta * 100, 2) if old_val > 0 else 0,
        }
        if delta < threshold:
            alerts.append(f"{dim} 下降 {abs(delta)*100:.1f}% ({old_val:.3f} → {new_val:.3f})")

    return {
        "skill_name": skill_name,
        "old_version": old_version,
        "new_version": new_version,
        "old_snapshot_at": old_snap.get("snapshot_at", ""),
        "new_snapshot_at": new_snap.get("snapshot_at", ""),
        "changes": changes,
        "alerts": alerts,
        "overall": "regressed" if alerts else "improved_or_stable",
    }


def restore_version(
    skill_name: str,
    version: str,
    skill_dir: Path,
) -> bool:
    """将指定历史版本恢复到技能目录。返回是否成功。"""
    hist_dir = _get_history_dir() / skill_name
    # 尝试单文件格式
    target = hist_dir / f"v{version}.md"
    if target.exists():
        skill_dir.mkdir(parents=True, exist_ok=True)
        # 更新版本号到当前最新
        content = target.read_text(encoding="utf-8")
        # 不修改版本号，保留回滚时的原始版本
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
        logger.info("Restored skill '%s' v%s from single file", skill_name, version)
        return True
    # 尝试目录格式
    target_dir = hist_dir / f"v{version}"
    if target_dir.exists():
        skill_dir.mkdir(parents=True, exist_ok=True)
        for f in target_dir.iterdir():
            if f.is_file():
                shutil.copy2(f, skill_dir / f.name)
        logger.info("Restored skill '%s' v%s from directory", skill_name, version)
        return True
    return False
