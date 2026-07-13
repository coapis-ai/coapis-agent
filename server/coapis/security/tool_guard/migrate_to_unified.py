#!/usr/bin/env python3
"""Migration script: generate unified tool_guard.yaml from legacy sources.

Reads:
  - security/tool_guard/rules/dangerous_shell_commands.yaml (29 rules)
  - security/command_risk_classifier.py (L0-L4 command definitions)

Writes:
  - {system_dir}/tool_guard.yaml (unified config)

Usage:
  python -m coapis.security.tool_guard.migrate_to_unified [--system-dir PATH]
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


# ── L0-L4 command definitions (from command_risk_classifier.py) ──

COMMAND_LEVELS: dict[str, dict[str, str]] = {
    # L0 — 只读 (read-only)
    "ls": {"level": "L0", "desc": "列出目录内容", "action": "allow"},
    "cat": {"level": "L0", "desc": "查看文件内容", "action": "allow"},
    "head": {"level": "L0", "desc": "查看文件头部", "action": "allow"},
    "tail": {"level": "L0", "desc": "查看文件尾部", "action": "allow"},
    "grep": {"level": "L0", "desc": "文本搜索", "action": "allow"},
    "find": {"level": "L0", "desc": "查找文件", "action": "allow"},
    "wc": {"level": "L0", "desc": "统计行数/词数", "action": "allow"},
    "echo": {"level": "L0", "desc": "输出文本", "action": "allow"},
    "pwd": {"level": "L0", "desc": "显示当前目录", "action": "allow"},
    "which": {"level": "L0", "desc": "查找命令路径", "action": "allow"},
    "whoami": {"level": "L0", "desc": "显示当前用户", "action": "allow"},
    "date": {"level": "L0", "desc": "显示日期时间", "action": "allow"},
    "env": {"level": "L0", "desc": "显示环境变量", "action": "allow"},
    "printenv": {"level": "L0", "desc": "打印环境变量", "action": "allow"},
    "file": {"level": "L0", "desc": "识别文件类型", "action": "allow"},
    "stat": {"level": "L0", "desc": "显示文件信息", "action": "allow"},
    "diff": {"level": "L0", "desc": "比较文件差异", "action": "allow"},
    "sort": {"level": "L0", "desc": "排序文本行", "action": "allow"},
    "uniq": {"level": "L0", "desc": "去重文本行", "action": "allow"},
    "awk": {"level": "L0", "desc": "文本处理", "action": "allow"},
    "sed": {"level": "L0", "desc": "流编辑器", "action": "allow"},
    # L1 — 文件操作 (file operations)
    "mkdir": {"level": "L1", "desc": "创建目录", "action": "audit"},
    "touch": {"level": "L1", "desc": "创建/更新文件时间戳", "action": "audit"},
    "cp": {"level": "L1", "desc": "复制文件", "action": "audit"},
    "mv": {"level": "L1", "desc": "移动/重命名文件", "action": "audit"},
    "ln": {"level": "L1", "desc": "创建链接", "action": "audit"},
    "chmod": {"level": "L1", "desc": "修改文件权限", "action": "audit"},
    "chown": {"level": "L1", "desc": "修改文件所有者", "action": "audit"},
    "tee": {"level": "L1", "desc": "输出到文件和标准输出", "action": "audit"},
    "truncate": {"level": "L1", "desc": "截断文件", "action": "audit"},
    # L2 — 执行/网络 (execution/network)
    "curl": {"level": "L2", "desc": "HTTP 请求", "action": "confirm"},
    "wget": {"level": "L2", "desc": "下载文件", "action": "confirm"},
    "git": {"level": "L2", "desc": "版本控制", "action": "confirm"},
    "python": {"level": "L2", "desc": "Python 解释器", "action": "confirm"},
    "python3": {"level": "L2", "desc": "Python3 解释器", "action": "confirm"},
    "pip": {"level": "L2", "desc": "Python 包管理", "action": "confirm"},
    "pip3": {"level": "L2", "desc": "Python3 包管理", "action": "confirm"},
    "node": {"level": "L2", "desc": "Node.js 运行时", "action": "confirm"},
    "npm": {"level": "L2", "desc": "Node 包管理", "action": "confirm"},
    "npx": {"level": "L2", "desc": "Node 包执行", "action": "confirm"},
    "java": {"level": "L2", "desc": "Java 运行时", "action": "confirm"},
    "javac": {"level": "L2", "desc": "Java 编译器", "action": "confirm"},
    "gcc": {"level": "L2", "desc": "C 编译器", "action": "confirm"},
    "make": {"level": "L2", "desc": "构建工具", "action": "confirm"},
    "cmake": {"level": "L2", "desc": "CMake 构建", "action": "confirm"},
    "cargo": {"level": "L2", "desc": "Rust 包管理", "action": "confirm"},
    "go": {"level": "L2", "desc": "Go 工具链", "action": "confirm"},
    "ruby": {"level": "L2", "desc": "Ruby 解释器", "action": "confirm"},
    "perl": {"level": "L2", "desc": "Perl 解释器", "action": "confirm"},
    "php": {"level": "L2", "desc": "PHP 解释器", "action": "confirm"},
    "bash": {"level": "L2", "desc": "Bash shell", "action": "confirm"},
    "sh": {"level": "L2", "desc": "Shell", "action": "confirm"},
    "source": {"level": "L2", "desc": "执行脚本", "action": "confirm"},
    "ssh": {"level": "L2", "desc": "远程登录", "action": "confirm"},
    "scp": {"level": "L2", "desc": "远程复制", "action": "confirm"},
    "rsync": {"level": "L2", "desc": "远程同步", "action": "confirm"},
    "crontab": {"level": "L2", "desc": "定时任务管理", "action": "confirm"},
    "at": {"level": "L2", "desc": "定时执行", "action": "confirm"},
    "jq": {"level": "L2", "desc": "JSON 处理", "action": "confirm"},
    "yq": {"level": "L2", "desc": "YAML 处理", "action": "confirm"},
    "xmllint": {"level": "L2", "desc": "XML 处理", "action": "confirm"},
    # L3 — 破坏/网络 (destructive/network)
    "rm": {"level": "L3", "desc": "删除文件/目录", "action": "block"},
    "rmdir": {"level": "L3", "desc": "删除空目录", "action": "block"},
    "tar": {"level": "L3", "desc": "归档压缩", "action": "block"},
    "zip": {"level": "L3", "desc": "ZIP 压缩", "action": "audit"},
    "unzip": {"level": "L3", "desc": "ZIP 解压", "action": "audit"},
    "gzip": {"level": "L3", "desc": "GZ 压缩", "action": "audit"},
    "gunzip": {"level": "L3", "desc": "GZ 解压", "action": "audit"},
    "kill": {"level": "L3", "desc": "终止进程", "action": "block"},
    "killall": {"level": "L3", "desc": "按名称终止进程", "action": "block"},
    "pkill": {"level": "L3", "desc": "按模式终止进程", "action": "block"},
    "nohup": {"level": "L3", "desc": "后台运行", "action": "audit"},
    "screen": {"level": "L3", "desc": "终端复用", "action": "audit"},
    "tmux": {"level": "L3", "desc": "终端复用", "action": "audit"},
    "iptables": {"level": "L3", "desc": "防火墙规则", "action": "block"},
    "ufw": {"level": "L3", "desc": "防火墙管理", "action": "block"},
    "nc": {"level": "L3", "desc": "网络调试", "action": "audit"},
    "nmap": {"level": "L3", "desc": "端口扫描", "action": "block"},
    "tcpdump": {"level": "L3", "desc": "抓包分析", "action": "audit"},
    "dd": {"level": "L3", "desc": "磁盘复制", "action": "block"},
    "mkfs": {"level": "L3", "desc": "格式化磁盘", "action": "block"},
    "fdisk": {"level": "L3", "desc": "磁盘分区", "action": "block"},
    "fsck": {"level": "L3", "desc": "磁盘检查", "action": "block"},
    # L4 — 系统管理 (system admin)
    "docker": {"level": "L4", "desc": "容器管理", "action": "block"},
    "docker-compose": {"level": "L4", "desc": "容器编排", "action": "block"},
    "podman": {"level": "L4", "desc": "容器管理", "action": "block"},
    "systemctl": {"level": "L4", "desc": "系统服务管理", "action": "block"},
    "service": {"level": "L4", "desc": "服务管理", "action": "block"},
    "apt": {"level": "L4", "desc": "Debian 包管理", "action": "block"},
    "apt-get": {"level": "L4", "desc": "Debian 包管理", "action": "block"},
    "yum": {"level": "L4", "desc": "RPM 包管理", "action": "block"},
    "dnf": {"level": "L4", "desc": "RPM 包管理", "action": "block"},
    "pacman": {"level": "L4", "desc": "Arch 包管理", "action": "block"},
    "rpm": {"level": "L4", "desc": "RPM 包操作", "action": "block"},
    "dpkg": {"level": "L4", "desc": "Debian 包操作", "action": "block"},
    "snap": {"level": "L4", "desc": "Snap 包管理", "action": "block"},
    "flatpak": {"level": "L4", "desc": "Flatpak 包管理", "action": "block"},
    "reboot": {"level": "L4", "desc": "重启系统", "action": "block"},
    "shutdown": {"level": "L4", "desc": "关机", "action": "block"},
    "halt": {"level": "L4", "desc": "停机", "action": "block"},
    "poweroff": {"level": "L4", "desc": "断电关机", "action": "block"},
    "useradd": {"level": "L4", "desc": "添加用户", "action": "block"},
    "userdel": {"level": "L4", "desc": "删除用户", "action": "block"},
    "groupadd": {"level": "L4", "desc": "添加用户组", "action": "block"},
    "groupdel": {"level": "L4", "desc": "删除用户组", "action": "block"},
    "passwd": {"level": "L4", "desc": "修改密码", "action": "block"},
    "sudo": {"level": "L4", "desc": "提权执行", "action": "block"},
    "su": {"level": "L4", "desc": "切换用户", "action": "block"},
}


def _build_config() -> dict[str, Any]:
    """Build the unified tool_guard.yaml content."""
    config: dict[str, Any] = {
        "version": "1.0.0",
        "description": "Unified tool guard configuration — combines command levels, detection rules, and evasion checks",
        "access_control": {
            "enabled": True,
            "guarded_tools": [],
            "denied_tools": [],
            "custom_rules": [],
            "disabled_rules": [],
        },
        "commands": {},
        "rules": [],
        "evasion_checks": {
            "command_substitution": True,
            "obfuscated_flags": True,
            "backslash_escaped_whitespace": True,
            "backslash_escaped_operators": True,
            "newlines": True,
            "comment_quote_desync": True,
            "quoted_newline": True,
        },
    }

    # ── Commands ──
    for cmd_name, cmd_info in COMMAND_LEVELS.items():
        config["commands"][cmd_name] = {
            "level": cmd_info["level"],
            "desc": cmd_info["desc"],
            "action": cmd_info["action"],
        }

    # ── Rules from dangerous_shell_commands.yaml ──
    rules_path = Path(__file__).parent / "rules" / "dangerous_shell_commands.yaml"
    if rules_path.exists():
        with open(rules_path) as f:
            old_rules = yaml.safe_load(f) or []
        for rule in old_rules:
            new_rule = {
                "id": rule.get("id", ""),
                "tools": rule.get("tools", []),
                "params": rule.get("params", []),
                "category": rule.get("category", ""),
                "severity": rule.get("severity", "MEDIUM"),
                "patterns": rule.get("patterns", []),
                "exclude_patterns": rule.get("exclude_patterns", []),
                "description": rule.get("description", ""),
                "remediation": rule.get("remediation", ""),
                "action": rule.get("action", "block"),
            }
            # Try to link rule to a command
            for cmd_name in COMMAND_LEVELS:
                for pattern in new_rule["patterns"]:
                    if cmd_name in pattern.lower():
                        new_rule["commands"] = [cmd_name]
                        break
                if "commands" in new_rule:
                    break
            if "commands" not in new_rule:
                new_rule["commands"] = []
            config["rules"].append(new_rule)

    return config


def migrate(system_dir: str | None = None) -> Path:
    """Run migration and return the path to the generated file."""
    config = _build_config()

    if system_dir:
        target_dir = Path(system_dir)
    else:
        target_dir = Path(__file__).parent.parent.parent.parent / "system"

    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / "tool_guard.yaml"

    # Backup if exists
    if target_path.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = target_path.with_suffix(f".yaml.bak.{ts}")
        shutil.copy2(target_path, backup)
        print(f"Backed up existing file to {backup}")

    with open(target_path, "w", encoding="utf-8") as f:
        f.write("# Unified Tool Guard Configuration\n")
        f.write(f"# Generated: {datetime.now().isoformat()}\n")
        f.write(f"# Commands: {len(config['commands'])}\n")
        f.write(f"# Rules: {len(config['rules'])}\n")
        f.write(f"# Evasion checks: {len(config['evasion_checks'])}\n\n")
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    print(f"Generated unified config: {target_path}")
    print(f"  Commands: {len(config['commands'])}")
    print(f"  Rules: {len(config['rules'])}")
    print(f"  Evasion checks: {len(config['evasion_checks']['evasion_checks'])}")

    return target_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate to unified tool_guard.yaml")
    parser.add_argument("--system-dir", help="Target system directory path")
    args = parser.parse_args()
    migrate(args.system_dir)


if __name__ == "__main__":
    main()
