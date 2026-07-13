# -*- coding: utf-8 -*-
"""
CoApis 数据迁移框架 — 按版本递增执行，幂等，可重入。

使用方式：
    # 容器内执行
    python3 -m coapis.system.migrate --from 0.8.60 --to 0.9.0

    # 或通过 coapis CLI
    coapis migrate --from 0.8.60 --to 0.9.0

设计原则：
    1. 幂等性 — 重复执行不产生副作用
    2. 可回滚 — 关键操作前备份
    3. 日志记录 — 所有操作记录到 upgrade_log.jsonl
    4. 版本锁 — 迁移时写入 .upgrading 锁文件
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("coapis.migrate")


# ═══════════════════════════════════════════════════════════════
# 版本比较工具
# ═══════════════════════════════════════════════════════════════

def _parse_version(v: str) -> Tuple[int, ...]:
    """将版本字符串解析为可比较的元组。"""
    try:
        return tuple(int(x) for x in v.strip().split("."))
    except (ValueError, AttributeError):
        return (0, 0, 0)


def _version_lt(a: str, b: str) -> bool:
    """判断 a < b。"""
    return _parse_version(a) < _parse_version(b)


def _version_le(a: str, b: str) -> bool:
    """判断 a <= b。"""
    return _parse_version(a) <= _parse_version(b)


# ═══════════════════════════════════════════════════════════════
# 迁移注册表 — 按版本递增排列
# ═══════════════════════════════════════════════════════════════
#
# 添加新迁移的步骤：
#   1. 在下方 MIGRATIONS 列表末尾添加 (版本号, 迁移函数)
#   2. 实现迁移函数，函数签名: (working_dir: Path) -> None
#   3. 函数内部做幂等检查，避免重复执行
#
# 示例：
#   MIGRATIONS.append(("0.9.1", migrate_to_0_9_1))
#

MIGRATIONS: List[Tuple[str, Callable]] = []


def _register(version: str):
    """迁移函数注册装饰器。"""
    def decorator(fn: Callable):
        MIGRATIONS.append((version, fn))
        return fn
    return decorator


# ═══════════════════════════════════════════════════════════════
# 迁移函数实现
# ═══════════════════════════════════════════════════════════════

@_register("0.9.0")
def migrate_to_0_9_0(working_dir: Path) -> None:
    """0.9.0 迁移：统一架构优化 + 模板更新 + 技能池扩展。

    变更清单：
    1. config.json 补充 version 字段
    2. system/templates/ 更新 AGENTS.md、PROFILE.md
    3. skill_pool/ 新增 env_manager 技能
    4. system/templates/ 新增模板文件（如不存在）
    """

    # ── 1. config.json 补充 version 字段 ──
    config_file = working_dir / "system" / "config.json"
    if config_file.exists():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                config = json.load(f)
            if "version" not in config:
                config["version"] = "0.9.0"
                _atomic_save_json(config_file, config)
                logger.info("Added version field to config.json")
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to update config.json: %s", e)

    # ── 2. 更新系统模板 ──
    templates_dir = working_dir / "system" / "templates"
    templates_dir.mkdir(parents=True, exist_ok=True)

    # AGENTS.md 精简版
    agents_md_content = """# AGENTS.md

## 安全

- 绝不泄露私密数据。绝不。
- 运行破坏性命令前先问。
- `trash` > `rm`（能恢复总比永久删除好）
- 拿不准的事情，需要跟用户确认。

### 🚨🚨🚨 代码修改铁律（最高优先级！）

**任何涉及代码修改、问题解决、修复、优化的操作，只要涉及代码的：**

1. **先调查**：读代码、查日志、分析根因，不改任何东西
2. **给方案**：写清楚要改什么文件、改什么内容、为什么这么改、可能的影响
3. **等确认**：用户确认后才能动手改代码
4. **改完验证**：改完后告诉用户改了什么，验证结果

**绝对不允许：**
- 未经告知就直接改代码
- 先斩后奏（改完再说"我改了xxx"）
- 边分析边改（分析过程中顺手改了什么）
- 以"顺手"、"顺便"为由修改非目标文件

**违反此规则 = 严重违规。**

## 环境管理

> 完整操作指南见 `skills/env_manager/SKILL.md`

- **开发环境**：改完代码后自动重建部署
- **生产环境**：不自动更新，由小蜜蜂手动部署
- **铁律**：必须用 `docker compose` 管理容器；重建后端后必须重启 nginx

## 内部 vs 外部

**可以自由做的：** 读文件、探索、整理、学习、搜索网页、在工作区内工作

**先问一声：** 发邮件、发推、公开发帖、任何会离开本地的操作、任何你不确定的事

## 工具

Skills 提供工具。需要用时查看它的 `SKILL.md`。本地笔记记在 `MEMORY.md` 的「工具设置」section 里。身份和用户资料记在 `PROFILE.md` 里。

## 🚫 反循环铁律（最高优先级！）

**程序化执行** — `ToolCallGuard` 自动去重（相同参数2次警告）和连续调用警告（同工具5次），无需人工记忆。自检口诀："我刚才是不是在做和 10 秒前完全一样的事？" — 如果是，停。

## 💓 Heartbeats - 要主动！

收到 heartbeat 轮询时，给出有意义的回复。有 HEARTBEAT.md 就读，严格遵循，别推测或重复旧任务。

**用 heartbeat 当：** 多个检查可合并、需要对话上下文、时间可浮动（~30分钟）

**用 cron 当：** 精确时间重要（"每周一9:00准点"）、一次性提醒（"20分钟后提醒我"）

## 让它成为你的

这只是起点。摸索出什么管用后，加上你自己的习惯、风格和规则，更新工作空间下的 AGENTS.md 文件。

## 记忆

每次会话都是全新的。工作目录下的文件是你的记忆延续：

- **每日笔记：** `memory/YYYY-MM-DD.md`（按需创建 `memory/` 目录）— 发生事件的原始记录
- **长期记忆：** `MEMORY.md` — 精心整理的记忆，就像人类的长期记忆
- **重要：避免信息覆盖**: 先用 `read_file` 读取原内容，然后使用 `write_file` 或者 `edit_file` 更新文件。

用这些文件来记录重要的东西，包括决策、上下文、需要记住的事。除非用户明确要求，否则不要在记忆中记录敏感的信息。

### 🧠 MEMORY.md - 你的长期记忆

- 出于**安全考虑** — 不应泄露给陌生人的个人信息
- 你可以在主会话中**自由读取、编辑和更新** MEMORY.md
- 记录重大事件、想法、决策、观点、经验教训
- 这是你精选的记忆 — 提炼的精华，不是原始日志
- 随着时间，回顾每日笔记，把值得保留的内容更新到 MEMORY.md

### 📝 写下来 - 别只记在脑子里！

- **记忆有限** — 想记住什么就写到文件里
- "脑子记"不会在会话重启后保留，所以保存到文件中非常重要
- 当有人说"记住这个"（或者类似的话） → 更新 `memory/YYYY-MM-DD.md` 或相关文件
- 当你学到教训 → 更新 AGENTS.md、MEMORY.md 或相关技能文档
- 当你犯了错 → 记下来，让未来的你避免重蹈覆辙
- **写下来 远比 用脑子记住 更好**

### 🎯 主动记录 - 别总是等人叫你记！

对话中发现有价值的信息时，**先记下来，再回答问题**：

- 用户提到的个人信息（名字、偏好、习惯、工作方式）→ 更新 `PROFILE.md` 的「用户资料」section
- 对话中做出的重要决策或结论 → 记录到 `memory/YYYY-MM-DD.md`
- 发现的项目上下文、技术细节、工作流程 → 写入相关文件
- 用户表达的喜好或不满 → 更新 `PROFILE.md` 的「用户资料」section
- 工具相关的本地配置（SSH、摄像头等）→ 更新 `MEMORY.md` 的「工具设置」section
- 任何你觉得未来会话可能用到的信息 → 立刻记下来

**关键原则：** 不要总是等用户说"记住这个"。如果信息对未来有价值，主动记录。先记录，再回答 — 这样即使会话中断，信息也不会丢失。

### 🔍 检索工具
回答关于过往工作、决策、日期、人员、偏好或待办的问题前：
1. 对 MEMORY.md 和 memory/*.md 运行 `memory_search`
2. 如需阅读每日笔记 `memory/YYYY-MM-DD.md`，直接用 `read_file`
"""

    _safe_write_template(templates_dir / "AGENTS.md", agents_md_content)

    # PROFILE.md 含 emoji 规则
    profile_md_content = """## 身份

- **名字：**
- **角色：** AI 助手
- **风格：** 直接、高效、像朋友一样交流

## 用户资料

- **名字：**
- **怎么叫他们：**
- **代词：**
- **笔记：**

## 交互风格

### 表情使用
在支持表情回应的平台（Discord、Slack、企微）上自然使用 emoji：
- 认可不必回复：👍、❤️、🙌
- 好笑：😂、💀
- 有趣/深思：🤔、💡
- 看到了不打断：👀
- 简单表态：✅、❌
- **每条消息最多一个表情**，选最合适的。
"""

    _safe_write_template(templates_dir / "PROFILE.md", profile_md_content)

    # ── 3. 新增 env_manager 技能到 skill_pool ──
    skill_pool_dir = working_dir / "skill_pool"
    skill_pool_dir.mkdir(parents=True, exist_ok=True)

    env_manager_dir = skill_pool_dir / "env_manager"
    if not env_manager_dir.exists():
        # 从镜像内复制（如果存在）
        source = Path("/app/coapis/skill_pool/env_manager")
        if source.exists() and source.is_dir():
            shutil.copytree(source, env_manager_dir)
            logger.info("Copied env_manager skill from image")
        else:
            # 镜像内不存在，创建基础版本
            env_manager_dir.mkdir(parents=True, exist_ok=True)
            skill_md = """# env_manager — 环境管理技能

管理 CoApis 的开发环境和生产环境部署。

## 使用场景

- 改完代码后需要重建部署
- 检查容器状态
- 查看服务日志
- 重启 nginx

## 核心规则

### 开发环境
- 改完代码后**自动重建部署**
- 命令：`docker compose -f docker-compose.dev.yaml up -d --build`

### 生产环境
- **不自动更新**，由小蜜蜂手动部署
- 命令：`docker compose -f docker-compose.yml up -d --build`

### 铁律
1. 必须用 `docker compose` 管理容器
2. 重建后端后**必须重启 nginx**：`docker restart coapis-dev-nginx`
3. 生产环境操作前**必须确认**

## 常用命令

```bash
# 查看开发环境状态
docker compose -f docker-compose.dev.yaml ps

# 查看生产环境状态
docker compose -f docker-compose.yml ps

# 重建开发环境后端
docker compose -f docker-compose.dev.yaml up -d --build coapis-dev

# 重启 nginx
docker restart coapis-dev-nginx

# 查看后端日志
docker logs coapis-dev --tail 50
```
"""
            _safe_write_template(env_manager_dir / "SKILL.md", skill_md)
            logger.info("Created env_manager skill template")


# ═══════════════════════════════════════════════════════════════
# 迁移引擎
# ═══════════════════════════════════════════════════════════════

class MigrationRunner:
    """迁移执行器。"""

    def __init__(self, working_dir: Path):
        self.working_dir = working_dir
        self.log_file = working_dir / "system" / "upgrade_log.jsonl"
        self.lock_file = working_dir / ".upgrading"

    def run(self, from_version: str, to_version: str) -> Dict[str, Any]:
        """执行从 from_version 到 to_version 的所有迁移。

        Returns:
            迁移结果摘要
        """
        result: Dict[str, Any] = {
            "success": True,
            "from_version": from_version,
            "to_version": to_version,
            "applied": [],
            "skipped": [],
            "errors": [],
            "start_time": time.time(),
        }

        # 写入升级锁
        self._write_lock(from_version, to_version)

        try:
            for target_ver, migration_fn in MIGRATIONS:
                # 跳过已经是或低于当前版本的迁移
                if _version_le(target_ver, from_version):
                    result["skipped"].append(target_ver)
                    logger.debug("Skipping migration %s (already at %s)", target_ver, from_version)
                    continue

                # 跳过超过目标版本的迁移
                if _version_lt(to_version, target_ver):
                    result["skipped"].append(target_ver)
                    logger.debug("Skipping migration %s (beyond target %s)", target_ver, to_version)
                    continue

                # 执行迁移
                logger.info("Running migration to %s...", target_ver)
                try:
                    migration_fn(self.working_dir)
                    result["applied"].append(target_ver)
                    logger.info("Migration to %s completed", target_ver)
                except Exception as e:
                    result["errors"].append({
                        "version": target_ver,
                        "error": str(e),
                        "type": type(e).__name__,
                    })
                    result["success"] = False
                    logger.error("Migration to %s failed: %s", target_ver, e, exc_info=True)
                    break

        finally:
            result["duration_seconds"] = round(time.time() - result["start_time"], 2)
            self._remove_lock()
            self._write_log(result)

        return result

    def _write_lock(self, from_ver: str, to_ver: str) -> None:
        """写入升级锁文件。"""
        try:
            lock_data = {
                "pid": os.getpid(),
                "from_version": from_ver,
                "to_version": to_ver,
                "started_at": time.time(),
            }
            self.lock_file.write_text(json.dumps(lock_data, indent=2))
        except OSError:
            pass

    def _remove_lock(self) -> None:
        """删除升级锁文件。"""
        try:
            self.lock_file.unlink(missing_ok=True)
        except OSError:
            pass

    def _write_log(self, result: Dict[str, Any]) -> None:
        """追加升级日志。"""
        try:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            log_entry = {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                **result,
            }
            # 移除不可序列化的字段
            log_entry.pop("start_time", None)
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except OSError as e:
            logger.warning("Failed to write upgrade log: %s", e)


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

def _atomic_save_json(path: Path, data: Any) -> None:
    """原子性保存 JSON 文件（先写 .tmp 再 rename）。"""
    tmp_path = path.with_suffix(".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(str(tmp_path), str(path))
    except OSError:
        tmp_path.unlink(missing_ok=True)
        raise


def _safe_write_template(path: Path, content: str) -> None:
    """安全写入模板文件。

    策略：
    - 如果文件不存在，直接创建
    - 如果文件存在但内容不同，备份后覆盖
    - 如果文件存在且内容相同，跳过
    """
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing.strip() == content.strip():
            return  # 内容相同，跳过

        # 内容不同，备份后覆盖
        backup_path = path.with_suffix(f".bak.{int(time.time())}")
        shutil.copy2(path, backup_path)
        logger.info("Backed up %s to %s", path.name, backup_path.name)

    path.write_text(content, encoding="utf-8")
    logger.info("Wrote template: %s", path.name)


def get_current_version(working_dir: Path) -> str:
    """获取当前数据版本。"""
    # 优先从 config.json 读取
    config_file = working_dir / "system" / "config.json"
    if config_file.exists():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                config = json.load(f)
            if "version" in config:
                return config["version"]
        except (json.JSONDecodeError, OSError):
            pass

    # 回退到 .initialized
    init_file = working_dir / ".initialized"
    if init_file.exists():
        try:
            with open(init_file, "r", encoding="utf-8") as f:
                marker = json.load(f)
            return marker.get("version", "0.0.0")
        except (json.JSONDecodeError, OSError):
            pass

    return "0.0.0"


# ═══════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════

def main():
    """CLI 入口。"""
    parser = argparse.ArgumentParser(description="CoApis 数据迁移工具")
    parser.add_argument("--from", dest="from_version", help="当前版本（默认自动检测）")
    parser.add_argument("--to", dest="to_version", required=True, help="目标版本")
    parser.add_argument("--working-dir", default=os.environ.get("COAPIS_WORKING_DIR", str(Path.home() / ".coapis")),
                        help="数据目录路径")
    parser.add_argument("--dry-run", action="store_true", help="只显示要执行的迁移，不实际执行")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")

    args = parser.parse_args()

    # 设置日志
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    working_dir = Path(args.working_dir)
    if not working_dir.exists():
        logger.error("Working directory not found: %s", working_dir)
        sys.exit(1)

    # 自动检测当前版本
    from_version = args.from_version or get_current_version(working_dir)
    to_version = args.to_version

    logger.info("═══════════════════════════════════════════════════")
    logger.info("CoApis 数据迁移")
    logger.info("  数据目录: %s", working_dir)
    logger.info("  当前版本: %s", from_version)
    logger.info("  目标版本: %s", to_version)
    logger.info("═══════════════════════════════════════════════════")

    if args.dry_run:
        logger.info("DRY RUN — 以下迁移将被执行但不会实际执行：")
        for ver, _ in MIGRATIONS:
            if _version_lt(from_version, ver) and _version_le(ver, to_version):
                logger.info("  → %s", ver)
        return

    # 执行迁移
    runner = MigrationRunner(working_dir)
    result = runner.run(from_version, to_version)

    # 输出结果
    if result["success"]:
        logger.info("✅ 迁移成功完成")
        if result["applied"]:
            logger.info("  已应用: %s", ", ".join(result["applied"]))
        if result["skipped"]:
            logger.info("  已跳过: %s", ", ".join(result["skipped"]))
        logger.info("  耗时: %.2f 秒", result["duration_seconds"])
    else:
        logger.error("❌ 迁移失败")
        for err in result["errors"]:
            logger.error("  版本 %s: %s (%s)", err["version"], err["error"], err["type"])
        sys.exit(1)


if __name__ == "__main__":
    main()
