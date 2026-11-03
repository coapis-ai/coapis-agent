# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, version 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""思考形状家族 —— 全系统唯一的「厂商/端点 → 思考参数形状」映射（v14 R1）。

**为什么放在 foundation**：这张表有两个消费者——

1. 对话主链下发档位：:mod:`coapis.agents.utils.thinking_budget`
2. 判官自己关/开思考：:mod:`coapis.decision.gateway`

判官与主链的模型来自**同一份模型配置**：主链能用的形状，判官就能用；判官也绝不
用主链不认的私有键位。原先两处各抄一张表（判官只按 provider_type 查表），代价
写在 dev 台账里——判官模型 ``provider_type="deepseek"`` +
``base_url="https://api.deepseek.com/v1"`` 三种形态全不命中 → 返回空 → 思考根本
没关 → 单次 12~18 秒，击穿软阈值并连吃熔断（台账 24 行 ``breaker_open``）。
同一轮里主链按端点判定生效、判官按端点判定失效，就是分表抄写的直接后果。

放在 foundation 而不是 decision 的理由：本模块被**智能体层**顶层导入，而
``coapis.decision/__init__`` 会连带拉起 providers → app 路由链——把一张纯字符串
表挂在会拉起整棵应用树的包上，等于让最底层模块依赖最上层（实测就是这么炸的）。
foundation 只 import 标准库，是唯一安全的家。依赖方向：
``agents → foundation``、``decision → foundation`` 都合法；
中枢**不得**反向 import 智能体层（静态检查
``test_decision_package_does_not_import_agents`` 把关）。

本模块保持**纯函数**：不 import providers/agents/app，只吃字符串参数。
认不出厂形一律返回 :data:`FAMILY_NONE` —— 宁可不注入思考参数，也不猜键位：
猜出来的键位只会变成上游 400（真模型打挂 = 整轮聊天 500）。
"""

from __future__ import annotations

from typing import Any, Dict, Tuple
from urllib.parse import urlparse

# ------------------------------------------------------------------ #
# 形状家族
# ------------------------------------------------------------------ #

FAMILY_CHAT_TEMPLATE = "chat_template"        # 顶层 chat_template_kwargs（本机推理服务）
FAMILY_ENABLE_THINKING = "enable_thinking"    # 顶层 enable_thinking [+ thinking_budget]
FAMILY_REASONING_EFFORT = "reasoning_effort"  # 顶层 reasoning_effort（OpenAI 系 o 系列）
FAMILY_ANTHROPIC = "anthropic"                # model_attrs.thinking 对象
FAMILY_GEMINI = "gemini"                      # model_attrs.thinking_config
FAMILY_NONE = "none"                          # 认不出厂形：不注入任何思考参数

FAMILIES = (
    FAMILY_CHAT_TEMPLATE,
    FAMILY_ENABLE_THINKING,
    FAMILY_REASONING_EFFORT,
    FAMILY_ANTHROPIC,
    FAMILY_GEMINI,
    FAMILY_NONE,
)

# provider_type 级形状
_CHAT_TEMPLATE_PROVIDERS = frozenset(
    {"ollama", "vllm", "sglang", "lmstudio", "local", "local_file"},
)
_ENABLE_THINKING_PROVIDERS = frozenset(
    {
        "dashscope",
        "dashscope_compatible",
        "aliyun",
        "deepseek",
        "moonshot",
        "xai",
        "zai",
        "einstein",
        "alienchat",
    },
)
_REASONING_EFFORT_PROVIDERS = frozenset(
    {"openai", "darkai", "openai_compatible", "compatible"},
)
_ANTHROPIC_PROVIDERS = frozenset({"anthropic"})
_GEMINI_PROVIDERS = frozenset({"gemini"})

# 端点级形状：provider_type 不可靠时的唯一依据。同一个 ``provider_type="openai"``
# 底下，DashScope 兼容口要顶层 enable_thinking，OpenAI 官方要 reasoning_effort，
# 本机 Ollama 要 chat_template_kwargs——只按 provider_type 查表必有一方错。
_HOST_CHAT_TEMPLATE = frozenset({"127.0.0.1", "localhost", "0.0.0.0", "::1"})
_HOST_ENABLE_THINKING = frozenset(
    {
        "dashscope.aliyuncs.com",
        "coding.dashscope.aliyuncs.com",
        "api.deepseek.com",
        "api.moonshot.cn",
        "api.x.ai",
        "open.bigmodel.cn",
        "api.gptsapi.net",
        "api.darkai.cn",
        "darkai.cn",
    },
)
_OPENAI_OFFICIAL_HOSTS = frozenset({"api.openai.com"})
_OLLAMA_PORT = ":11434"

#: Ollama 的思考是开关 + 预算，不是 OpenAI 的四档：minimal 落到 low
_EFFORT_TO_OLLAMA = {"minimal": "low", "low": "low", "medium": "medium", "high": "high"}


def host_of(base_url: Any) -> str:
    """base_url 的主机名（小写、去端口、去 userinfo）。取不到返回空串。"""
    try:
        netloc = urlparse(str(base_url or "").strip()).netloc
        return netloc.split("@")[-1].split(":")[0].lower()
    except Exception:  # noqa: BLE001 - 解析不了就当没有端点
        return ""


def shape_family(
    provider_type: Any = "",
    base_url: Any = "",
    provider_id: Any = "",
) -> str:
    """厂商/端点 → 思考参数形状家族。**全系统唯一**映射处（主链与判官同源）。

    判定优先级：**端点 > provider_type > provider_id**。
    ``provider_type="openai"`` 底下既可能是 DashScope 兼容口（顶层
    ``enable_thinking``），也可能是 OpenAI 官方（``reasoning_effort``），只按
    provider_type 查表必然有一方错。provider_id 只作兜底（id 里带厂商名）。

    三者都认不出 → :data:`FAMILY_NONE`：调用方不注入任何思考参数（宁可不关
    思考，也不猜键位——猜出来的键位只会变成上游 400）。
    """
    host = host_of(base_url)
    pt = str(provider_type or "").strip().lower()
    pid = str(provider_id or "").strip().lower()
    url = str(base_url or "")

    if host in _OPENAI_OFFICIAL_HOSTS:
        # OpenAI 官方口：只认 reasoning_effort，未知顶层键一律被拒绝（400）。
        return FAMILY_REASONING_EFFORT
    if host in _HOST_ENABLE_THINKING:
        return FAMILY_ENABLE_THINKING
    if host in _HOST_CHAT_TEMPLATE or _OLLAMA_PORT in url:
        # 本机推理服务（含局域网地址的 Ollama）：顶层 chat_template_kwargs。
        return FAMILY_CHAT_TEMPLATE

    if pt in _CHAT_TEMPLATE_PROVIDERS:
        return FAMILY_CHAT_TEMPLATE
    if pt in _ENABLE_THINKING_PROVIDERS:
        return FAMILY_ENABLE_THINKING
    if pt in _REASONING_EFFORT_PROVIDERS or "openai" in pt:
        return FAMILY_REASONING_EFFORT
    if pt in _ANTHROPIC_PROVIDERS or "anthropic" in pt:
        return FAMILY_ANTHROPIC
    if pt in _GEMINI_PROVIDERS or "gemini" in pt:
        return FAMILY_GEMINI
    if "ollama" in pid:
        return FAMILY_CHAT_TEMPLATE
    if "dashscope" in pid or "deepseek" in pid:
        return FAMILY_ENABLE_THINKING
    return FAMILY_NONE


def thinking_request_kwargs(
    provider_type: Any = "",
    base_url: Any = "",
    provider_id: Any = "",
    thinking: bool = False,
) -> Dict[str, Any]:
    """按厂形给出「这一行的思考开/关」**请求体参数**（判官用，与主链同一张表）。

    - ``thinking=False`` 关思考；``thinking=True`` 显式开思考（验收岗用——判官
      模型平时按行关着省时间，验收判断需要推理，故单独开）。
    - 厂形认不出 → 返回空字典，调用方自行兜底（绝不猜键位）。

    OpenAI 系（:data:`FAMILY_REASONING_EFFORT`）没有「关思考」这个开关（只有
    ``reasoning_effort`` 档位），故返回空——猜一个键位只会变成上游 400。
    """
    fam = shape_family(provider_type, base_url, provider_id)
    on = bool(thinking)
    if fam == FAMILY_ENABLE_THINKING:
        return {"enable_thinking": on}
    if fam == FAMILY_CHAT_TEMPLATE:
        return {"chat_template_kwargs": {"enable_thinking": on}}
    return {}


def family_request_kwargs(
    family: str,
    budget: int,
    effort: str,
    reasoning_effort: str,
) -> Tuple[Dict[str, Any], Dict[str, Any], str]:
    """主链下发用：把（厂形 + 思考开支）翻成 ``(generate_kwargs, model_attrs, effort)``。

    与 :func:`thinking_request_kwargs` 同表同键位，只是主链带预算数字、判官只要开关。
    返回的 ``reasoning_effort`` 已按厂形修正（Ollama 没有四档，minimal 落 low）。
    """
    generate_kwargs: Dict[str, Any] = {}
    model_attrs: Dict[str, Any] = {}
    effort_out = reasoning_effort
    budget = int(budget or 0)

    if family == FAMILY_CHAT_TEMPLATE:
        # 本机推理服务（Ollama/vLLM/SGLang）：顶层 chat_template_kwargs，预算也进
        # 嵌套字典（顶层塞未知字段会被适配器拒绝）。
        kwargs: Dict[str, Any] = {"enable_thinking": budget > 0}
        if budget > 0:
            kwargs["thinking_budget"] = budget
        generate_kwargs["chat_template_kwargs"] = kwargs
        effort_out = _EFFORT_TO_OLLAMA.get(reasoning_effort, reasoning_effort)
    elif family == FAMILY_ENABLE_THINKING:
        # 顶层 enable_thinking[+thinking_budget]（DashScope 兼容口 / DeepSeek 官方）。
        generate_kwargs["enable_thinking"] = budget > 0
        if budget > 0:
            generate_kwargs["thinking_budget"] = budget
    elif family == FAMILY_ANTHROPIC:
        model_attrs["thinking"] = (
            {"type": "enabled", "budget_tokens": max(1024, min(budget, 128000))}
            if budget > 0
            else {"type": "disabled"}
        )
    elif family == FAMILY_GEMINI:
        model_attrs["thinking_config"] = {
            "thinking_budget": max(0, budget),
            "include_thoughts": budget > 0,
        }
    # FAMILY_REASONING_EFFORT / FAMILY_NONE：只带 reasoning_effort，不发形状键
    # （官方 OpenAI 发未知键会 400；认不出的 provider 宁可不关思考，不能打挂主链）。
    return generate_kwargs, model_attrs, effort_out


__all__ = [
    "FAMILIES",
    "FAMILY_ANTHROPIC",
    "FAMILY_CHAT_TEMPLATE",
    "FAMILY_ENABLE_THINKING",
    "FAMILY_GEMINI",
    "FAMILY_NONE",
    "FAMILY_REASONING_EFFORT",
    "family_request_kwargs",
    "host_of",
    "shape_family",
    "thinking_request_kwargs",
]
