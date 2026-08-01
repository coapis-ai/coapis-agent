# 场景配置简化方案

> **创建时间**：2026-07-17
> **版本**：v2.0
> **核心思想**：分类即菜单，场景关联分类，支持维度切换

---

## 一、方案核心

### 1.1 核心设计

**分类即菜单**：
- 左侧菜单直接显示分类
- 支持维度切换（通用分类 / 领域分类）
- 不需要复杂的层级结构

**场景关联分类**：
- 场景的 `category` 字段是数组，支持多个分类
- 例如：`["office-common", "natural-resources", "ecological-environment"]`
- 同一个场景可以在多个分类下显示

**维度切换**：
- 顶部维度切换器：[通用分类] [领域分类]
- 用户可以切换查看不同维度的分类

---

### 1.2 数据结构

**只需2个文件**：

```
data/scene-configs/
├── categories.json  # 分类配置（两个维度）
└── scenes.json      # 场景配置（场景关联分类）
```

---

## 二、数据结构说明

### 2.1 categories.json - 分类配置

```json
{
  "version": "2.0",
  "dimensions": {
    "nature": {
      "name": "通用分类",
      "description": "按场景的通用性分类",
      "categories": [
        {
          "id": "office-common",
          "name": "办公通用",
          "icon": "📄",
          "description": "日常办公场景，所有领域通用",
          "sort_order": 1
        },
        {
          "id": "approval-service",
          "name": "审批服务",
          "icon": "✅",
          "description": "行政审批场景，流程导向",
          "sort_order": 2
        },
        ...
      ]
    },
    
    "domain": {
      "name": "领域分类",
      "description": "按业务领域分类",
      "categories": [
        {
          "id": "natural-resources",
          "name": "自然资源",
          "icon": "🏞️",
          "description": "国土空间规划、土地管理、矿产资源等",
          "sort_order": 1,
          "context": {
            "keywords": ["三区三线", "占补平衡"],
            "regulations": ["土地管理法"]
          }
        },
        ...
      ]
    }
  }
}
```

**关键点**：
- `dimensions.nature`: 通用分类维度（7个分类）
- `dimensions.domain`: 领域分类维度（10个分类）
- `context`: 领域上下文（用于智能体的领域适配）

---

### 2.2 scenes.json - 场景配置

```json
{
  "scenes": [
    {
      "id": "meeting-minutes",
      "name": "会议纪要",
      "description": "会议录音转写和纪要生成...",
      "agent_id": "scene-meeting-minutes",
      "icon": "📝",
      
      "category": [
        "office-common",
        "natural-resources",
        "ecological-environment",
        "agriculture-rural",
        "development-reform",
        "housing-construction",
        "education",
        "forestry-grassland",
        "culture-tourism",
        "health",
        "comprehensive-enforcement"
      ],
      
      "properties": {
        "frequency": "high",
        "is_generic": true,
        "priority": "high"
      },
      
      "skills": ["audio-transcription", "docx"],
      "welcome_message": "...",
      "tags": {...}
    }
  ]
}
```

**关键点**：
- `category`: 数组，场景所属的分类ID列表
- 通用场景（如会议纪要）：同时属于"office-common"和所有领域分类
- 专属场景（如不动产登记）：只属于"natural-resources"

---

## 三、前端实现

### 3.1 界面布局

```
┌─────────────────────────────────────────┐
│ 顶部：维度切换器                          │
│ [通用分类] [领域分类]                     │
├─────────────────────────────────────────┤
│ 左侧：一级分类菜单                        │
│ ├── 📄 办公通用 (3)                      │
│ ├── ✅ 审批服务 (8)                      │
│ ├── 📋 规划编制 (5)                      │
│ ├── 🔍 监管执法 (7)                      │
│ ├── 📊 数据分析 (5)                      │
│ ├── 🏥 公共服务 (4)                      │
│ └── 🚨 应急处置 (3)                      │
├─────────────────────────────────────────┤
│ 右侧：场景卡片网格                        │
│ ┌───────┐ ┌───────┐ ┌───────┐          │
│ │ 会议  │ │ 公文  │ │ 工作  │          │
│ │ 纪要  │ │ 起草  │ │ 报告  │          │
│ └───────┘ └───────┘ └───────┘          │
└─────────────────────────────────────────┘
```

---

### 3.2 前端逻辑

```typescript
// 1. 加载分类配置
const categoriesConfig = await fetch('/api/scenes/categories');
const { dimensions } = categoriesConfig;

// 2. 当前选中的维度
const [currentDimension, setCurrentDimension] = useState('nature');

// 3. 当前选中的分类
const [selectedCategory, setSelectedCategory] = useState(null);

// 4. 获取当前维度的分类列表
const categories = dimensions[currentDimension].categories;

// 5. 加载场景列表
const scenes = await fetch('/api/scenes');

// 6. 根据选中的分类过滤场景
const filteredScenes = selectedCategory
  ? scenes.filter(s => s.category.includes(selectedCategory.id))
  : scenes;

// 7. 渲染界面
return (
  <div>
    {/* 维度切换器 */}
    <Tabs>
      <Tab key="nature" onClick={() => setCurrentDimension('nature')}>
        通用分类
      </Tab>
      <Tab key="domain" onClick={() => setCurrentDimension('domain')}>
        领域分类
      </Tab>
    </Tabs>
    
    {/* 左侧分类菜单 */}
    <Menu>
      {categories.map(cat => (
        <MenuItem key={cat.id} onClick={() => setSelectedCategory(cat)}>
          {cat.icon} {cat.name}
        </MenuItem>
      ))}
    </Menu>
    
    {/* 右侧场景卡片 */}
    <SceneCards scenes={filteredScenes} />
  </div>
);
```

---

## 四、后端API

### 4.1 API设计

| API | 方法 | 说明 |
|-----|------|------|
| `/api/scenes/categories` | GET | 获取分类配置（两个维度） |
| `/api/scenes` | GET | 获取场景列表（支持分类过滤） |
| `/api/scenes/{scene_id}` | GET | 获取场景详情 |

---

### 4.2 API实现

```python
from fastapi import APIRouter, Query
from typing import Optional, List
import json
from pathlib import Path

router = APIRouter()

# 数据文件路径
DATA_DIR = Path(__file__).parent.parent / "data" / "scene-configs"

@router.get("/scenes/categories")
async def get_categories():
    """获取分类配置"""
    with open(DATA_DIR / "categories.json", "r", encoding="utf-8") as f:
        return json.load(f)

@router.get("/scenes")
async def get_scenes(
    category: Optional[str] = Query(None, description="分类ID")
):
    """获取场景列表，支持分类过滤"""
    with open(DATA_DIR / "scenes.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    
    scenes = data["scenes"]
    
    # 根据分类过滤
    if category:
        scenes = [s for s in scenes if category in s["category"]]
    
    return {"scenes": scenes}

@router.get("/scenes/{scene_id}")
async def get_scene(scene_id: str):
    """获取场景详情"""
    with open(DATA_DIR / "scenes.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    
    for scene in data["scenes"]:
        if scene["id"] == scene_id:
            return scene
    
    return {"error": "Scene not found"}
```

---

## 五、统计信息

### 5.1 分类统计

**通用分类维度**：
| 分类名称 | 场景数量 |
|---------|---------|
| 办公通用 | 3个 |
| 审批服务 | 1个 |
| 规划编制 | 1个 |
| 监管执法 | 4个 |
| 数据分析 | 1个 |
| 公共服务 | 0个 |
| 应急处置 | 1个 |
| **总计** | **11个** |

**领域分类维度**：
| 领域名称 | 场景数量 |
|---------|---------|
| 自然资源 | 8个 |
| 生态环境 | 9个 |
| 农业农村 | 6个 |
| 发展改革 | 8个 |
| 城乡建设 | 8个 |
| 教育管理 | 3个 |
| 林草湿荒 | 4个 |
| 文化旅游 | 5个 |
| 卫生健康 | 9个 |
| 综合执法 | 7个 |

---

### 5.2 场景分类分布

**会议纪要**：
- 通用分类：办公通用
- 领域分类：自然资源、生态环境、农业农村、发展改革、城乡建设、教育管理、林草湿荒、文化旅游、卫生健康、综合执法（10个领域）

**项目审批**：
- 通用分类：审批服务
- 领域分类：自然资源、生态环境、发展改革、城乡建设（4个领域）

**执法检查**：
- 通用分类：监管执法
- 领域分类：自然资源、生态环境、城乡建设、农业农村、林草湿荒、卫生健康、文化旅游、综合执法（8个领域）

---

## 六、实施计划

### 6.1 实施步骤

| 步骤 | 工作内容 | 时间 |
|------|---------|------|
| 步骤1 | 后端API实现 | 1天 |
| 步骤2 | 前端维度切换器实现 | 0.5天 |
| 步骤3 | 前端分类菜单实现 | 0.5天 |
| 步骤4 | 前端场景卡片实现 | 1天 |
| 步骤5 | 智能体配置调整 | 1天 |
| 步骤6 | 测试与优化 | 1天 |
| **总计** | - | **5天** |

---

### 6.2 关键要点

1. ✅ **维度切换器**：顶部Tab切换，默认显示"通用分类"
2. ✅ **分类菜单**：左侧菜单，根据当前维度显示对应分类
3. ✅ **场景过滤**：`scene.category.includes(categoryId)`
4. ✅ **场景卡片**：点击打开聊天窗口

---

## 七、总结

### 7.1 简化成果

| 对比项 | 复杂方案 | 简化方案 |
|-------|---------|---------|
| **文件数量** | 5个 | 2个 |
| **视图文件** | 需要预生成 | 不需要 |
| **生成脚本** | 需要 | 不需要 |
| **前端逻辑** | 复杂 | 简单 |
| **API数量** | 4个 | 3个 |
| **实施时间** | 5天 | 5天（但更简单） |

---

### 7.2 核心优势

1. ✅ **数据结构简单**：只需2个配置文件
2. ✅ **前端逻辑清晰**：过滤逻辑一目了然
3. ✅ **支持维度切换**：满足不同用户需求
4. ✅ **场景复用率高**：一个场景可以在多个分类显示

---

**文档版本**：v2.0
**最后更新**：2026-07-17
**状态**：已完成，等待实施
