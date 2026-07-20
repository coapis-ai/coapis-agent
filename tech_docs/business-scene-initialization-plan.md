# 业务场景数据初始化方案

> **文档版本**：v1.0  
> **创建日期**：2026-07-17  
> **核心问题**：如何基于现有业务技能，创建完整的业务场景体系

---

## 一、现状分析

### 1.1 现有业务技能

**技能清单**（`server/coapis/data/packs/zh/skills.json`）：

| 技能ID | 名称 | 类型 | 说明 |
|--------|------|------|------|
| `axu-data-analysis` | 数据分析 | 业务技能 | 整理数据、找规律、做图表 |
| `axu-policy-interpretation` | 政策解读 | 业务技能 | 把官话翻译成人话，提炼可落地的要点 |
| `axu-report-writing` | 报告编制 | 业务技能 | 写材料、理思路、出框架 |
| `axu-requirements-analysis` | 需求分析 | 业务技能 | 拆解问题、理清逻辑、找到关键矛盾 |
| `axu-solution-design` | 方案设计 | 业务技能 | 从0到1搭框架，平衡各方诉求 |
| `axu-text-polishing` | 文字润色 | 业务技能 | 改文风、调语气、让文字干净利落 |

**其他技能**：
- `docx`, `pdf`, `pptx`, `xlsx` - 文档处理技能
- `browser_use`, `web-search` - 浏览器操作
- `himalaya` - 邮件管理
- `news` - 新闻检索

---

### 1.2 行业场景梳理（`tech_docs/design/industry-scenes-detail.md`）

**已梳理行业**：
1. **政府单位**（党政机关、垂管部门、事业单位）
2. **企业行业**（制造业、金融业、医疗行业、教育行业）

**场景数量**：
- 政府单位：约 80+ 场景
- 企业行业：约 60+ 场景
- 总计：约 140+ 场景

---

## 二、核心问题分析

### 问题1：是否直接初始化创建场景智能体？

**答案：是，但分阶段实施**

#### 2.1 场景与场景智能体的关系

```
场景（Scene）
    ├── 定义：用户使用的功能单元（会议纪要、工作报告）
    ├── 属性：名称、图标、描述、系统提示词、关联技能
    └── 对应：一个场景智能体（scene-{scene_id}）

场景智能体（Scene Agent）
    ├── 作用：存储共享进化结果
    ├── 存储：agents/scene-{scene_id}/
    └── 生命周期：跟随场景创建/删除
```

#### 2.2 为什么要初始化场景智能体？

**优点**：
- ✅ 场景代入时无需临时创建智能体
- ✅ 支持共享进化（所有用户贡献经验）
- ✅ 管理界面可以查看场景智能体状态
- ✅ 场景数据与智能体数据一致性更好

**缺点**：
- ⚠️ 初始化时会创建大量智能体配置文件
- ⚠️ 需要管理场景和智能体的同步

**结论**：**利大于弊，应该初始化**

---

### 问题2：管理列表应该管理场景智能体吗？

**答案：是，但实现方式需要优化**

#### 2.1 当前管理方式

**场景管理**：
- 场景列表：`scenes.json`（场景元数据）
- 场景智能体：`agents/scene-{scene_id}/agent.json`

**问题**：
- 场景和场景智能体分离管理
- 用户需要在两个地方操作

#### 2.2 优化方案：统一管理

**管理界面**：
```
场景管理页面
    ├── 场景列表（表格）
    │   ├── 场景ID
    │   ├── 名称、图标、分类
    │   ├── 系统提示词
    │   ├── 关联技能
    │   ├── 智能体状态 ✨（新增）
    │   └── 操作：编辑、删除
    │
    └── 操作逻辑：
        ├── 创建场景 → 自动创建场景智能体
        ├── 编辑场景 → 同步更新智能体配置
        └── 删除场景 → 级联删除智能体
```

**技术实现**：
```python
# SceneAgentService 增强
def create_scene(scene_data):
    # 1. 创建场景记录
    scene = save_scene(scene_data)
    
    # 2. 自动创建场景智能体
    agent_config = generate_agent_config(scene)
    save_agent_config(scene.id, agent_config)
    
    # 3. 返回场景数据（包含智能体状态）
    return scene

def delete_scene(scene_id, hard_delete=False):
    # 1. 删除场景记录
    delete_scene_record(scene_id, hard_delete)
    
    # 2. 级联删除场景智能体
    delete_agent_config(scene_id)
```

---

### 问题3：业务场景数据初始化方案

#### 3.1 数据结构设计

**一级分类（Category）**：

| ID | 名称 | 图标 | 说明 |
|----|------|------|------|
| `office` | 办公 | 📁 | 日常办公、文档处理、会议管理 |
| `data-analysis` | 数据分析 | 📊 | 数据处理、统计分析、可视化 |
| `writing` | 写作 | ✍️ | 文档撰写、内容创作、文字润色 |
| `policy` | 政策 | 📋 | 政策解读、法规分析、合规审查 |
| `communication` | 沟通协作 | 💬 | 团队协作、邮件沟通、任务管理 |
| `research` | 研究 | 🔍 | 需求分析、方案设计、调研报告 |

**二级分类（子场景）**：

```
办公（office）
├── 会议管理（meeting）
│   ├── 会议纪要
│   ├── 会议安排
│   └── 会议跟踪
├── 文档处理（document）
│   ├── 公文起草
│   ├── 文档审核
│   └── 文档归档
└── 邮件管理（email）
    ├── 邮件撰写
    ├── 邮件回复
    └── 邮件归档

数据分析（data-analysis）
├── 数据统计（statistics）
│   ├── 数据清洗
│   ├── 统计分析
│   └── 报表生成
└── 数据可视化（visualization）
    ├── 图表生成
    └── 数据大屏

写作（writing）
├── 报告撰写（report）
│   ├── 工作报告
│   ├── 研究报告
│   └── 总结报告
└── 文字润色（polishing）
    ├── 文风调整
    └── AI味去除

政策（policy）
├── 政策解读（interpretation）
│   ├── 政策要点提取
│   └── 影响分析
└── 合规审查（compliance）
    ├── 合规检查
    └── 风险识别

沟通协作（communication）
├── 团队协作（team）
│   ├── 任务分配
│   └── 进度跟踪
└── 邮件沟通（email）
    ├── 商务邮件
    └── 通知公告

研究（research）
├── 需求分析（requirements）
│   ├── 需求拆解
│   └── 逻辑梳理
└── 方案设计（solution）
    ├── 方案框架
    └── 方案优化
```

---

#### 3.2 场景数据初始化方案

**方案A：基于现有业务技能映射（推荐）**

**映射关系**：

| 技能 | 一级分类 | 二级分类 | 场景名称 | 场景ID |
|------|---------|---------|---------|--------|
| `axu-data-analysis` | 数据分析 | 数据统计 | 数据分析助手 | `data-analysis` |
| `axu-policy-interpretation` | 政策 | 政策解读 | 政策解读助手 | `policy-interpretation` |
| `axu-report-writing` | 写作 | 报告撰写 | 报告撰写助手 | `report-writing` |
| `axu-requirements-analysis` | 研究 | 需求分析 | 需求分析助手 | `requirements-analysis` |
| `axu-solution-design` | 研究 | 方案设计 | 方案设计助手 | `solution-design` |
| `axu-text-polishing` | 写作 | 文字润色 | 文字润色助手 | `text-polishing` |

**场景数据示例**：

```json
{
  "id": "data-analysis",
  "name": "数据分析助手",
  "icon": "📊",
  "description": "整理数据、找规律、做图表，让数据说话",
  "category": "数据分析",
  "subcategory": "数据统计",
  "tags": ["数据", "统计", "可视化"],
  "skills": ["axu-data-analysis", "xlsx", "pptx"],
  "system_prompt": "你是一个专业的数据分析助手...\n\n核心能力：\n1. 数据清洗和预处理\n2. 统计分析\n3. 可视化图表生成\n4. 数据报告撰写",
  "welcome_message": "您好！我是数据分析助手。我可以帮您：\n• 清洗和预处理数据\n• 进行统计分析\n• 生成可视化图表\n• 撰写分析报告\n\n请上传数据文件或告诉我分析需求。",
  "status": "active"
}
```

---

**方案B：基于行业场景梳理扩展**

**从 `industry-scenes-detail.md` 提取高频场景**：

**政府单位 Top 10 场景**：

| 排名 | 场景 | 分类 | 说明 |
|------|------|------|------|
| 1 | 会议纪要 | 办公-会议管理 | 高频通用 |
| 2 | 公文起草 | 办公-文档处理 | 党政机关核心 |
| 3 | 政策解读 | 政策-政策解读 | 发改委、组织部等 |
| 4 | 工作报告 | 写作-报告撰写 | 所有单位 |
| 5 | 数据分析 | 数据分析-数据统计 | 所有单位 |
| 6 | 督查督办 | 办公-任务管理 | 办公厅/室 |
| 7 | 干部考察 | 研究-需求分析 | 组织部 |
| 8 | 财政监督 | 政策-合规审查 | 财政局 |
| 9 | 应急预案 | 研究-方案设计 | 应急管理局 |
| 10 | 邮件撰写 | 沟通协作-邮件沟通 | 所有单位 |

---

#### 3.3 完整场景清单（推荐初始化）

**基础场景（6个）**：

```json
[
  {
    "id": "meeting-minutes",
    "name": "会议纪要",
    "icon": "📝",
    "category": "办公",
    "subcategory": "会议管理",
    "tags": ["会议", "文档生成", "高频"],
    "skills": ["audio-transcription", "content-extraction"],
    "status": "active"
  },
  {
    "id": "data-analysis",
    "name": "数据分析",
    "icon": "📊",
    "category": "数据分析",
    "subcategory": "数据统计",
    "tags": ["数据", "统计", "可视化"],
    "skills": ["axu-data-analysis", "xlsx", "pptx"],
    "status": "active"
  },
  {
    "id": "policy-interpretation",
    "name": "政策解读",
    "icon": "📋",
    "category": "政策",
    "subcategory": "政策解读",
    "tags": ["政策", "解读", "专业"],
    "skills": ["axu-policy-interpretation", "docx"],
    "status": "active"
  },
  {
    "id": "report-writing",
    "name": "报告撰写",
    "icon": "📄",
    "category": "写作",
    "subcategory": "报告撰写",
    "tags": ["报告", "写作", "高频"],
    "skills": ["axu-report-writing", "docx"],
    "status": "active"
  },
  {
    "id": "requirements-analysis",
    "name": "需求分析",
    "icon": "🔍",
    "category": "研究",
    "subcategory": "需求分析",
    "tags": ["需求", "分析", "逻辑"],
    "skills": ["axu-requirements-analysis"],
    "status": "active"
  },
  {
    "id": "solution-design",
    "name": "方案设计",
    "icon": "💡",
    "category": "研究",
    "subcategory": "方案设计",
    "tags": ["方案", "设计", "框架"],
    "skills": ["axu-solution-design"],
    "status": "active"
  }
]
```

**扩展场景（可选，基于行业需求）**：

- 文字润色（`text-polishing`）
- 邮件撰写（`email-compose`）
- 公文起草（`official-document`）
- 工作计划（`work-plan`）
- 会议安排（`meeting-scheduling`）

---

## 三、实施方案

### 3.1 数据初始化流程

```
Step 1：创建分类数据
    ├── tags.json（标签配置）
    └── categories.json（分类配置）

Step 2：创建场景数据
    ├── scenes.json（场景索引）
    └── 基于现有技能映射

Step 3：初始化场景智能体
    ├── 遍历 scenes.json
    ├── 为每个场景生成智能体配置
    └── 保存到 agents/scene-{id}/agent.json

Step 4：验证数据完整性
    ├── 检查场景与智能体一一对应
    ├── 检查技能引用是否存在
    └── 检查分类标签是否完整
```

---

### 3.2 技术实现

**初始化脚本**：`scripts/init_business_scenes.py`

```python
#!/usr/bin/env python3
"""
业务场景数据初始化脚本

功能：
1. 创建分类和标签数据
2. 创建场景数据
3. 初始化场景智能体
"""

import json
from pathlib import Path

# 分类配置
CATEGORIES = {
    "office": {"name": "办公", "icon": "📁"},
    "data-analysis": {"name": "数据分析", "icon": "📊"},
    "writing": {"name": "写作", "icon": "✍️"},
    "policy": {"name": "政策", "icon": "📋"},
    "communication": {"name": "沟通协作", "icon": "💬"},
    "research": {"name": "研究", "icon": "🔍"},
}

# 场景数据（基于现有技能映射）
SCENES = [
    {
        "id": "meeting-minutes",
        "name": "会议纪要助手",
        "icon": "📝",
        "category": "办公",
        "subcategory": "会议管理",
        "tags": ["会议", "文档生成", "高频"],
        "skills": ["audio-transcription", "content-extraction"],
        "description": "专业会议纪要生成助手，支持会议录音转写、结构化会议纪要生成",
        "system_prompt": "你是一个专业的会议纪要助手...",
        "welcome_message": "您好！我是会议纪要助手...",
        "status": "active",
    },
    # ... 更多场景
]

def init_categories():
    """初始化分类数据"""
    pass

def init_scenes():
    """初始化场景数据"""
    pass

def init_scene_agents():
    """初始化场景智能体"""
    pass

if __name__ == "__main__":
    print("开始初始化业务场景数据...")
    init_categories()
    init_scenes()
    init_scene_agents()
    print("✅ 业务场景数据初始化完成！")
```

---

### 3.3 数据文件结构

```
server/data/
├── categories.json          # 分类配置
├── tags.json               # 标签配置
├── scenes.json             # 场景索引
└── agents/
    ├── scene-meeting-minutes/
    │   ├── agent.json      # 场景智能体配置
    │   └── MEMORY.md       # 共享进化记忆
    ├── scene-data-analysis/
    │   ├── agent.json
    │   └── MEMORY.md
    └── ... (其他场景智能体)
```

---

## 四、管理界面优化

### 4.1 场景管理页面增强

**新增字段**：
- **智能体状态**：显示场景智能体是否创建
- **进化状态**：显示共享记忆大小、最后更新时间
- **使用统计**：使用次数、最近使用时间

**操作增强**：
- **创建场景** → 自动创建场景智能体
- **编辑场景** → 同步更新智能体配置
- **删除场景** → 级联删除智能体
- **重建智能体** → 重新生成智能体配置

---

### 4.2 标签管理页面

**标签维度**：
- **功能标签**：办公、数据分析、写作、政策、沟通协作、研究
- **行业标签**：政府、金融、医疗、教育、企业
- **频率标签**：高频、中频、低频
- **类型标签**：通用、专业、定制

**标签管理功能**：
- 创建/编辑/删除标签
- 设置标签属性（图标、描述、关键词）
- 设置标签关联技能
- 启用/禁用标签

---

## 五、总结

### 5.1 核心决策

1. ✅ **初始化场景智能体**：场景和智能体一一对应，自动创建管理
2. ✅ **统一管理界面**：场景管理 = 场景数据 + 场景智能体管理
3. ✅ **基于现有技能映射**：6个核心业务场景，可扩展至 140+ 行业场景

---

### 5.2 实施步骤

**Phase 1：基础场景初始化（1天）**
- 创建分类和标签数据
- 创建 6 个核心业务场景
- 初始化对应的场景智能体

**Phase 2：管理界面优化（2天）**
- 场景管理页面增加智能体状态
- 标签管理页面开发
- 场景创建/编辑自动化

**Phase 3：行业场景扩展（可选）**
- 根据行业需求，从梳理文档中选择场景
- 逐步扩展场景库
- 持续优化场景配置

---

**下一步行动**：
1. 确认基础场景清单（6个核心场景）
2. 实现初始化脚本
3. 优化管理界面

---

**文档版本**：v1.0  
**最后更新**：2026-07-17
