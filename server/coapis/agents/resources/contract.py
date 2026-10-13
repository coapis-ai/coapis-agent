# -*- coding: utf-8 -*-
"""资源契约 · 消费面（§5.2 冻结签名，实现不得增删参数）。

**两套语义，方向冻结**（见 ``tech_docs/资源契约R1-闸门0-接口冻结清单_20261012.md``）：

* 清单面 ``ResourceLedger``（已落地）= 权威真相源：资源是什么、在哪、谁引用、什么状态。
* 消费面 ``ResourceAdapter``（本文件）= **只读**清单面，绝不改写。

智能体的能力体现在**路由判断**：先 ``discover()`` 了解有什么，再选对资源面 ``search()``，
最后 ``fetch()`` 取内容。KB 只是其中一个适配器（企业版启用，社区版自动缺席）。

签名冻结（与方案文档 A3.3 一致，不得改动）::

    class ResourceAdapter(ABC):
        name: str
        async def discover(self) -> list[ResourceMeta]
        async def search(self, query: str, limit: int = 10) -> list[Hit]
        async def fetch(self, ref) -> Content

纪律（与 ``ResourceLedger`` 一致）：**fire-and-forget**——适配器任何一层都不得抛出
异常。检索面坏了绝不能把消息链路带崩。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any

#: 单次 fetch 返回的最大字符数。取内容是为了让模型能读，不是为了让模型转储。
MAX_FETCH_CHARS = 6000

#: discover() 单次最多返回多少条。发现面是导航，不是全量导出。
MAX_DISCOVER_ITEMS = 200

#: FS 补扫（台账未覆盖的历史文件）最多扫多少个文件。
MAX_FS_SCAN_ITEMS = 500


@dataclass
class ResourceMeta:
    """一个资源的描述符。``ref`` 是 ``fetch()`` 的句柄，由适配器自定义。"""

    kind: str          # file | db | kb | mcp | web
    ref: str           # 适配器内唯一的资源句柄
    title: str
    summary: str = ""
    status: str = ""
    owner_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Hit:
    """检索命中。``score`` 归一到 0..1，跨适配器可比较。"""

    meta: ResourceMeta
    score: float
    snippet: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.meta.kind,
            "ref": self.meta.ref,
            "title": self.meta.title,
            "score": round(self.score, 3),
            "snippet": self.snippet,
            "status": self.meta.status,
            "owner_id": self.meta.owner_id,
            "summary": self.meta.summary,
            "extra": self.meta.extra,
        }


@dataclass
class Content:
    """``fetch()`` 的返回体。"""

    kind: str
    ref: str
    text: str
    truncated: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "ref": self.ref,
            "text": self.text,
            "truncated": self.truncated,
            "meta": self.meta,
        }


def score_match(query: str, text: str) -> float:
    """归一化匹配分：整串命中 > CJK 二元组重叠 > 词元重叠。

    中文查询按空格切词是无效的（``"季度报表"`` 切成一个词），所以补 CJK
    bigram 重叠；这比"整串包含"更宽容，能捞到 ``报表`` 命中 ``季度报表模板``。
    """
    q = (query or "").strip().lower()
    t = (text or "").lower()
    if not q or not t:
        return 0.0

    if q in t:
        # 位置权重：越靠前越像标题命中
        pos = t.index(q)
        return round(1.0 - 0.30 * pos / max(len(t), 1), 4)

    # CJK bigram 重叠（中文场景的主力）
    bigrams = [q[i : i + 2] for i in range(len(q) - 1)]
    if bigrams:
        hit = sum(1 for b in bigrams if b in t)
        big = 0.6 * hit / len(bigrams)
    else:
        big = 0.0

    toks = [w for w in q.split() if len(w) >= 2]
    if toks:
        tok = 0.6 * sum(1 for w in toks if w in t) / len(toks)
    else:
        tok = 0.0

    return round(max(big, tok), 4)


class ResourceAdapter(ABC):
    """统一资源面适配器。签名冻结，实现不得增删参数。"""

    #: 资源面标识：file / db / kb / mcp / web
    name: str = ""

    @abstractmethod
    async def discover(self) -> list[ResourceMeta]:
        """这一面**有什么**资源（导航用，不是全量导出）。"""

    @abstractmethod
    async def search(self, query: str, limit: int = 10) -> list[Hit]:
        """按查询在本面内检索，返回带 score 的命中（降序）。"""

    @abstractmethod
    async def fetch(self, ref: str) -> Content:
        """取资源内容。``ref`` 必须来自 discover/search 的结果。"""
