# 标签系统设计

> **核心设计**：标签用于场景分类、搜索、推荐、技能触发  
> **创建日期**：2026-07-17

---

## 一、标签的作用

### 1.1 六大作用

| 作用 | 说明 |
|------|------|
| **分类展示** | 工作台按标签分区展示场景 |
| **筛选过滤** | 用户筛选感兴趣的场景 |
| **智能推荐** | 根据关键词推荐场景 |
| **技能触发** | 标签关联技能，场景代入时自动加载 |
| **权限控制** | 不同角色看到不同标签的场景 |
| **使用统计** | 统计标签使用频率，优化推荐 |

---

## 二、标签维度

### 2.1 功能标签（作为工作台菜单）

**用途**：决定场景在工作台的哪个分区展示

**示例**：

| 标签ID | 名称 | 图标 | 说明 |
|--------|------|------|------|
| `office-function` | 办公 | 📁 | 日常办公相关 |
| `data-analysis-function` | 数据分析 | 📊 | 数据处理、分析、可视化 |
| `document-processing-function` | 文档处理 | 📄 | 文档生成、审查、转换 |
| `communication-function` | 沟通协作 | 💬 | 团队协作、任务分配 |

**特性**：
- ✅ 作为工作台左侧菜单项
- ✅ 场景的 `primary_tag` 必须是功能标签
- ✅ 一个场景只能有一个主标签（决定归属分区）

---

### 2.2 行业标签（场景属性）

**用途**：标识场景适用的行业领域

**示例**：

| 标签ID | 名称 | 图标 | 说明 |
|--------|------|------|------|
| `general-industry` | 通用 | 🌐 | 适用于所有行业 |
| `government-industry` | 政府 | 🏛️ | 政府机关专用 |
| `finance-industry` | 金融 | 💰 | 金融行业专用 |
| `medical-industry` | 医疗 | 🏥 | 医疗卫生专用 |
| `education-industry` | 教育 | 🎓 | 教育培训专用 |

**特性**：
- ✅ 不作为工作台菜单项
- ✅ 场景可以有多个行业标签
- ✅ 用于场景详情页展示、搜索过滤

---

### 2.3 其他标签维度

**场景类型标签**：

| 标签ID | 名称 | 图标 | 说明 |
|--------|------|------|------|
| `basic-type` | 基础 | 🔰 | 基础功能场景 |
| `professional-type` | 专业 | 🔒 | 专业级场景 |
| `advanced-type` | 高级 | 🚀 | 高级功能场景 |

**使用频率标签**：

| 标签ID | 名称 | 图标 | 说明 |
|--------|------|------|------|
| `high-frequency` | 高频 | ⭐ | 使用频率高 |
| `medium-frequency` | 中频 | 📊 | 使用频率中等 |
| `low-frequency` | 低频 | 📉 | 使用频率低 |

**特性**：
- ✅ 不作为工作台菜单项
- ✅ 用于场景排序、推荐、统计

---

## 三、标签数据结构

### 3.1 完整结构

```json
{
  "id": "office-function",
  "name": "办公",
  "icon": "📁",
  "description": "日常办公相关功能",
  "dimension": "function",
  "keywords": ["会议", "报告", "邮件", "通知", "计划"],
  "related_skills": ["audio-transcription", "content-extraction"],
  "sort_order": 100,
  "show_in_menu": true,
  "enabled": true
}
```

**字段说明**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | ✅ | 标签唯一标识 |
| `name` | string | ✅ | 标签名称 |
| `icon` | string | ✅ | 标签图标（emoji） |
| `description` | string | ❌ | 标签描述 |
| `dimension` | string | ✅ | 标签维度（function/industry/type/frequency） |
| `keywords` | array | ❌ | 关键词列表（用于搜索匹配） |
| `related_skills` | array | ❌ | 关联技能列表 |
| `sort_order` | number | ✅ | 排序权重（越大越靠前） |
| `show_in_menu` | boolean | ✅ | 是否在工作台菜单显示 |
| `enabled` | boolean | ✅ | 是否启用 |

---

### 3.2 标签配置示例

**tags.json**：

```json
{
  "tags": [
    {
      "id": "office-function",
      "name": "办公",
      "icon": "📁",
      "description": "日常办公相关功能",
      "dimension": "function",
      "keywords": ["会议", "报告", "邮件", "通知", "计划"],
      "related_skills": ["audio-transcription", "content-extraction"],
      "sort_order": 100,
      "show_in_menu": true,
      "enabled": true
    },
    {
      "id": "data-analysis-function",
      "name": "数据分析",
      "icon": "📊",
      "description": "数据处理、分析、可视化",
      "dimension": "function",
      "keywords": ["数据", "统计", "图表", "报表", "分析"],
      "related_skills": ["data-processing", "chart-generation"],
      "sort_order": 90,
      "show_in_menu": true,
      "enabled": true
    },
    {
      "id": "general-industry",
      "name": "通用",
      "icon": "🌐",
      "description": "适用于所有行业",
      "dimension": "industry",
      "keywords": [],
      "related_skills": [],
      "sort_order": 100,
      "show_in_menu": false,
      "enabled": true
    },
    {
      "id": "high-frequency",
      "name": "高频",
      "icon": "⭐",
      "description": "使用频率高",
      "dimension": "frequency",
      "keywords": [],
      "related_skills": [],
      "sort_order": 100,
      "show_in_menu": false,
      "enabled": true
    }
  ]
}
```

---

## 四、场景与标签的关系

### 4.1 场景数据结构

```json
{
  "id": "meeting-minutes",
  "name": "会议纪要",
  "icon": "📝",
  "description": "快速生成会议纪要，支持音频转写、自动提取关键信息",
  "short_description": "支持音频转写",
  
  "primary_tag": "office-function",
  "tags": [
    "office-function",
    "general-industry",
    "high-frequency"
  ],
  
  "system_prompt": "你是一个专业的会议纪要助手...",
  "welcome_message": "我可以帮您快速生成会议纪要...",
  
  "usage_count": 0,
  "created_at": "2026-07-17T10:00:00Z",
  "updated_at": "2026-07-17T10:00:00Z",
  "enabled": true
}
```

**关键字段**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `primary_tag` | string | ✅ | 主标签（功能标签，决定归属分区） |
| `tags` | array | ✅ | 所有标签列表 |

---

### 4.2 标签选择规则

**规则1：主标签必须是功能标签**

```json
{
  "primary_tag": "office-function",  // ✅ 正确：功能标签
  "tags": ["office-function", "general-industry", "high-frequency"]
}
```

```json
{
  "primary_tag": "general-industry",  // ❌ 错误：不能是行业标签
  "tags": ["office-function", "general-industry"]
}
```

---

**规则2：场景可以有多个标签**

```json
{
  "primary_tag": "office-function",
  "tags": [
    "office-function",      // 功能标签
    "general-industry",     // 行业标签
    "high-frequency"        // 频率标签
  ]
}
```

---

**规则3：一个场景只能有一个主标签**

```json
{
  "primary_tag": "office-function",  // ✅ 唯一的主标签
  "tags": [...]
}
```

---

## 五、标签管理

### 5.1 标签生命周期

**创建标签**：
- 管理员在后台创建标签
- 设置标签属性（名称、图标、维度等）
- 启用标签

**使用标签**：
- 场景引用标签
- 用户使用标签筛选场景
- 系统根据标签推荐场景

**禁用标签**：
- 管理员禁用标签
- 已禁用的标签不显示在工作台
- 已禁用的标签不影响已关联的场景

**删除标签**：
- 管理员删除标签
- 删除前检查是否有场景引用
- 如有引用，提示不能删除或批量移除引用

---

### 5.2 标签管理界面

**标签列表**：

```
┌──────────────────────────────────────────────────────────────┐
│  标签管理                                      [新建标签]    │
├──────────────────────────────────────────────────────────────┤
│  名称       图标  维度      菜单显示  状态    操作           │
│  办公       📁    function  ✅        启用    编辑 | 删除   │
│  数据分析   📊    function  ✅        启用    编辑 | 删除   │
│  通用       🌐    industry  ❌        启用    编辑 | 删除   │
│  政府       🏛️    industry  ❌        启用    编辑 | 删除   │
└──────────────────────────────────────────────────────────────┘
```

**新建/编辑标签**：

```
┌──────────────────────────────────────┐
│  新建标签                            │
├──────────────────────────────────────┤
│  标签名称：[__________________]      │
│  图标：    [_______________]  [选择] │
│  描述：    [__________________]      │
│  维度：    [功能标签 ▼]              │
│  关键词：  [会议,报告,邮件]          │
│  关联技能：[__________________]      │
│  排序权重：[100]                     │
│  菜单显示：[✓]                       │
│  启用：    [✓]                       │
│                                      │
│  [取消]  [保存]                      │
└──────────────────────────────────────┘
```

---

## 六、标签与技能关联

### 6.1 关联机制

**标签可以关联技能**：

```json
{
  "id": "office-function",
  "name": "办公",
  "related_skills": [
    "audio-transcription",   // 音频转写技能
    "content-extraction"     // 内容提取技能
  ]
}
```

---

### 6.2 自动加载技能

**场景代入时，自动加载主标签关联的技能**：

```
用户点击"会议纪要"场景
    ↓
系统读取场景配置
    ├── primary_tag: "office-function"
    └── tags: ["office-function", ...]
    ↓
系统读取主标签关联的技能
    └── related_skills: ["audio-transcription", "content-extraction"]
    ↓
自动加载技能
    ├── 加载 audio-transcription 技能
    └── 加载 content-extraction 技能
    ↓
场景代入完成，AI 可以使用这些技能
```

---

## 七、标签搜索与推荐

### 7.1 搜索匹配

**用户搜索关键词时，匹配标签的关键词**：

```python
def search_scenes(keyword: str):
    # 1. 搜索场景名称和描述
    scenes = search_scene_name_and_description(keyword)
    
    # 2. 搜索标签关键词
    matching_tags = search_tag_keywords(keyword)
    
    # 3. 获取标签关联的场景
    for tag_id in matching_tags:
        scenes.extend(get_scenes_by_tag(tag_id))
    
    # 4. 去重并排序
    scenes = deduplicate_and_sort(scenes)
    
    return scenes
```

---

### 7.2 智能推荐

**根据用户使用记录推荐场景**：

```python
def recommend_scenes(user_id: str):
    # 1. 获取用户常用标签
    frequent_tags = get_user_frequent_tags(user_id)
    
    # 2. 获取这些标签下的场景
    scenes = []
    for tag_id in frequent_tags:
        scenes.extend(get_scenes_by_tag(tag_id))
    
    # 3. 按使用频率排序
    scenes.sort(key=lambda s: s.usage_count, reverse=True)
    
    return scenes[:10]  # 返回前10个
```

---

## 八、API设计

### 8.1 获取所有标签

```python
GET /api/tags

响应：
{
  "tags": [
    {
      "id": "office-function",
      "name": "办公",
      "icon": "📁",
      "dimension": "function",
      "show_in_menu": true
    }
  ]
}
```

---

### 8.2 创建标签

```python
POST /api/tags

请求：
{
  "name": "办公",
  "icon": "📁",
  "description": "日常办公相关功能",
  "dimension": "function",
  "keywords": ["会议", "报告"],
  "related_skills": ["audio-transcription"],
  "sort_order": 100,
  "show_in_menu": true
}

响应：
{
  "id": "office-function",
  "name": "办公",
  ...
}
```

---

### 8.3 更新标签

```python
PUT /api/tags/{tag_id}

请求：
{
  "name": "办公",
  "icon": "📁",
  ...
}
```

---

### 8.4 删除标签

```python
DELETE /api/tags/{tag_id}

响应：
{
  "success": true,
  "message": "标签已删除"
}
```

---

## 九、总结

### 标签系统核心设计

| 维度 | 设计 |
|------|------|
| **标签维度** | 功能、行业、类型、频率 |
| **功能标签** | 作为工作台菜单，场景必须有主标签 |
| **行业标签** | 场景属性，不作为菜单 |
| **技能关联** | 标签可关联技能，场景代入时自动加载 |
| **搜索匹配** | 标签关键词用于搜索 |
| **智能推荐** | 根据标签使用频率推荐场景 |

---

**文档版本**：v1.0  
**最后更新**：2026-07-17
