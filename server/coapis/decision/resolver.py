# -*- coding: utf-8 -*-
"""判断模型解析（一期，v13 第 15 章 D1/D2 拍板：**复用 active_model**）。

判断模型 = 会话当前激活模型，**不新增槽位、零配置成本**。解析直接调用
既有唯一权威入口 ``resolve_chat_model_slot``（用户偏好 → 智能体
active_model → 全局默认），与聊天/多模态判断同源，杜绝"聊天用模型 A、
判断用模型 B"的分裂。

v15 D1=A 补的例外： hub 配置里 ``judge_provider_id`` + ``judge_model`` 都
非空时，判官**固定**用该模型（建议轻量非思考模型），不再跟随会话激活
模型——会话模型差，判官跟着差（实测 dev 的激活模型是 Q3 思考模型，判档
要 5~15 秒）。固定模型解析失败时回落激活模型链，绝不因判官让任务卡死。

拿不到可用模型时返回 None —— 调用方**必须**降级为「不判断」，绝不因
判断环节让任务卡死（v13 验收标准 5）。
"""
from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# 本地链路判定（F1 自适应超时的依据）：这些主机 + 常见推理端口视为本地。
_LOCAL_HOSTS = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    "host.docker.internal",
    "host.containers.internal",
    "host.minikube.internal",
}
_LOCAL_PORTS = (11434, 8080, 8081, 8082, 8000)  # ollama / vLLM / llama.cpp


def is_local_base_url(base_url: Any) -> bool:
    """``base_url`` 是否指向本地/内网推理服务。

    本地链路（ollama、vLLM）跑思考模型要 5~15 秒，远端 API 通常 1~3 秒。
    判官超时按链路给预算，靠的就是这个判定。
    """
    raw = str(base_url or "").strip()
    if not raw:
        return False
    parsed = urlparse(raw if "//" in raw else f"//{raw}")
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    if host in _LOCAL_HOSTS:
        return True
    if host.startswith("127."):
        return True
    # RFC1918 内网段 + 链路本地：小蜜蜂的 vLLM 跑在局域网机器上
    parts = host.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        a, b = int(parts[0]), int(parts[1])
        if a in (10, 127) or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168):
            return True
    if host.endswith(".local") or host.endswith(".internal"):
        return True
    return parsed.port in _LOCAL_PORTS


def is_ollama_base_url(base_url: Any) -> bool:
    """ollama 的 OpenAI 兼容端点判定（关思考要换 ollama 的键名）。"""
    raw = str(base_url or "").lower()
    return "11434" in raw or "ollama" in raw



def assert_chat_capable(provider: Any, model_id: str) -> tuple[bool, str]:
    """硬校验（v14 §4.4①）：候选模型必须是 **chat** 类型。

    类型以 ``ModelInfo.model_type`` 为准（用户在「模型管理」里的显式分类），
    缺失时用既有的 ``infer_model_type`` 按名字兜底推断。

    这一道校验是"嵌入模型当判官"的根治点：qwen3-embedding 这类模型在
    OpenAI 兼容接口上**不会报错**，只是永远读不出结论——它必须在进入判断
    之前就被挡掉，而不是靠提示词里写"你不是判官"。
    """
    try:
        from ..providers.model_type import infer_model_type
    except Exception:  # pragma: no cover - 导入期防御
        infer_model_type = None

    for m in getattr(provider, "models", None) or []:
        if getattr(m, "id", None) != model_id:
            continue
        declared = getattr(m, "model_type", None)
        if declared:
            return str(declared) == "chat", str(declared)
        if infer_model_type is not None:
            inferred = str(infer_model_type(m.id, getattr(m, "name", None)) or "chat")
            return inferred == "chat", f"{inferred}(推断)"
        return True, "chat(未知类型默认)"

    # 模型不在清单里：只按名字推断，推成非 chat 就挡掉
    if infer_model_type is not None:
        inferred = str(infer_model_type(model_id) or "chat")
        return inferred == "chat", f"{inferred}(推断)"
    return True, "chat(未知类型默认)"


def get_judgment_provider_config(
    user_id: str | None = None,
    agent_id: str | None = None,
    out_source: dict | None = None,
) -> Optional[dict[str, Any]]:
    """解析本次判断使用的模型，返回 model_factory 可用的配置字典。

    ``user_id`` / ``agent_id`` 用于按会话身份解析激活模型；缺省时退化为
    全局默认。返回 None 表示「无可用判断模型」，调用方降级为不判断。

    ``out_source`` 传入 dict 时写入 ``source`` = ``user_pref`` /
    ``agent_default`` / ``global_default``，供台账记命中层（v14 §4.4②）。
    """
    try:
        from ..app.routers.user_model_prefs import resolve_chat_model_slot
    except Exception as exc:  # pragma: no cover - 导入期防御
        logger.warning("[DecisionHub] 判断模型解析入口不可用: %s", exc)
        return None

    try:
        try:
            slot = resolve_chat_model_slot(
                user_id or None,
                agent_id,
                out_source=out_source,
            )
        except TypeError:
            # 兼容旧签名/测试桩：没有 out_source 形参时按位置调用
            slot = resolve_chat_model_slot(user_id or None, agent_id)
    except Exception as exc:
        logger.warning("[DecisionHub] 激活模型解析异常（降级不判断）: %s", exc)
        return None

    if not slot:
        return None

    provider_id, model = slot
    if not provider_id or not model:
        return None
    return build_provider_config(
        provider_id,
        model,
        out_source,
        source=str((out_source or {}).get("source") or "agent_default"),
    )


def build_provider_config(
    provider_id: str,
    model: str,
    out_source: dict | None = None,
    *,
    source: str = "agent_default",
) -> Optional[dict[str, Any]]:
    """按 provider_id/model 组装判断模型配置；不合格返回 None。

    硬校验两件事：模型真实存在、类型必须是 chat（v14 §4.4①）。
    """
    try:
        from ..providers.provider_manager import ProviderManager

        provider = ProviderManager.get_instance().get_provider(provider_id)
        if provider is None:
            return None
        # 模型必须真实存在（用户删掉模型后偏好会变陈旧）
        try:
            available = provider.list_models()
        except Exception:
            available = []
        if available and model not in available:
            logger.warning(
                "[DecisionHub] 判断模型 %s/%s 已不存在，降级不判断",
                provider_id,
                model,
            )
            return None
        # v14 §4.4①：chat 类型硬校验——不是 chat 的模型绝不进判断
        ok, model_type = assert_chat_capable(provider, model)
        if not ok:
            logger.warning(
                "[DecisionHub] 判断模型 %s/%s 类型=%s，不是 chat，"
                "不能当判官（降级不判断，请为该会话配置对话模型）",
                provider_id,
                model,
                model_type,
            )
            return None
        if out_source is not None:
            out_source["source"] = source
        return {
            "provider_id": provider_id,
            "model": model,
            "base_url": str(provider.base_url),
            # 归一化：去掉尾部 '/'，供 f"{api_base}/chat/completions" 拼接
            "api_base": str(provider.base_url).rstrip("/"),
            "api_key": str(provider.api_key),
            "model_type": model_type,
        }
    except Exception as exc:
        logger.warning("[DecisionHub] 判断模型配置组装失败: %s", exc)
        return None


def get_judge_provider_config(
    hub: Any = None,
    user_id: str | None = None,
    agent_id: str | None = None,
    out_source: dict | None = None,
) -> Optional[dict[str, Any]]:
    """判官模型解析：**只认判官槽位，不回落会话激活模型**（D-A 2026-11-05 拍板）。

    口径反转：v13 定的"判官没配就借用会话激活模型"实测是 4 秒级卡死的主犯。
    dev 台账 184 行真判全是抄激活模型打出来的——判官档位 2000 ms 预算、
    回合 6000 ms 预算全部打在对话模型上（deepseek-v4-flash-bailian），
    结果 超时 105 行、熔断 24 行、预算吃光 61 行，真判率 40.8%、损耗 44%、
    最坏一次 16963 ms。用户口径：「当决策模型不可用，过程中自动忽略」——
    未配置就是没有判官，直接按规则判，不该拿用户的对话模型去赌一次判断。

    ``judge_provider_id`` + ``judge_model`` 任一为空 → None（判官不上岗）；
    配了但模型已删除/非 chat → None（配置坏了也直判，不借模型）。

    ``user_id``/``agent_id`` 形参保留为兼容位（历史签名），不再参与解析。
    """
    pid = str(getattr(hub, "judge_provider_id", "") or "").strip()
    model = str(getattr(hub, "judge_model", "") or "").strip()
    if not pid or not model:
        return None
    cfg = build_provider_config(pid, model, out_source, source="judge_slot")
    if cfg is None:
        logger.warning(
            "[DecisionHub] 判官槽位里的模型 %s/%s 不可用（已删除/非 chat），"
            "判官不上岗，按规则直判",
            pid,
            model,
        )
    return cfg


__all__ = [
    "assert_chat_capable",
    "build_provider_config",
    "get_judge_provider_config",
    "get_judgment_provider_config",
    "is_local_base_url",
    "is_ollama_base_url",
]
