# CoApis 工具调度优化方案

> 基于 QwenPaw 源码深度对比分析，2026-06-14

## 一、现状对比总结

| 维度 | QwenPaw | CoApis (现状) | 差距 |
|------|---------|-----------------|------|
| **工具注册** | Python函数docstring自动解析生成schema | 手动维护description字符串 | ❌ 描述易与代码脱节 |
| **工具数量** | ~20个核心工具，按group启停 | 56个全量注册，关键词筛选 | ⚠️ LLM决策负担重 |
| **Skill系统** | SKILL.md索引注入system prompt，LLM按需加载 | 有skills目录但未注入prompt | ❌ LLM不知道有哪些skill |
| **搜索** | 无专用web_search，全靠browser_use | web_search多后端fallback | ✅ CoApis更优 |
| **System Prompt** | AGENTS.md+SOUL.md+PROFILE.md + skill索引 + env_context | AGENTS.md + env_context | ⚠️ 缺skill索引 |
| **消息显示** | 流式推送，per-stream-type独立缓冲 | 累积后一次性发送 | ⚠️ 无实时体验 |
| **显示配置** | RenderStyle配置化，可按渠道定制 | 硬编码filter逻辑 | ⚠️ 灵活性差 |

## 二、优化方案（按优先级排序）

### P0: Tool Schema 自动生成（消除描述脱节）

**问题**：CoApis的tool description是手动字符串，容易与代码签名不一致，导致LLM传错参数。

**方案**：借鉴QwenPaw的`_parse_tool_function`，从函数docstring+signature自动生成JSON schema。

```python
# 新增: coapis/tools/schema_gen.py
def auto_generate_tool_schema(tool_func) -> dict:
    """从函数docstring和signature自动生成OpenAI function calling schema"""
    # 1. 解析docstring获取description和参数说明
    # 2. 解析inspect.signature获取参数名、类型、默认值
    # 3. 用Pydantic create_model生成JSON schema
    # 4. 返回标准OpenAI function calling格式
```

**影响范围**：
- `registry.py` 的 `register_tool` 改为接收函数，自动生成schema
- 所有现有工具的description字符串可保留为fallback
- 新增工具只需写好docstring即可

**工作量**：~1天

---

### P1: Skill 索引注入 System Prompt

**问题**：CoApis有skills目录但LLM完全不知道，无法按需加载。

**方案**：借鉴QwenPaw的skill注册机制，在system prompt末尾注入skill索引。

```python
# workspace.py - _process_handler 中构建system prompt时
def _build_skill_index_prompt(skills_dir: Path) -> str:
    """扫描skills目录，生成skill索引注入system prompt"""
    skill_entries = []
    for skill_dir in skills_dir.iterdir():
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        # 读取YAML frontmatter获取name和description
        frontmatter = parse_frontmatter(skill_md)
        name = frontmatter.get("name", skill_dir.name)
        desc = frontmatter.get("description", "")
        skill_entries.append(
            f"## {name}\n{desc}\n"
            f"Check \"{skill_dir}/SKILL.md\" for how to use this skill"
        )
    
    if not skill_entries:
        return ""
    
    return (
        "# Agent Skills\n"
        "The agent skills are a collection of instructions and resources "
        "you can load dynamically. Each skill has a SKILL.md file.\n\n"
        + "\n\n".join(skill_entries)
    )
```

**影响范围**：
- `workspace.py` 的system prompt构建逻辑
- 需要确保skill的SKILL.md有标准YAML frontmatter
- LLM会在需要时调用`read_file(SKILL.md)`加载完整指令

**工作量**：~0.5天

---

### P2: 工具分组与按需激活

**问题**：56个工具全量发给LLM，决策负担重。

**方案**：借鉴QwenPaw的ToolGroup机制，将工具分为基础组和扩展组。

```python
# registry.py - 新增工具分组
TOOL_GROUPS = {
    "basic": {
        "description": "基础文件和命令操作",
        "tools": ["read_file", "write_file", "edit_file", "execute_shell_command", 
                   "grep_search", "glob_search", "get_current_time"],
        "active": True,  # 始终激活
    },
    "web": {
        "description": "网页搜索和浏览器自动化",
        "tools": ["web_search", "browser_use"],
        "active": False,  # 按需激活
    },
    "media": {
        "description": "图片、视频、文件传输",
        "tools": ["view_image", "view_video", "send_file_to_user", "desktop_screenshot"],
        "active": False,
    },
    "agent": {
        "description": "多智能体协作",
        "tools": ["list_agents", "chat_with_agent", "submit_to_agent", 
                   "check_agent_task", "spawn_subagent"],
        "active": False,
    },
    "data": {
        "description": "数据分析和处理",
        "tools": ["data_store", "data_ops", "text_processor"],
        "active": False,
    },
}

# 保留关键词触发机制作为自动激活手段
KEYWORD_GROUP_ACTIVATION = {
    "news": ["web"],
    "天气": ["web"],
    "搜索": ["web"],
    "新闻": ["web"],
    "图片": ["media"],
    "视频": ["media"],
    # ...
}
```

**工作量**：~1天

---

### P3: 搜索意图预取机制优化

**问题**：当前的搜索意图预取关键词列表是硬编码的，不够灵活。

**方案**：将搜索关键词列表移入配置，并增加更多触发词。

```python
# workspace.py - 搜索意图配置化
SEARCH_INTENT_KEYWORDS = [
    # 时间相关
    "今天", "明天", "昨天", "最新", "最近", "当前", "now", "today",
    # 动作相关
    "查一下", "搜索", "搜一下", "查找", "找一下", "查询",
    # 内容类型
    "新闻", "天气", "热点", "资讯", "头条", "八卦", "比赛",
    "价格", "股票", "汇率", "比分", "赛程",
    # 英文
    "news", "weather", "search", "find", "latest", "current",
    "price", "score", "stock",
]

# 可从配置文件加载覆盖
def load_search_keywords(config_path: Path) -> List[str]:
    """从配置文件加载搜索关键词列表"""
    if config_path.exists():
        with open(config_path) as f:
            config = json.load(f)
            return config.get("search_keywords", SEARCH_INTENT_KEYWORDS)
    return SEARCH_INTENT_KEYWORDS
```

**工作量**：~0.5天

---

### P4: 消息显示配置化

**问题**：WeCom的消息显示逻辑是硬编码的，不够灵活。

**方案**：借鉴QwenPaw的RenderStyle，实现配置化的消息渲染器。

```python
# 新增: coapis/app/channels/renderer.py
from dataclasses import dataclass

@dataclass
class RenderStyle:
    """消息渲染风格配置"""
    show_tool_details: bool = True      # 显示工具调用详情
    show_thinking: bool = True          # 显示思考过程
    supports_markdown: bool = True      # 支持Markdown
    supports_code_fence: bool = True    # 支持代码块
    use_emoji: bool = True              # 使用emoji
    filter_internal_tools: bool = True  # 过滤内部工具

class MessageRenderer:
    """消息渲染器"""
    def __init__(self, style: RenderStyle = None):
        self.style = style or RenderStyle()
    
    def render_tool_call(self, name: str, args: str) -> str:
        if self.style.show_tool_details:
            return f"🔧 **{name}**\n```\n{args[:200]}\n```"
        return f"🔧 {name}..."
    
    def render_tool_output(self, name: str, output: str) -> str:
        if self.style.show_tool_details:
            return f"✅ **{name}**:\n{output}"
        return f"✅ {name}"
    
    def render_thinking(self, text: str) -> str:
        if self.style.show_thinking:
            return f"💭 {text}"
        return ""

# 在channel初始化时根据配置创建renderer
wecom_style = RenderStyle(
    show_tool_details=True,
    show_thinking=True,
    supports_markdown=True,
    use_emoji=True,
)
renderer = MessageRenderer(wecom_style)
```

**工作量**：~1天

---

### P5: 工具描述文档化

**问题**：部分工具的description不清晰，LLM难以正确使用。

**方案**：为每个工具编写标准docstring，确保description与代码一致。

```python
# 示例: web_search.py
async def web_search(
    query: str,
    num_results: int = 5,
    backend: str = "auto",
) -> Dict[str, Any]:
    """Search the web for information.
    
    Use this tool when you need to find current information, news,
    weather, prices, or any real-world data that requires internet access.
    
    Args:
        query: The search query. Be specific and descriptive.
        num_results: Number of results to return (1-20, default 5).
        backend: Search backend. Options: "auto" (try all), "tavily",
                 "baidu", "sogou". Default "auto".
    
    Returns:
        Dict with "results" list, each containing "title", "url", "snippet".
    
    Examples:
        - "今天深圳天气" → searches weather
        - "最新科技新闻" → searches tech news
        - "Python asyncio tutorial" → searches English content
    """
```

**工作量**：~2天（所有工具）

---

## 三、实施路线图

### Phase 1: 核心优化（1周）
- **Day 1-2**: P0 (Tool Schema自动生成) + P1 (Skill索引注入)
- **Day 3**: P2 (工具分组与按需激活)
- **Day 4**: P3 (搜索意图预取优化)
- **Day 5**: 测试 + 部署

### Phase 2: 体验优化（1周）
- **Day 1-2**: P4 (消息显示配置化)
- **Day 3-5**: P5 (工具描述文档化)

### Phase 3: 高级特性（2周）
- Skill热加载与版本管理
- 工具使用统计与自动优化
- 消息流式推送（借鉴QwenPaw的stream架构）

---

## 四、预期效果

| 指标 | 优化前 | 优化后 |
|------|--------|--------|
| 工具描述准确性 | 60%（手动维护） | 95%（自动生成） |
| LLM工具选择准确率 | 70%（56个工具） | 90%（分组后~15个） |
| Skill可用性 | 0%（LLM不知道） | 100%（索引注入） |
| 搜索响应速度 | 3-5秒（browser） | 1-2秒（web_search） |
| 消息显示灵活性 | 硬编码 | 配置化 |

---

## 五、风险与缓解

1. **Schema自动生成兼容性**
   - 风险：现有工具的docstring不标准
   - 缓解：保留手动description作为fallback，渐进式迁移

2. **工具分组过度过滤**
   - 风险：某些场景需要的工具被过滤
   - 缓解：保留核心工具组始终激活，关键词触发机制兜底

3. **Skill索引增加token消耗**
   - 风险：system prompt变长
   - 缓解：只注入name+description，完整内容按需加载

---

## 六、参考实现

- QwenPaw工具注册: `/apps/ai/tool-dev/devs/QwenPaw/src/qwenpaw/agents/react_agent.py` (L280-390)
- QwenPaw Skill系统: `/apps/ai/tool-dev/devs/QwenPaw/src/qwenpaw/agents/skill_system/`
- QwenPaw消息渲染: `/apps/ai/tool-dev/devs/QwenPaw/src/qwenpaw/app/channels/renderer.py`
- QwenPaw工具分组: `/root/anaconda3/lib/python3.12/site-packages/agentscope/tool/_toolkit.py`
- QwenPaw系统提示: `/apps/ai/tool-dev/devs/QwenPaw/src/qwenpaw/agents/prompt.py`
