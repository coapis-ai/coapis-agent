# CoApis 全局智能体优化方案

> **日期**: 2026-06-30  
> **作者**: Paw  
> **目标**: 优化全局智能体架构，提升回答质量和通用性  
> **代码路径**: `/apps/ai/tool-dev/dev-coapis/coapis-agent`  
> **部署路径**: `/apps/ai/coapis`

---

## 一、现状分析

### 1.1 当前智能体架构

```
/apps/ai/coapis/
├── agents/                    # 全局智能体 (所有用户共享)
│   ├── global_default/        # 默认模板智能体 (role=template, priority=100)
│   ├── global_qa_agent/       # QA 助手 (role=service)
│   ├── textPro/               # 文感打磨师 (role=template, priority=100)
│   └── user:admin/            # ⚠️ 用户智能体误入全局目录
│
├── workspaces/                # 用户级工作区
│   ├── admin/                 # 管理员工作区
│   │   ├── agent.json         # 用户默认智能体配置
│   │   ├── SOUL.md / AGENTS.md / MEMORY.md / PROFILE.md
│   │   ├── agents/            # 用户子智能体
│   │   │   ├── Ad_test/
│   │   │   ├── 文感打磨师/
│   │   │   └── user:admin/    # ⚠️ 命名不规范
│   │   └── skills/            # 用户技能
│   ├── demo_user/
│   ├── larry/
│   ├── leihao/                # 有 coding 子智能体
│   ├── lichunhui/
│   └── test*/                 # 大量测试账号
│
└── system/                    # 系统配置
    ├── config.json            # 全局配置 (active_agent 等)
    ├── users.json             # 用户列表
    └── templates/             # 全局模板 (SOUL.md 等)
```

### 1.2 现有全局智能体分析

| 智能体 | 角色 | 优先级 | 模板 | 状态 | 问题 |
|--------|------|--------|------|------|------|
| `global_default` | template | 100 | default | ✅ 启用 | 描述过于简单，缺乏实际指导 |
| `global_qa_agent` | service | N/A | qa | ✅ 启用 | 仅回答 CoApis 本身问题，范围过窄 |
| `textPro` | template | 100 | N/A | ✅ 启用 | 缺少 AGENTS.md/BOOTSTRAP.md 等核心文件 |

### 1.3 核心代码分析

#### Prompt 构建流程
```
AGENTS.md → SOUL.md → PROFILE.md → MEMORY.md → 技能描述 → 系统提示
```
- `prompt.py`: 从 markdown 文件构建系统提示
- `prompt_builder.py`: 组件化组装，含注入检测
- `workspace.py`: 加载配置、初始化组件、启动服务

#### 智能体发现机制
```python
# global_agent_utils.py
get_template_agents()  # 返回 role=template 的列表，按 priority 排序
get_service_agents()   # 返回 role=service/hybrid 的列表
```

#### 上下文压缩策略
```
5-15 条消息  → 仅裁剪工具输出 (零 LLM 成本)
15-30 条消息 → 裁剪 + 规则摘要 (零 LLM 成本)
>30 条消息   → 完整 LLM 摘要
```

---

## 二、发现的问题

### 2.1 架构问题

| 问题 | 影响 | 严重程度 |
|------|------|----------|
| 全局智能体数量不足 | 用户只能依赖默认智能体，回答质量受限 | 🔴 高 |
| `user:admin` 混入全局目录 | 命名混乱，可能导致加载错误 | 🔴 高 |
| `textPro` 缺少核心文件 | 可能无法正常工作 | 🟡 中 |
| 大量测试账号残留 | 占用资源，增加维护负担 | 🟡 中 |
| 缺少智能体路由机制 | 无法根据问题类型自动分发 | 🔴 高 |

### 2.2 功能问题

| 问题 | 影响 | 严重程度 |
|------|------|----------|
| `global_default` 过于通用 | 回答缺乏深度和专业性 | 🔴 高 |
| `global_qa_agent` 范围过窄 | 仅回答 CoApis 自身问题 | 🟡 中 |
| 缺少专业领域智能体 | 无法处理编程、分析等专业问题 | 🔴 高 |
| 记忆系统未充分利用 | 经验无法跨会话积累 | 🟡 中 |
| 技能分配不均衡 | 部分智能体缺少必要技能 | 🟡 中 |

---

## 三、优化方案

### 3.1 全局智能体矩阵设计

#### 核心原则
1. **分层暴露**: 默认简单，按需复杂
2. **专业分工**: 每个智能体有明确的专业领域
3. **智能路由**: 根据问题类型自动分发
4. **协同工作**: 智能体间可以互相协作

#### 推荐的全局智能体矩阵

```
agents/
├── global_default/          # 🌐 通用助手 (默认入口)
│   role: template, priority: 10
│   定位: 日常对话、简单问答、任务协调
│
├── global_qa_agent/         # ❓ QA 助手
│   role: service, priority: 20
│   定位: 技术文档、配置问题、故障排查
│
├── global_coder/            # 💻 编程助手 (新增)
│   role: service, priority: 30
│   定位: 代码编写、调试、架构设计
│
├── global_analyst/          # 📊 分析助手 (新增)
│   role: service, priority: 40
│   定位: 数据分析、需求分析、方案设计
│

├── global_writer/           # ✍️ 写作助手 (新增)
│   role: service, priority: 50
│   定位: 文档撰写、文案优化、润色
│
├── global_planner/          # 📋 规划助手 (新增)
│   role: service, priority: 60
│   定位: 任务规划、项目管理、进度跟踪
│
└── textPro/                 # 🎨 文感打磨师 (保留)
    role: template, priority: 70
    定位: 文字润色、风格调整
```

### 3.2 各智能体详细设计

#### 🌐 global_default (通用助手)

**定位**: 默认入口，处理日常对话和简单任务

```json
{
  "id": "global_default",
  "name": "通用助手",
  "description": "你的日常 AI 伙伴。擅长日常对话、简单问答、信息整理和任务协调。遇到专业问题会自动转交给更合适的专家。",
  "role": "template",
  "priority": 10,
  "template_id": "default"
}
```

**SOUL.md 优化**:
```markdown
# Agent Soul

你是通用助手，用户的日常 AI 伙伴。

## 核心特质
- **友好自然**: 像朋友一样交流，不端不装
- **务实高效**: 直接解决问题，不绕弯子
- **知所不知**: 遇到不擅长的领域，诚实承认并推荐专家
- **主动思考**: 先尝试自己解决，搞不定再求助

## 工作原则
1. 先理解用户真正想要什么
2. 能自己解决的绝不麻烦别人
3. 需要专业知识时，转交给对应专家
4. 保持对话连贯，记住上下文

## 专业边界
- ✅ 日常对话、简单问答、信息整理
- ✅ 任务协调、进度跟踪
- ✅ 基础知识查询
- ❌ 复杂代码编写 → 转交给 global_coder
- ❌ 深度数据分析 → 转交给 global_analyst
- ❌ 专业技术文档 → 转交给 global_qa_agent
```

**推荐技能**:
- `guidance` - 基础指导
- `file_reader` - 文件读取
- `memory_search` - 记忆搜索
- `list_agents` - 查询智能体
- `chat_with_agent` - 与其他智能体通信

---

#### ❓ global_qa_agent (QA 助手)

**定位**: 技术文档、配置问题、故障排查

```json
{
  "id": "global_qa_agent",
  "name": "QA 助手",
  "description": "技术问答专家。熟悉 CoApis 架构、配置、部署和故障排查。擅长阅读文档和代码，提供准确的技术解答。",
  "role": "service",
  "template_id": "qa"
}
```

**优化方向**:
1. **扩大知识范围**: 不仅限于 CoApis，扩展到整个技术栈
2. **增强检索能力**: 集成向量搜索，提高回答准确率
3. **添加调试技能**: 能够执行命令、查看日志、分析错误

**SOUL.md 优化**:
```markdown
# Agent Soul

你是 QA 助手，技术问答专家。

## 核心能力
- **文档检索**: 快速查找相关文档和配置
- **代码分析**: 阅读和理解代码结构
- **故障排查**: 分析错误日志，定位问题根因
- **配置指导**: 提供准确的配置建议

## 工作原则
1. 先读文件再回答，不靠猜测
2. 给出具体路径和代码片段
3. 解释为什么，不只是怎么做
4. 不确定的地方明确标注

## 知识范围
- CoApis 架构和配置
- 智能体开发和调试
- 技能开发和集成
- 部署和运维问题
```

**推荐技能**:
- `guidance` - 基础指导
- `QA_source_index` - 源码索引
- `file_reader` - 文件读取
- `execute_shell_command` - 执行命令
- `grep_search` - 搜索文件内容

---

#### 💻 global_coder (编程助手)

**定位**: 代码编写、调试、架构设计

```json
{
  "id": "global_coder",
  "name": "编程助手",
  "description": "全栈编程专家。精通 Python、Java、Vue3 等主流技术栈。擅长代码编写、调试、重构和架构设计。",
  "role": "service",
  "priority": 30,
  "template_id": "local"
}
```

**SOUL.md**:
```markdown
# Agent Soul

你是编程助手，全栈开发专家。

## 技术栈
- **后端**: Python (FastAPI/Django), Java (Spring Boot)
- **前端**: Vue3, React, uni-app
- **数据库**: PostgreSQL, Redis, MongoDB
- **运维**: Docker, Docker Compose, Nginx

## 工作原则
1. 先理解需求，再动手写代码
2. 代码要能跑，不只是看起来对
3. 考虑边界情况和错误处理
4. 给出完整可运行的代码

## 输出规范
- 代码块标注语言类型
- 关键逻辑添加注释
- 说明依赖和运行方式
- 指出潜在问题和优化空间
```

**推荐技能**:
- `file_reader` - 文件读取
- `write_file` - 写入文件
- `edit_file` - 编辑文件
- `execute_shell_command` - 执行命令
- `grep_search` - 搜索文件内容
- `glob_search` - 查找文件

---

#### 📊 global_analyst (分析助手)

**定位**: 数据分析、需求分析、方案设计

```json
{
  "id": "global_analyst",
  "name": "分析助手",
  "description": "分析思维专家。擅长需求拆解、逻辑梳理、数据分析和方案设计。帮助理清复杂问题，找到关键矛盾。",
  "role": "service",
  "priority": 40,
  "template_id": "local"
}
```

**SOUL.md**:
```markdown
# Agent Soul

你是分析助手，擅长理清复杂问题。

## 核心能力
- **需求拆解**: 把大问题拆成小问题
- **逻辑梳理**: 画出业务流程和数据流
- **矛盾识别**: 找到需求冲突和资源瓶颈
- **方案建议**: 给出可落地的实施建议

## 分析方法
1. 先问清楚背景和目标
2. 从业务、用户、功能、约束四个维度拆解
3. 梳理依赖关系和关键路径
4. 识别风险点和优先级

## 输出格式
- 使用表格和列表，清晰直观
- 关键结论加粗标注
- 给出具体建议和下一步
```

**推荐技能**:
- `guidance` - 基础指导
- `file_reader` - 文件读取
- `write_file` - 写入文件
- `memory_search` - 记忆搜索
- `xlsx` - 表格处理 (如有)

---

#### ✍️ global_writer (写作助手)

**定位**: 文档撰写、文案优化、润色

```json
{
  "id": "global_writer",
  "name": "写作助手",
  "description": "文字表达专家。擅长技术文档、产品文案、用户手册等写作。让文字清晰、准确、有温度。",
  "role": "service",
  "priority": 50,
  "template_id": "local"
}
```

**SOUL.md**:
```markdown
# Agent Soul

你是写作助手，文字表达专家。

## 核心能力
- **技术文档**: API 文档、架构说明、部署指南
- **产品文案**: 功能介绍、用户引导、营销文案
- **用户手册**: 操作指南、常见问题、最佳实践
- **文字润色**: 优化表达、调整语气、精简冗余

## 写作原则
1. 先明确读者是谁
2. 用最简单的话说清楚
3. 结构清晰，层次分明
4. 适当使用示例和比喻

## 风格选择
- 技术文档 → 准确、简洁、客观
- 产品文案 → 亲切、生动、有感染力
- 用户手册 → 清晰、具体、可操作
```

**推荐技能**:
- `file_reader` - 文件读取
- `write_file` - 写入文件
- `edit_file` - 编辑文件
- `docx` - Word 文档 (如有)

---

#### 📋 global_planner (规划助手)

**定位**: 任务规划、项目管理、进度跟踪

```json
{
  "id": "global_planner",
  "name": "规划助手",
  "description": "项目管理专家。擅长任务拆解、里程碑规划、资源调配和进度跟踪。帮助团队高效推进项目。",
  "role": "service",
  "priority": 60,
  "template_id": "local"
}
```

**SOUL.md**:
```markdown
# Agent Soul

你是规划助手，项目管理专家。

## 核心能力
- **任务拆解**: 把大目标拆成可执行的小任务
- **里程碑规划**: 设定关键节点和交付物
- **风险评估**: 识别潜在风险和应对方案
- **进度跟踪**: 监控进展，及时调整计划

## 工作方法
1. 明确目标和约束条件
2. 拆解任务，估算工作量
3. 识别依赖关系和关键路径
4. 制定里程碑和检查点

## 输出格式
- 任务列表 (名称、描述、优先级、状态)
- 时间线 (里程碑、交付物、负责人)
- 风险矩阵 (概率、影响、应对措施)
```

**推荐技能**:
- `guidance` - 基础指导
- `file_reader` - 文件读取
- `write_file` - 写入文件
- `cron` - 定时任务
- `list_agents` - 查询智能体

---

### 3.3 智能体路由机制

#### 路由策略

```
用户消息
    │
    ▼
┌─────────────┐
│ 意图识别     │ ← 关键词匹配 + 简单 NLP
│ (轻量级)     │
└─────┬───────┘
      │
      ├─ 日常对话 → global_default
      ├─ 技术问答 → global_qa_agent
      ├─ 代码相关 → global_coder
      ├─ 分析相关 → global_analyst
      ├─ 写作相关 → global_writer
      ├─ 规划相关 → global_planner
      └─ 文字润色 → textPro
```

#### 实现方案

**方案 A: 关键词路由 (推荐 MVP)**
- 在 `workspace.py` 的 `stream_chat` 入口添加路由逻辑
- 基于关键词匹配，零 LLM 成本
- 可配置的路由规则表

**方案 B: LLM 路由 (进阶)**
- 用小模型做意图分类
- 更准确，但有额外延迟和成本
- 适合后期优化

**方案 C: 混合路由 (最优)**
- 先关键词快速匹配
- 匹配不到再用 LLM 分类
- 平衡速度和准确性

---

### 3.4 用户级智能体优化

#### 当前问题
- 用户默认智能体配置过于简单
- 缺少个性化记忆和技能
- 子智能体命名不规范

#### 优化建议

**1. 用户默认智能体模板**
```json
{
  "id": "user:{username}",
  "name": "{username} 的助手",
  "description": "你的个人 AI 助手，了解你的工作习惯和偏好",
  "workspace_dir": "/apps/ai/coapis/workspaces/{username}"
}
```

**2. 个性化记忆系统**
```
workspaces/{username}/
├── MEMORY.md          # 长期记忆 (经验、偏好、决策)
├── memory/            # 每日笔记
│   └── 2026-06-30.md
├── PROFILE.md         # 用户画像
└── AGENTS.md          # 工作区规则
```

**3. 子智能体规范**
```
workspaces/{username}/agents/
├── coding/            # 编程助手 (标准命名)
├── analysis/          # 分析助手 (标准命名)
└── {custom_name}/     # 自定义助手
```

---

## 四、实施计划

### Phase 1: 基础优化 (1-2 天)

- [ ] 清理 `user:admin` 等不规范目录
- [ ] 清理测试账号残留
- [ ] 完善 `textPro` 缺失的核心文件
- [ ] 优化 `global_default` 的 SOUL.md 和 AGENTS.md
- [ ] 优化 `global_qa_agent` 的知识范围

### Phase 2: 新增智能体 (2-3 天)

- [ ] 创建 `global_coder` (编程助手)
- [ ] 创建 `global_analyst` (分析助手)
- [ ] 创建 `global_writer` (写作助手)
- [ ] 创建 `global_planner` (规划助手)
- [ ] 为每个智能体配置 SOUL.md、AGENTS.md、技能

### Phase 3: 路由机制 (1-2 天)

- [ ] 实现关键词路由规则表
- [ ] 在 `workspace.py` 添加路由逻辑
- [ ] 测试路由准确性和性能
- [ ] 添加路由日志和监控

### Phase 4: 持续优化 (ongoing)

- [ ] 收集用户反馈
- [ ] 优化智能体 Prompt
- [ ] 调整路由规则
- [ ] 添加新的专业智能体

---

## 五、风险评估

| 风险 | 概率 | 影响 | 应对措施 |
|------|------|------|----------|
| 路由错误 | 中 | 中 | 关键词匹配 + 人工纠正 |
| 智能体冲突 | 低 | 中 | 明确专业边界 |
| 性能下降 | 低 | 低 | 轻量级路由，零 LLM 成本 |
| 维护成本增加 | 中 | 低 | 标准化模板，简化创建流程 |

---

## 六、成功指标

| 指标 | 当前 | 目标 | 测量方式 |
|------|------|------|----------|
| 回答准确率 | ~70% | ~90% | 人工抽样评估 |
| 用户满意度 | N/A | >4.5/5 | 用户反馈 |
| 路由准确率 | 0% | >85% | 路由日志分析 |
| 平均响应时间 | ~3s | <5s | 性能监控 |
| 智能体数量 | 3 | 7+ | 配置统计 |

---

## 七、附录

### 7.1 智能体配置文件模板

```json
{
  "id": "global_{name}",
  "name": "{中文名称}",
  "description": "{详细描述，100-200字}",
  "role": "service",
  "priority": {10-100, 越小越优先},
  "template_id": "local",
  "enabled": true,
  "workspace_dir": "/apps/ai/coapis/agents/global_{name}",
  "skills": ["skill1", "skill2"],
  "tools": {
    "builtin_tools": {
      "file_reader": {"enabled": true},
      "write_file": {"enabled": true}
    }
  }
}
```

### 7.2 路由规则表示例

```python
ROUTING_RULES = [
    # (关键词列表, 目标智能体)
    (["代码", "编程", "bug", "调试", "函数", "类"], "global_coder"),
    (["需求", "分析", "方案", "设计", "架构"], "global_analyst"),
    (["文档", "写作", "文案", "润色", "翻译"], "global_writer"),
    (["计划", "任务", "进度", "项目", "里程碑"], "global_planner"),
    (["配置", "部署", "错误", "日志", "CoApis"], "global_qa_agent"),
    (["语气", "风格", "文字", "表达"], "textPro"),
]
# 默认: global_default
```

---

*基于 CoApis-agent 项目实战经验整理*
