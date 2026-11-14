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

    2026-11-09 起委托给 ``providers.provider.is_local_endpoint``，全项目一份
    内网判定。**本判定只用于超时预算，不参与 Key**（小蜜蜂拍板：Key 归提供商层，
    聊天与判官都不预判"有没有 Key"）。
    """
    from ..providers.provider import is_local_endpoint

    return is_local_endpoint(base_url)


def is_ollama_base_url(base_url: Any) -> bool:
    """ollama 的 OpenAI 兼容端点判定（关思考要换 ollama 的键名）。"""
    raw = str(base_url or "").lower()
    return "11434" in raw or "ollama" in raw


def availability_key(provider_id: str, model_id: str) -> str:
    """模型可用性台账 / 能力探测缓存的统一键：``provider_id:model_id``。

    B3（收尾方案 v1 §6.1）：键的拼法以前散在调用方，判官侧根本没有出键的
    地方——两处各拼一套，台账就认不出"哪台模型坏过"。键只在配置组装处
    生成一次，随配置一路带走。
    """
    return f"{str(provider_id or '').strip()}:{str(model_id or '').strip()}"


def judge_capability_ok(
    provider_id: str,
    model_id: str,
    min_prompt_tokens: int = 2048,
) -> tuple[bool, str]:
    """判官能力闸（B3 · 收尾方案 v1 §6.1）。返回 ``(能胜任?, 原因码)``。

    为什么要在判断之前拦：判官的输入是"提示词 + 被判的内容"，几十 KB 的
    计划/工具参数都要塞进去。窗口比这还小的模型必然被截断，上游不报错、
    只给一句读不出结论的话——台账上就是 parse_fail/timeout，看起来像
    "判官不行"，其实是拿错了模型。嵌入模型当判官 9/9 全超时就是这个形状
    （v14 根因），类型闸挡住了那一类，**窗口闸挡的是这一类**，两者正交。

    三查，全部只用已经在手的事实，**不发网络请求**：
    1. chat 类型（复用 :func:`assert_chat_capable`，与既有校验同源）；
    2. 输入窗口：模型自报的 ``max_sequence_length`` ≥ ``min_prompt_tokens``；
    3. 结构化输出：探测缓存里 ``json_mode`` 明确探测为 False 的模型不胜任
       （判官提示词要求 JSON 结论，读不出 JSON 的判官等于没有判官）。

    口径纪律：**未观测 = 放行**。``max_sequence_length`` 为 None（提供商不
    上报）或缓存无记录时不否决——没有证据说它坏就不猜，与模型可用性台账
    "无记录 = ok" 同口径。这一条是灰度安全的前提：闸门打开不会把现有
    判官全灭，只会挡掉有证据不胜任的。
    """
    # 局部导入：providers 层依赖判断中枢的只有这一条单向调用，
    # 顶层互导会成环（gateway → resolver → providers → …）。
    from ..providers.provider_manager import ProviderManager
    from .judge_reasons import NOT_CHAT, PROVIDER_MISSING, SLOT_MODEL_INCAPABLE

    try:
        mgr = ProviderManager.get_instance()
        provider = mgr.get_provider(provider_id) if mgr is not None else None
    except Exception:  # noqa: BLE001 - 读不到管理器＝没有证据，放行
        return True, ""
    if provider is None:
        return False, PROVIDER_MISSING

    ok, _mtype = assert_chat_capable(provider, model_id)
    if not ok:
        return False, NOT_CHAT

    info = None
    for m in getattr(provider, "models", None) or []:
        if getattr(m, "id", None) == model_id:
            info = m
            break
    if info is not None:
        window = getattr(info, "max_sequence_length", None)
        if window is not None:
            try:
                if int(window) < int(min_prompt_tokens):
                    return False, SLOT_MODEL_INCAPABLE
            except (TypeError, ValueError):
                pass

    try:
        from ..providers.model_capability_cache import get_capability_cache

        probed = get_capability_cache().get(
            availability_key(provider_id, model_id), "json_mode", None
        )
    except Exception:  # noqa: BLE001 - 缓存不可用不参与否决
        probed = None
    if probed is False:
        return False, SLOT_MODEL_INCAPABLE

    return True, ""




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
            # B3（收尾方案 v1 §6.1）：可用性台账与探测缓存都按这个键记账，
            # 配置组装处出键，下游不再各拼各的（"谁都能拼、拼得不一样"
            # 就是台账认不出模型的成因）。
            "availability_key": availability_key(provider_id, model),
        }
    except Exception as exc:
        logger.warning("[DecisionHub] 判断模型配置组装失败: %s", exc)
        return None


def _decision_slot_pair() -> tuple[str, str]:
    """读"决策模型"默认槽位 —— 模型管理里的第 6 个槽位（v16 新增）。

    判官模型的家从 ``config/decision_hub.json`` 里的一对字符串迁到模型管理
    的默认槽位体系：与 chat/embedding/rerank/audio/vision 同权，能在模型
    管理页看到、能设默认、复用 chat 的能力校验。

    返回 ``(provider_id, model_id)``；没配、管理器未就绪、读失败都给空串
    （判官不上岗 = 设计内行为，不是错误）。
    """
    try:
        from ..providers.provider_manager import ProviderManager

        mgr = ProviderManager.get_instance()
        if mgr is None:
            return "", ""
        slot = mgr.get_default_models().get_by_type("decision")
        if slot is None:
            return "", ""
        return (
            str(slot.provider_id or "").strip(),
            str(slot.model_id or "").strip(),
        )
    except Exception as exc:  # 槽位读不到 = 没配，判官按规则直判
        logger.debug("[DecisionHub] 决策模型槽位读取失败: %s", exc)
        return "", ""


def _supply_switch_off(hub: Any) -> bool:
    """供给层开关：判官关了就不必有"判官模型配置"这个东西（B1 契约）。

    以前开关只在网关出口处判，供给层（本函数）照旧解析模型——于是每个
    调用方都要自己记得"先问开关"，漏一个就多烧一次模型；实测
    判档/计划/验收三个消费点里有一个没记得问。口径反转成"开关是供给层
    的事"：判官关闭 → 没有供给，调用方拿到的永远是 None，不可能误调。

    认两种键名：``judge_enabled``（调用方传的判断语义开关，判档岗用它）与
    ``enabled``（中枢总开关）。两者任一显式为 False 才算关闭；属性不存在
    不算关闭（配置对象形态多样，缺键 = 未表态）。
    """
    for key in ("judge_enabled", "enabled"):
        value = getattr(hub, key, None)
        if value is not None and not value:
            return True
    return False


def get_judge_provider_config(
    hub: Any = None,
    user_id: str | None = None,
    agent_id: str | None = None,
    out_source: dict | None = None,
) -> Optional[dict[str, Any]]:
    """判官模型解析：只认判官槽位与决策模型槽位，不回落会话激活模型（D-A 拍板）。

    口径反转：v13 定的"判官没配就借用会话激活模型"实测是 4 秒级卡死的主犯。
    dev 台账 184 行真判全是抄激活模型打出来的——判官档位 2000 ms 预算、
    回合 6000 ms 预算全部打在对话模型上（deepseek-v4-flash-bailian），
    结果 超时 105 行、熔断 24 行、预算吃光 61 行，真判率 40.8%、损耗 44%、
    最坏一次 16963 ms。用户口径：「当决策模型不可用，过程中自动忽略」——
    未配置就是没有判官，直接按规则判，不该拿用户的对话模型去赌一次判断。

    解析优先级（v16 D4 拍板，从高到低）：

    1. 智能体级覆盖：``hub`` 由 ``merge_hub_config`` 合并而来（环境变量 →
       数据根 ``config/decision_hub.json`` → 该智能体 ``agent.json`` 的
       ``decision_hub`` 段），所以 ``judge_provider_id``/``judge_model``
       在智能体段里写了就自动压过全局——这一层本来就存在，保持不动。
    2. 全局判官槽位（同一对键，管理台/决策中枢面板写的）。
    3. 决策模型槽位：模型管理里的第 6 个默认槽位 ``default_models.decision``
       （v16 新增，与 chat/embedding/... 同权，是判官模型现在的家）。
    4. 都没有 → None：判官不上岗，各岗按确定性规则直判（设计内行为）。

    槽位里的模型已删除/非 chat → 同样 None（配置坏了也直判，绝不借模型）。
    ``hub.judge_*`` 与决策槽位同时有值时 hub 赢且日志点名，让"我在模型管理
    里选了却不生效"这件事当场可见；管理台保存决策槽位时会清空 hub 那对键。

    ``user_id``/``agent_id`` 形参保留为兼容位（历史签名），不再参与解析。
    """
    # B1 契约（收尾方案 v1 §5）：开关在供给层生效，一处判全局。
    if _supply_switch_off(hub):
        return None
    pid = str(getattr(hub, "judge_provider_id", "") or "").strip()
    model = str(getattr(hub, "judge_model", "") or "").strip()
    source = "judge_slot"
    slot_pid, slot_model = _decision_slot_pair()
    if pid and model:
        # 兼容期：hub 那对历史键优先级更高。两边都有值且指向不同模型时
        # 必须点名——"我在模型管理里选了决策模型却不生效"要当场可见。
        if slot_pid and slot_model and (slot_pid, slot_model) != (pid, model):
            logger.warning(
                "[DecisionHub] 判官模型有两处配置且不一致：判官槽位 %s/%s "
                "压过决策模型槽位 %s/%s（判官槽位是历史兼容位，管理台保存"
                "决策模型时会清空它）",
                pid,
                model,
                slot_pid,
                slot_model,
            )
    elif slot_pid and slot_model:
        pid, model, source = slot_pid, slot_model, "decision_slot"
    if not pid or not model:
        return None
    cfg = build_provider_config(pid, model, out_source, source=source)
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
