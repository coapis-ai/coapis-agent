# -*- coding: utf-8 -*-
"""Frozen baseline of the retired legacy rule set (C5).

``rules/dangerous_shell_commands.yaml`` and ``guardians/rule_guardian.py``
were retired in C5 — they were the *second* rule source feeding the *second*
engine, which is how "console switch does nothing" and "builtin-rules always
empty" became possible.  The 28 rules below are the last state of that YAML,
recorded verbatim (id / severity / declared action) so the unified config is
still held to the migration promise *"the legacy set is a subset of the
unified set, never weaker"* without keeping dead files in the tree.

Legacy semantics: ``RuleBasedToolGuardian`` emitted a finding for every
matched rule; the mixin's AUTO mode then required approval for **any**
finding.  ``action`` in the YAML was advisory metadata (``None`` = default,
i.e. the finding blocks in AUTO mode), so the contract encoded here is:

* every legacy id must exist in the unified config;
* unified severity >= legacy severity;
* a rule the legacy engine flagged must map to a blocking unified action
  (``block`` / ``confirm``), never ``allow`` / ``audit``.
"""

#: legacy id -> (severity, declared action in the retired YAML)
LEGACY_RULES: dict[str, tuple[str, str]] = {
    "TOOL_CMD_DANGEROUS_MV": ("MEDIUM", "audit"),
    "TOOL_CMD_FS_DESTRUCTION": ("CRITICAL", "block"),
    "TOOL_CMD_DOS_FORK_BOMB": ("CRITICAL", "block"),
    "TOOL_CMD_PIPE_TO_SHELL": ("CRITICAL", "block"),
    "TOOL_CMD_REVERSE_SHELL": ("CRITICAL", "block"),
    "TOOL_CMD_SYSTEM_TAMPERING": ("HIGH", "block"),
    "TOOL_CMD_UNSAFE_PERMISSIONS": ("HIGH", "block"),
    "TOOL_CMD_OBFUSCATED_EXEC": ("HIGH", "block"),
    "TOOL_CMD_SYSTEM_REBOOT": ("CRITICAL", "block"),
    "TOOL_CMD_SERVICE_RESTART": ("HIGH", "block"),
    "TOOL_CMD_PROCESS_KILL": ("HIGH", "block"),
    "TOOL_CMD_PRIVILEGE_ESCALATION": ("CRITICAL", "block"),
    "TOOL_CMD_IFS_INJECTION": ("HIGH", "block"),
    "TOOL_CMD_CONTROL_CHARS": ("CRITICAL", "block"),
    "TOOL_CMD_UNICODE_WHITESPACE": ("HIGH", "block"),
    "TOOL_CMD_PROC_ENVIRON": ("HIGH", "block"),
    "TOOL_CMD_JQ_SYSTEM": ("HIGH", "block"),
    "TOOL_CMD_JQ_FILE_FLAGS": ("HIGH", "block"),
    "TOOL_CMD_ZSH_DANGEROUS": ("HIGH", "block"),
    "TOOL_CMD_SQL_INJECTION": ("HIGH", "block"),
    "TOOL_CMD_RF_FORCE": ("HIGH", "confirm"),
    "TOOL_CMD_ENV_DUMP": ("LOW", "audit"),
    "TOOL_CMD_CHMOD_RECURSIVE": ("LOW", "audit"),
    "TOOL_CMD_DOCKER_DANGEROUS": ("MEDIUM", "confirm"),
    "TOOL_CMD_PACKAGE_MANAGER": ("MEDIUM", "audit"),
    "TOOL_CMD_DANGEROUS_CP": ("MEDIUM", "confirm"),
    "TOOL_CMD_GIT_DESTRUCTIVE": ("MEDIUM", "confirm"),
    "TOOL_CMD_WGET_CURL_DATA": ("MEDIUM", "confirm"),
}

LEGACY_RULE_IDS: list[str] = list(LEGACY_RULES)

#: Severity ordering used by the "never weaker" comparison.
_SEV_ORDER = {
    "SAFE": 0,
    "INFO": 1,
    "LOW": 2,
    "MEDIUM": 3,
    "HIGH": 4,
    "CRITICAL": 5,
}


def sev_rank(sev: str) -> int:
    return _SEV_ORDER.get(str(sev).upper(), 0)

#: legacy id -> the exact regex list from the retired YAML (frozen verbatim).
#: The differential suite uses these to prove each probe really fires the legacy
#: rule it claims to test: a probe matching no pattern is a fake probe.
LEGACY_PATTERNS: dict[str, list[str]] = {
    "TOOL_CMD_DANGEROUS_MV": [
        '\\bmv\\b',
    ],
    "TOOL_CMD_FS_DESTRUCTION": [
        '\\bmkfs(\\.[a-zA-Z0-9_]+)?\\b',
        '\\bmke2fs\\b',
        '\\bdd\\s+.*of=\\/dev\\/',
        '>\\s*\\/dev\\/(sd[a-z][0-9]*|vd[a-z][0-9]*|nvme\\d+n\\d+(p\\d+)?)',
    ],
    "TOOL_CMD_DOS_FORK_BOMB": [
        ':\\s*\\(\\s*\\)\\s*\\{\\s*:\\s*\\|\\s*:\\s*&\\s*\\}\\s*;\\s*:',
        '\\bkill\\s+-9\\s+(-1\\b|1\\b)',
    ],
    "TOOL_CMD_PIPE_TO_SHELL": [
        '\\b(curl|wget)\\b\\s+.*\\|.*\\b(bash|sh|zsh|ash|dash)\\b',
    ],
    "TOOL_CMD_REVERSE_SHELL": [
        '\\/dev\\/(tcp|udp)\\/',
        '\\bnc\\s+.*-e\\s*\\S+',
        '\\bncat\\s+.*-e\\s*\\S+',
        '\\bsocat\\s+.*EXEC:',
    ],
    "TOOL_CMD_SYSTEM_TAMPERING": [
        '\\bcrontab\\b',
        '\\bauthorized_keys\\b',
        '\\/etc\\/sudoers',
        '\\/etc\\/crontab',
    ],
    "TOOL_CMD_UNSAFE_PERMISSIONS": [
        '\\bchmod\\s+-[a-zA-Z]*R[a-zA-Z]*\\s+(777|a\\+rwx)\\s+\\/',
        '\\bchattr\\s+\\+i',
    ],
    "TOOL_CMD_OBFUSCATED_EXEC": [
        '\\bbase64\\s+(-d|--decode)\\s*\\|\\s*\\b(bash|sh|zsh)\\b',
    ],
    "TOOL_CMD_SYSTEM_REBOOT": [
        '\\b(reboot|shutdown|halt|poweroff)\\b',
        '\\binit\\s+(0|6)\\b',
        '\\btelinit\\s+(0|6)\\b',
        '\\bShutdown-Computer\\b',
        '\\bRestart-Computer\\b',
    ],
    "TOOL_CMD_SERVICE_RESTART": [
        '\\bsystemctl\\s+(restart|stop|start|reload|kill)\\b',
        '\\bservice\\s+\\S+\\s+(restart|stop|start|reload)\\b',
        '\\b(sc|net)\\s+(start|stop|restart)\\b',
        '\\blaunchctl\\s+(load|unload|stop|start|kickstart|kill)\\b',
        '\\brc-service\\s+(restart|stop|start)\\b',
    ],
    "TOOL_CMD_PROCESS_KILL": [
        '\\b(pkill|killall)\\b',
        '\\bkill\\s+(-(9|KILL|15|TERM|1|HUP|2|INT)\\s+)?[^-\\s]',
        '\\btaskkill\\s+\\/F\\b',
        '\\bStop-Process\\b.*-Force\\b',
    ],
    "TOOL_CMD_PRIVILEGE_ESCALATION": [
        '\\bsudo\\s+',
        '\\bsu\\b',
        '\\bdoas\\s+',
        '\\bpkexec\\b',
        '\\brunas\\s+\\/user:',
    ],
    "TOOL_CMD_IFS_INJECTION": [
        '\\$IFS(?![A-Za-z0-9_])',
        '\\$\\{[^}]*IFS',
    ],
    "TOOL_CMD_CONTROL_CHARS": [
        '[\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f\\x7f]',
    ],
    "TOOL_CMD_UNICODE_WHITESPACE": [
        '[\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000\\ufeff]',
    ],
    "TOOL_CMD_PROC_ENVIRON": [
        '\\/proc\\/(?:self|\\d+)\\/environ(?:\\b|$)',
    ],
    "TOOL_CMD_JQ_SYSTEM": [
        '\\bjq\\b.*\\bsystem\\s*\\(',
    ],
    "TOOL_CMD_JQ_FILE_FLAGS": [
        '\\bjq\\b.*(?:\\s-f\\b|\\s--from-file\\b|\\s--rawfile\\b|\\s--slurpfile\\b|\\s-L\\b|\\s--library-path\\b)',
    ],
    "TOOL_CMD_ZSH_DANGEROUS": [
        '\\bzmodload\\b',
        '\\bemulate\\b(?:\\s+-\\S+)*\\s+-c\\b',
        '\\b(sysopen|sysread|syswrite|sysseek)\\b',
        '\\b(zpty|ztcp|zsocket)\\b',
        '\\bzf_(rm|mv|ln|chmod|chown|mkdir|rmdir|chgrp)\\b',
        '\\bfc\\b.*\\s-\\S*e',
    ],
    "TOOL_CMD_SQL_INJECTION": [
        '\\bDROP\\s+TABLE\\b',
        '\\bDROP\\s+DATABASE\\b',
        '\\bTRUNCATE\\s+TABLE\\b',
        '\\bDELETE\\s+FROM\\b.*\\bWHERE\\s+1\\s*=\\s*1',
    ],
    "TOOL_CMD_RF_FORCE": [
        '\\brm\\s+.*-rf\\b',
        '\\brm\\s+.*-fr\\b',
    ],
    "TOOL_CMD_ENV_DUMP": [
        '\\benv\\b\\s*$',
        '\\bprintenv\\b\\s*$',
    ],
    "TOOL_CMD_CHMOD_RECURSIVE": [
        '\\bchmod\\s+.*-R\\s+(777|a\\+rwx)\\b',
    ],
    "TOOL_CMD_DOCKER_DANGEROUS": [
        '\\bdocker\\s+(rm|rmi|kill|stop|pause|unpause|rename|update)\\b',
        '\\bdocker\\s+container\\s+(rm|kill|stop|pause|unpause)\\b',
        '\\bdocker\\s+volume\\s+(rm|prune)\\b',
        '\\bdocker\\s+network\\s+(rm|disconnect)\\b',
        '\\bdocker\\s+system\\s+prune\\b',
        '\\bdocker\\s+compose\\s+(down|rm)\\b',
    ],
    "TOOL_CMD_PACKAGE_MANAGER": [
        '\\bapt(-get)?\\s+(install|remove|purge|autoremove|upgrade|dist-upgrade)\\b',
        '\\byum\\s+(install|remove|erase|autoremove|update|upgrade)\\b',
        '\\bdnf\\s+(install|remove|autoremove|update|upgrade)\\b',
        '\\bpip3?\\s+install\\b',
        '\\bnpm\\s+(install|i)\\b',
        '\\bgem\\s+install\\b',
    ],
    "TOOL_CMD_DANGEROUS_CP": [
        '\\bcp\\s+.*(-r|--recursive)\\b.*/etc/',
        '\\bcp\\s+.*/etc/\\s+',
        '\\bcp\\s+.*/usr/',
        '\\bcp\\s+.*\\s+/bin/',
        '\\bcp\\s+.*\\s+/sbin/',
    ],
    "TOOL_CMD_GIT_DESTRUCTIVE": [
        '\\bgit\\s+push\\b',
        '\\bgit\\s+reset\\s+--hard\\b',
        '\\bgit\\s+clean\\s+-f\\b',
        '\\bgit\\s+branch\\s+-D\\b',
        '\\bgit\\s+checkout\\s+--force\\b',
    ],
    "TOOL_CMD_WGET_CURL_DATA": [
        '\\bcurl\\s+.*(-d|--data|--data-raw|--data-binary)\\b',
        '\\bwget\\s+.*--post-file\\b',
        '\\bwget\\s+.*--body-file\\b',
        '\\bwget\\s+.*--post-data\\b',
    ],
}
