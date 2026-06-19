# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
# Licensed under the Apache License, Version 2.0
"""Scene intent classifier — lightweight keyword-based scene detection.

Determines which scene (coding/ops/data/security/ai/collaboration) a user message
targets, enabling scene-based dynamic tool injection.
No LLM required — pure keyword matching.
"""
from __future__ import annotations
import re
from typing import Optional


SCENE_KEYWORDS: dict[str, list[str]] = {
    "coding": [
        # English
        "code", "function", "class", "debug", "test", "format", "review",
        "commit", "pr", "merge", "branch", "refactor", "lint", "prettier",
        "black", "python", "javascript", "typescript", "rust", "golang",
        "compile", "build", "makefile", "dockerfile", "pip", "npm",
        "import", "module", "package", "dependency", "vulnerability",
        "syntax", "error", "exception", "stacktrace", "traceback",
        "regex", "ast", "parse", "tokenize",
        # Chinese
        "代码", "函数", "类", "调试", "测试", "格式化", "审查", "提交",
        "合并", "分支", "重构", "编译", "构建", "依赖", "语法",
        "错误", "异常", "正则", "解析", "模块", "包",
    ],
    "ops": [
        "deploy", "docker", "container", "k8s", "kubernetes", "monitor",
        "performance", "latency", "uptime", "health", "log", "cron",
        "schedule", "restart", "scale", "nginx", "redis", "ssh",
        "server", "process", "daemon", "systemd", "systemctl",
        "部署", "容器", "监控", "性能", "延迟", "日志", "定时",
        "重启", "扩展", "服务", "进程", "系统", "运维",
    ],
    "data": [
        "csv", "json", "excel", "xlsx", "database", "sqlite", "mysql",
        "postgres", "redis", "cache", "queue", "etl", "pipeline",
        "data", "analytics", "statistics", "chart", "graph", "table",
        "archive", "zip", "tar", "compress", "extract",
        "数据", "表格", "数据库", "缓存", "队列", "统计", "图表",
        "分析", "压缩", "归档", "导出", "导入",
    ],
    "security": [
        "secret", "password", "token", "api_key", "credential", "encrypt",
        "decrypt", "hash", "ssl", "tls", "cert", "firewall", "vulnerability",
        "audit", "permission", "role", "access", "auth", "oauth",
        "scan", "pentest", "injection", "xss", "csrf",
        "密钥", "密码", "加密", "解密", "哈希", "证书", "漏洞",
        "审计", "权限", "角色", "认证", "扫描", "注入",
    ],
    "ai": [
        "llm", "gpt", "claude", "gemini", "openai", "anthropic",
        "prompt", "embedding", "vector", "rag", "retrieval", "knowledge",
        "training", "fine-tune", "model", "inference", "token",
        "image", "diffusion", "stable", "midjourney", "dall-e",
        "speech", "tts", "stt", "voice", "transcription",
        "智能", "大模型", "向量", "知识库", "检索", "提示词",
        "训练", "推理", "图像", "语音", "生成",
    ],
    "collaboration": [
        "notify", "notification", "email", "slack", "webhook", "sms",
        "share", "team", "group", "collaborate", "assign", "delegate",
        "workflow", "pipeline", "orchestrate", "coordinate",
        "通知", "邮件", "消息", "共享", "团队", "协作",
        "分发", "工作流", "编排", "协调",
    ],
}


def classify_scene(message: str) -> Optional[str]:
    """Classify a user message into a scene using keyword matching.

    Args:
        message: The user's message text

    Returns:
        The best matching scene name, or None if no strong match.
    """
    if not message or not message.strip():
        return None

    msg_lower = message.lower()
    scores: dict[str, int] = {}

    for scene, keywords in SCENE_KEYWORDS.items():
        score = 0
        for kw in keywords:
            # Use word boundary for English, substring for Chinese
            if re.search(r'[\u4e00-\u9fff]', kw):
                if kw in msg_lower:
                    score += 2  # Chinese keywords get higher weight
            else:
                if re.search(r'\b' + re.escape(kw) + r'\b', msg_lower):
                    score += 1
        scores[scene] = score

    if not scores:
        return None

    best_scene = max(scores, key=scores.get)
    best_score = scores[best_scene]

    # Require minimum score to avoid false positives
    if best_score < 2:
        return None

    return best_scene


def classify_with_confidence(message: str) -> dict:
    """Classify with confidence score.

    Returns:
        {"scene": str|None, "confidence": float, "scores": dict}
    """
    if not message or not message.strip():
        return {"scene": None, "confidence": 0.0, "scores": {}}

    msg_lower = message.lower()
    scores: dict[str, int] = {}

    for scene, keywords in SCENE_KEYWORDS.items():
        score = 0
        for kw in keywords:
            if re.search(r'[\u4e00-\u9fff]', kw):
                if kw in msg_lower:
                    score += 2
            else:
                if re.search(r'\b' + re.escape(kw) + r'\b', msg_lower):
                    score += 1
        scores[scene] = score

    total = sum(scores.values())
    if total == 0:
        return {"scene": None, "confidence": 0.0, "scores": scores}

    best_scene = max(scores, key=scores.get)
    best_score = scores[best_scene]
    confidence = best_score / total if total > 0 else 0.0

    if best_score < 2:
        return {"scene": None, "confidence": confidence, "scores": scores}

    return {"scene": best_scene, "confidence": round(confidence, 3), "scores": scores}
