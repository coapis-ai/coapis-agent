# -*- coding: utf-8 -*-
"""判断模型解析（一期，v13 第 15 章 D1/D2 拍板：**复用 active_model**）。

判断模型 = 会话当前激活模型，**不新增槽位、零配置成本**。解析直接调用
既有唯一权威入口 ``resolve_chat_model_slot``（用户偏好 → 智能体
active_model → 全局默认），与聊天/多模态判断同源，杜绝"聊天用模型 A、
判断用模型 B"的分裂。

拿不到可用模型时返回 None —— 调用方**必须**降级为「不判断」，绝不因
判断环节让任务卡死（v13 验收标准 5）。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


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
                "[DecisionHub] 激活模型 %s/%s 已不存在，降级不判断",
                provider_id,
                model,
            )
            return None
        # v14 §4.4①：chat 类型硬校验——不是 chat 的模型绝不进判断
        ok, model_type = assert_chat_capable(provider, model)
        if not ok:
            logger.warning(
                "[DecisionHub] 激活模型 %s/%s 类型=%s，不是 chat，"
                "不能当判官（降级不判断，请为该会话配置对话模型）",
                provider_id,
                model,
                model_type,
            )
            return None
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


__all__ = ["assert_chat_capable", "get_judgment_provider_config"]
