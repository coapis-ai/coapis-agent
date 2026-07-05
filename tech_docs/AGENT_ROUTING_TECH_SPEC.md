# CoApis 智能体路由机制技术方案

> **日期**: 2026-06-30  
> **作者**: Paw  
> **目标**: 实现轻量级智能体路由，零 LLM 成本  
> **代码路径**: `/apps/ai/tool-dev/dev-coapis/coapis-agent`

---

## 一、设计目标

1. **零 LLM 成本**: 路由决策不依赖额外 AI 调用
2. **低延迟**: 路由开销 < 1ms
3. **可配置**: 路由规则通过配置文件管理
4. **可扩展**: 新增智能体只需添加规则，不改代码
5. **可回退**: 路由失败时回退到默认智能体

---

## 二、架构设计

### 2.1 路由流程

```
用户消息
    │
    ▼
┌─────────────────────────────────────────┐
│  AgentRouter                             │
│                                         │
│  1. 加载路由规则 (缓存)                   │
│  2. 提取消息关键词                        │
│  3. 匹配规则 (按优先级)                   │
│  4. 返回目标智能体 ID                     │
│                                         │
│  匹配失败 → 返回 global_default          │
└─────────────────────────────────────────┘
    │
    ▼
目标智能体 Workspace
```

### 2.2 核心组件

```
coapis/agents/
├── router/                    # 路由模块 (新增)
│   ├── __init__.py
│   ├── agent_router.py       # 路由引擎
│   ├── rules.py              # 规则管理
│   └── config.json           # 路由规则配置
│
├── workspace.py               # 修改: 添加路由入口
└── service_manager.py         # 修改: 注册路由服务
```

---

## 三、详细设计

### 3.1 路由规则配置 (`router/config.json`)

```json
{
  "version": "1.0",
  "default_agent": "global_default",
  "rules": [
    {
      "id": "coding",
      "name": "编程相关",
      "target_agent": "global_coder",
      "keywords": [
        "代码", "编程", "bug", "调试", "函数", "类",
        "接口", "API", "框架", "库", "依赖",
        "Python", "Java", "Vue", "React", "SQL",
        "git", "docker", "npm", "maven",
        "报错", "异常", "错误", "traceback",
        "实现", "重构", "优化", "性能"
      ],
      "priority": 10,
      "enabled": true
    },
    {
      "id": "analysis",
      "name": "分析相关",
      "target_agent": "global_analyst",
      "keywords": [
        "需求", "分析", "方案", "设计", "架构",
        "拆解", "梳理", "流程", "业务", "场景",
        "痛点", "矛盾", "优先级", "评估",
        "对比", "选型", "可行性"
      ],
      "priority": 20,
      "enabled": true
    },
    {
      "id": "writing",
      "name": "写作相关",
      "target_agent": "global_writer",
      "keywords": [
        "文档", "写作", "文案", "润色", "翻译",
        "改写", "精简", "扩写", "总结",
        "报告", "手册", "指南", "说明"
      ],
      "priority": 30,
      "enabled": true
    },
    {
      "id": "planning",
      "name": "规划相关",
      "target_agent": "global_planner",
      "keywords": [
        "计划", "任务", "进度", "项目", "里程碑",
        "排期", "资源", "分工", "跟踪",
        "管理", "协调", "会议"
      ],
      "priority": 40,
      "enabled": true
    },
    {
      "id": "qa",
      "name": "技术问答",
      "target_agent": "global_qa_agent",
      "keywords": [
        "配置", "部署", "安装", "环境",
        "CoApis", "智能体", "技能", "工具",
        "错误", "日志", "排查", "故障",
        "怎么", "如何", "为什么"
      ],
      "priority": 50,
      "enabled": true
    },
    {
      "id": "polishing",
      "name": "文字润色",
      "target_agent": "textPro",
      "keywords": [
        "语气", "风格", "文字", "表达",
        "人话", "口语化", "正式", "亲切",
        "修改", "调整", "打磨"
      ],
      "priority": 60,
      "enabled": true
    }
  ]
}
```

### 3.2 路由引擎 (`router/agent_router.py`)

```python
"""AgentRouter - 轻量级智能体路由引擎。

基于关键词匹配，零 LLM 成本。
支持优先级排序和规则热更新。
"""
import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class RoutingRule:
    """单条路由规则。"""

    def __init__(self, rule_dict: dict):
        self.id = rule_dict["id"]
        self.name = rule_dict.get("name", self.id)
        self.target_agent = rule_dict["target_agent"]
        self.keywords = [kw.lower() for kw in rule_dict.get("keywords", [])]
        self.priority = rule_dict.get("priority", 100)
        self.enabled = rule_dict.get("enabled", True)
        # 构建关键词集合，加速匹配
        self._keyword_set = set(self.keywords)

    def match(self, message: str) -> Tuple[bool, int]:
        """匹配消息，返回 (是否匹配, 匹配关键词数量)。"""
        if not self.enabled:
            return False, 0
        msg_lower = message.lower()
        match_count = sum(1 for kw in self._keyword_set if kw in msg_lower)
        return match_count > 0, match_count


class AgentRouter:
    """智能体路由引擎。

    功能:
    - 加载和缓存路由规则
    - 关键词匹配路由
    - 规则热更新
    - 路由统计
    """

    _instance: Optional["AgentRouter"] = None

    @classmethod
    def get_instance(cls) -> "AgentRouter":
        """单例模式。"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.rules: List[RoutingRule] = []
        self.default_agent = "global_default"
        self._config_path: Optional[Path] = None
        self._last_load_time = 0.0
        self._stats = {
            "total": 0,
            "routed": 0,
            "default": 0,
            "by_agent": {},
        }

    def load_rules(self, config_path: Path) -> int:
        """加载路由规则。

        Returns:
            加载的规则数量
        """
        self._config_path = config_path
        try:
            with open(config_path, encoding="utf-8") as f:
                config = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load routing rules: {e}")
            return 0

        self.default_agent = config.get("default_agent", "global_default")
        raw_rules = config.get("rules", [])

        # 解析规则并按优先级排序
        self.rules = []
        for rule_dict in raw_rules:
            try:
                rule = RoutingRule(rule_dict)
                self.rules.append(rule)
            except Exception as e:
                logger.warning(f"Failed to parse rule: {rule_dict.get('id', '?')}: {e}")

        # 按优先级排序 (数字越小越优先)
        self.rules.sort(key=lambda r: r.priority)

        self._last_load_time = time.time()
        logger.info(f"Loaded {len(self.rules)} routing rules, default={self.default_agent}")
        return len(self.rules)

    def should_reload(self, interval: float = 60.0) -> bool:
        """检查是否需要重新加载规则。"""
        return (time.time() - self._last_load_time) > interval

    def route(self, message: str, username: str = None) -> str:
        """路由消息到目标智能体。

        Args:
            message: 用户消息
            username: 用户名 (用于统计)

        Returns:
            目标智能体 ID
        """
        self._stats["total"] += 1

        # 按优先级匹配规则
        for rule in self.rules:
            matched, count = rule.match(message)
            if matched:
                target = rule.target_agent
                self._stats["routed"] += 1
                self._stats["by_agent"][target] = (
                    self._stats["by_agent"].get(target, 0) + 1
                )
                logger.debug(
                    f"Routed to {target} (rule={rule.id}, matches={count})"
                )
                return target

        # 默认路由
        self._stats["default"] += 1
        return self.default_agent

    def get_stats(self) -> dict:
        """获取路由统计信息。"""
        total = self._stats["total"] or 1
        return {
            "total": self._stats["total"],
            "routed": self._stats["routed"],
            "default": self._stats["default"],
            "route_rate": round(self._stats["routed"] / total, 3),
            "by_agent": dict(self._stats["by_agent"]),
        }

    def reset_stats(self):
        """重置统计信息。"""
        self._stats = {"total": 0, "routed": 0, "default": 0, "by_agent": {}}
```

### 3.3 集成到 Workspace (`workspace.py` 修改)

在 `Workspace.stream_chat()` 方法中添加路由逻辑:

```python
async def stream_chat(self, user_message: str, ...):
    """Stream chat with optional agent routing."""

    # ── 新增: 智能体路由 ──
    if self.is_global and self.username:
        # 仅对全局智能体 + 有用户名的场景启用路由
        try:
            from .router.agent_router import AgentRouter
            router = AgentRouter.get_instance()

            # 懒加载规则
            if not router.rules:
                config_path = Path(__file__).parent / "router" / "config.json"
                if config_path.exists():
                    router.load_rules(config_path)

            # 路由决策
            target_agent = router.route(user_message, self.username)

            if target_agent != self.agent_id:
                # 需要转发到其他智能体
                logger.info(
                    f"Routing {self.username}'s message to {target_agent} "
                    f"(from {self.agent_id})"
                )

                # 获取目标智能体的 workspace
                target_workspace = await self._get_agent_workspace(target_agent)
                if target_workspace:
                    # 转发消息
                    async for event in target_workspace.stream_chat(
                        user_message, chat_id, user_id, ...
                    ):
                        yield event
                    return
        except Exception as e:
            logger.warning(f"Routing failed, using local agent: {e}")
```

### 3.4 服务注册 (`service_manager.py` 修改)

```python
# 在 Workspace.start() 中注册路由服务
sm.register(ServiceDescriptor(
    name="agent_router",
    factory=lambda ws: self._init_router(),
    priority=5,  # 最先初始化
    reusable=True,
))

def _init_router(self):
    """Initialize agent router."""
    from .router.agent_router import AgentRouter
    router = AgentRouter.get_instance()
    config_path = Path(__file__).parent / "router" / "config.json"
    if config_path.exists():
        router.load_rules(config_path)
    return router
```

---

## 四、实施步骤

### Step 1: 创建路由模块 (30 分钟)

```bash
cd /apps/ai/tool-dev/dev-coapis/coapis-agent/server/coapis/agents
mkdir -p router
touch router/__init__.py
# 创建 agent_router.py, rules.py, config.json
```

### Step 2: 集成到 Workspace (1 小时)

1. 修改 `workspace.py` 的 `stream_chat` 方法
2. 添加路由逻辑
3. 添加 `_get_agent_workspace` 辅助方法

### Step 3: 测试 (1 小时)

1. 单元测试: 规则匹配、优先级、默认回退
2. 集成测试: 端到端路由
3. 性能测试: 路由延迟

### Step 4: 部署 (30 分钟)

1. 重启 CoApis 服务
2. 验证路由日志
3. 监控路由统计

---

## 五、监控与调优

### 5.1 路由日志

```
2026-06-30 14:30:00 INFO  Routed to global_coder (rule=coding, matches=3)
2026-06-30 14:30:05 INFO  Routed to global_default (no match)
2026-06-30 14:30:10 INFO  Routed to global_qa_agent (rule=qa, matches=2)
```

### 5.2 路由统计 API

```python
@router.get("/api/router/stats")
async def get_router_stats():
    """获取路由统计信息。"""
    router = AgentRouter.get_instance()
    return router.get_stats()
```

### 5.3 调优方法

1. **调整关键词**: 根据实际使用情况添加/删除关键词
2. **调整优先级**: 根据业务重要性调整规则优先级
3. **添加规则**: 新增专业领域时添加对应规则
4. **禁用规则**: 暂时禁用以测试影响

---

## 六、后续优化

### 6.1 LLM 辅助路由

当关键词匹配不自信时，用小模型做二次确认:

```python
if match_count == 1:  # 仅匹配 1 个关键词，置信度低
    # 用小模型做意图分类
    intent = await llm_classify(message)
    if intent.confidence > 0.8:
        return intent.agent_id
```

### 6.2 用户偏好路由

记住用户的历史选择，优先路由到用户偏好的智能体:

```python
# 用户明确指定 @coder
if "@coder" in message:
    return "global_coder"

# 用户最近 10 次都路由到 global_analyst
if user_recent_targets.count("global_analyst") > 8:
    return "global_analyst"
```

### 6.3 上下文感知路由

根据对话历史调整路由:

```python
# 如果上一轮是 global_coder，继续路由到 global_coder
if last_agent == "global_coder" and is_code_related(message):
    return "global_coder"
```

---

*基于 CoApis-agent 项目实战经验整理*
