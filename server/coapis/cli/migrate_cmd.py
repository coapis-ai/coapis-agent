# -*- coding: utf-8 -*-
"""CLI command: coapis migrate — 数据迁移工具。"""
from __future__ import annotations

import os
import sys
import logging
from pathlib import Path

import click

logger = logging.getLogger(__name__)


@click.command("migrate")
@click.option("--from", "from_version", default=None, help="当前版本（默认自动检测）")
@click.option("--to", "to_version", required=True, help="目标版本")
@click.option(
    "--working-dir",
    default=None,
    help="数据目录路径（默认 COAPIS_WORKING_DIR 环境变量或 /apps/ai/coapis）",
)
@click.option("--dry-run", is_flag=True, help="只显示要执行的迁移，不实际执行")
@click.option("--verbose", "-v", is_flag=True, help="详细输出")
def migrate_cmd(
    from_version: str | None,
    to_version: str,
    working_dir: str | None,
    dry_run: bool,
    verbose: bool,
) -> None:
    """执行数据迁移（按版本递增，幂等，可重入）。

    \b
    示例：
        coapis migrate --to 0.9.0                    # 自动检测当前版本
        coapis migrate --from 0.8.60 --to 0.9.0     # 指定版本
        coapis migrate --to 0.9.0 --dry-run          # 预览迁移
        coapis migrate --to 0.9.0 -v                 # 详细输出
    """
    # 设置日志
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # 确定数据目录
    wd = Path(working_dir or os.environ.get("COAPIS_WORKING_DIR", "/apps/ai/coapis"))
    if not wd.exists():
        click.echo(f"❌ 数据目录不存在: {wd}", err=True)
        sys.exit(1)

    # 导入迁移模块（延迟导入，避免 CLI 加载时拉入全链）
    from ..system.migrate import MigrationRunner, get_current_version, MIGRATIONS, _version_lt, _version_le

    # 自动检测当前版本
    detected_version = from_version or get_current_version(wd)

    click.echo("")
    click.echo("═══════════════════════════════════════════════════════")
    click.echo("CoApis 数据迁移")
    click.echo(f"  数据目录: {wd}")
    click.echo(f"  当前版本: {detected_version}")
    click.echo(f"  目标版本: {to_version}")
    click.echo("═══════════════════════════════════════════════════════")
    click.echo("")

    if dry_run:
        click.echo("🔍 DRY RUN — 以下迁移将被执行但不会实际执行：")
        found = False
        for ver, _ in MIGRATIONS:
            if _version_lt(detected_version, ver) and _version_le(ver, to_version):
                click.echo(f"  → {ver}")
                found = True
        if not found:
            click.echo("  (无需要执行的迁移)")
        return

    # 执行迁移
    runner = MigrationRunner(wd)
    result = runner.run(detected_version, to_version)

    # 输出结果
    if result["success"]:
        click.echo("✅ 迁移成功完成")
        if result["applied"]:
            click.echo(f"  已应用: {', '.join(result['applied'])}")
        if result["skipped"]:
            click.echo(f"  已跳过: {', '.join(result['skipped'])}")
        click.echo(f"  耗时: {result['duration_seconds']:.2f} 秒")
    else:
        click.echo("❌ 迁移失败", err=True)
        for err in result["errors"]:
            click.echo(f"  版本 {err['version']}: {err['error']} ({err['type']})", err=True)
        sys.exit(1)
