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


def get_judgment_provider_config(
    user_id: str | None = None,
    agent_id: str | None = None,
) -> Optional[dict[str, Any]]:
    """解析本次判断使用的模型，返回 model_factory 可用的配置字典。

    ``user_id`` / ``agent_id`` 用于按会话身份解析激活模型；缺省时退化为
    全局默认。返回 None 表示「无可用判断模型」，调用方降级为不判断。
    """
    try:
        from ..app.routers.user_model_prefs import resolve_chat_model_slot
    except Exception as exc:  # pragma: no cover - 导入期防御
        logger.warning("[DecisionHub] 判断模型解析入口不可用: %s", exc)
        return None

    try:
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
        return {
            "provider_id": provider_id,
            "model": model,
            "base_url": str(provider.base_url),
            # 归一化：去掉尾部 '/'，供 f"{api_base}/chat/completions" 拼接
            "api_base": str(provider.base_url).rstrip("/"),
            "api_key": str(provider.api_key),
        }
    except Exception as exc:
        logger.warning("[DecisionHub] 判断模型配置组装失败: %s", exc)
        return None


__all__ = ["get_judgment_provider_config"]
