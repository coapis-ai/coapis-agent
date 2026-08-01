# 场景管理实施方案

> **版本**: v1.0  
> **日期**: 2026-07-20  
> **目标**: 实现场景管理功能，结合标签系统

---

## 一、现状分析

### 1.1 标签数据（已就绪）

**标签总数**: 25个

**按类型分布**:
- `dimension`: 2个（domain、nature）
- `category`: 17个（作为场景的主标签）
- `industry`: 4个（通用、政府、金融、医疗）
- `frequency`: 2个（高频、中频）

**Category 标签列表**:
```
domain 维度:
├── natural-resources（自然资源）
├── ecological-environment（生态环境）
├── agriculture-rural（农业农村）
├── development-reform（发展改革）
├── housing-construction（城乡建设）
├── education（教育管理）
├── forestry-grassland（林草湿荒）
├── culture-tourism（文化旅游）
├── health（卫生健康）
└── comprehensive-enforcement（综合执法）

nature 维度:
├── office-common（办公通用）
├── approval-service（审批服务）
├── planning-compilation（规划编制）
├── supervision-enforcement（监管执法）
├── data-analysis（数据分析）
├── public-service（公共服务）
└── emergency-handling（应急处置）
```

### 1.2 场景数据（需迁移）

**场景总数**: 37个

**Category 映射关系**:

| 旧 category | 新 primary_tag_id |
|------------|-------------------|
| 办公通用 | office-common |
| 审批服务 | approval-service |
| 规划编制 | planning-compilation |
| 监管执法 | supervision-enforcement |
| 数据分析 | data-analysis |
| 应急处置 | emergency-handling |
| 自然资源 | natural-resources |
| 生态环境 | ecological-environment |
| 农业农村 | agriculture-rural |
| 发展改革 | development-reform |
| 城乡建设 | housing-construction |
| 教育管理 | education |
| 林草湿荒 | forestry-grassland |
| 文化旅游 | culture-tourism |
| 卫生健康 | health |
| 综合执法 | comprehensive-enforcement |

---

## 二、实施方案

### 2.1 数据模型优化

**SceneConfig 模型扩展**：

```python
# server/coapis/models/scene.py

class SceneConfig(BaseModel):
    """场景配置"""
    
    # 基本信息
    id: str
    name: str
    icon: str = "📝"
    description: str = ""
    short_description: str = ""  # 新增：简短描述
    
    # 标签关联（新增）
    primary_tag_id: Optional[str] = None  # 新增：主标签ID
    tag_ids: List[str] = []               # 新增：所有标签ID
    
    # 场景能力
    skills: List[str] = []
    system_prompt: str = ""
    welcome_message: str = ""
    
    # 状态和统计
    status: str = "active"
    usage_count: int = 0                  # 新增：使用次数
    
    # 时间戳
    created_at: datetime
    updated_at: datetime
    created_by: str = "system"
    
    # 向后兼容（保留）
    category: str = ""
    tags: List[str] = []
```

### 2.2 数据迁移脚本

**文件位置**: `server/scripts/migrate_scene_tags.py`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""场景数据迁移脚本：将 category 字段映射到 primary_tag_id"""

import json
from pathlib import Path
from datetime import datetime

# Category 映射表
CATEGORY_MAP = {
    "办公通用": "office-common",
    "审批服务": "approval-service",
    "规划编制": "planning-compilation",
    "监管执法": "supervision-enforcement",
    "数据分析": "data-analysis",
    "应急处置": "emergency-handling",
    "自然资源": "natural-resources",
    "生态环境": "ecological-environment",
    "农业农村": "agriculture-rural",
    "发展改革": "development-reform",
    "城乡建设": "housing-construction",
    "教育管理": "education",
    "林草湿荒": "forestry-grassland",
    "文化旅游": "culture-tourism",
    "卫生健康": "health",
    "综合执法": "comprehensive-enforcement",
}

def migrate_scenes(data_dir: Path):
    """迁移场景数据"""
    
    # 读取场景文件
    scenes_file = data_dir / "scenes.json"
    if not scenes_file.exists():
        print(f"场景文件不存在: {scenes_file}")
        return
    
    with open(scenes_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    scenes = data.get("scenes", [])
    print(f"读取场景数量: {len(scenes)}")
    
    # 迁移每个场景
    migrated = 0
    for scene in scenes:
        old_category = scene.get("category", "")
        
        # 查找映射的主标签ID
        primary_tag_id = CATEGORY_MAP.get(old_category)
        
        if primary_tag_id:
            scene["primary_tag_id"] = primary_tag_id
            migrated += 1
            print(f"  ✓ {scene['id']}: {old_category} → {primary_tag_id}")
        else:
            # 默认使用办公通用
            scene["primary_tag_id"] = "office-common"
            print(f"  ⚠ {scene['id']}: {old_category} → office-common (默认)")
        
        # 初始化 tag_ids（包含主标签）
        if "tag_ids" not in scene:
            scene["tag_ids"] = [scene["primary_tag_id"]]
        
        # 添加简短描述（如果没有）
        if "short_description" not in scene:
            desc = scene.get("description", "")
            scene["short_description"] = desc[:50] if len(desc) > 50 else desc
        
        # 添加使用次数字段（如果没有）
        if "usage_count" not in scene:
            scene["usage_count"] = 0
        
        # 更新时间戳
        scene["updated_at"] = datetime.now().isoformat()
    
    # 保存更新后的场景
    with open(scenes_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"\n迁移完成: {migrated}/{len(scenes)} 个场景")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        data_dir = Path(sys.argv[1])
    else:
        data_dir = Path("/apps/ai/coapis")
    
    print(f"数据目录: {data_dir}")
    migrate_scenes(data_dir)
```

### 2.3 场景管理服务

**文件位置**: `server/coapis/services/scene_management_service.py`

```python
class SceneManagementService:
    """场景管理服务"""
    
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.scenes_file = data_dir / "scenes.json"
        self._scenes = None
    
    # CRUD 操作
    def list_scenes(self, status=None, primary_tag_id=None, tag_id=None, keyword=None)
    def get_scene(self, scene_id: str)
    def create_scene(self, scene_data: SceneCreateRequest)
    def update_scene(self, scene_id: str, scene_data: SceneUpdateRequest)
    def delete_scene(self, scene_id: str)
    
    # 工作台数据
    def get_workbench_menu(self)
    def get_workbench_section(self, tag_id: str)
    def get_scene_detail(self, scene_id: str)
    
    # 场景代入
    def inject_scene(self, scene_id: str, user_id: str)
    def increment_usage(self, scene_id: str)
```

### 2.4 场景管理 API

**文件位置**: `server/coapis/app/routers/scene_management.py`

```python
# 管理端 API
GET    /api/admin/scenes                    # 获取场景列表
GET    /api/admin/scenes/{scene_id}         # 获取场景详情
POST   /api/admin/scenes                    # 创建场景
PUT    /api/admin/scenes/{scene_id}         # 更新场景
DELETE /api/admin/scenes/{scene_id}         # 删除场景

# 工作台 API
GET    /api/scenes/workbench/menu           # 获取工作台菜单
GET    /api/scenes/workbench/section/{tag_id}  # 获取分区场景
GET    /api/scenes/workbench/scene/{scene_id}  # 获取场景详情
```

---

## 三、前端实现

### 3.1 场景管理页面

**文件位置**: `client/src/pages/Admin/SceneManagement.tsx`

**组件结构**:
```
SceneManagement
├── 筛选栏
│   ├── 状态筛选
│   ├── 主标签筛选
│   └── 关键词搜索
├── 场景列表（Table）
│   ├── ID
│   ├── 名称
│   ├── 图标
│   ├── 主标签
│   ├── 状态
│   ├── 使用次数
│   └── 操作
└── 新建/编辑弹窗
    ├── 基本信息
    ├── 标签配置
    ├── 场景能力
    └── 状态
```

### 3.2 标签选择器组件

**主标签选择器**：
```typescript
// 只显示 category 类型的标签
// 树形结构显示
interface PrimaryTagSelectorProps {
  value?: string;
  onChange: (tagId: string) => void;
}

export function PrimaryTagSelector({ value, onChange }: Props) {
  const { data: tags } = useQuery(['tags', 'category'], () => 
    tagsApi.listTags({ tag_type: 'category' })
  );
  
  // 构建树形数据
  const treeData = buildTagTree(tags);
  
  return (
    <TreeSelect
      value={value}
      onChange={onChange}
      treeData={treeData}
      placeholder="选择主标签"
    />
  );
}
```

**其他标签选择器**：
```typescript
// 显示 industry 和 frequency 类型的标签
interface OtherTagsSelectorProps {
  value?: string[];
  onChange: (tagIds: string[]) => void;
}

export function OtherTagsSelector({ value, onChange }: Props) {
  const { data: tags } = useQuery(['tags', 'other'], () => 
    tagsApi.listTags({ 
      tag_type: ['industry', 'frequency'] 
    })
  );
  
  return (
    <Select
      mode="multiple"
      value={value}
      onChange={onChange}
      options={tags?.tags?.map(t => ({
        label: `${t.icon} ${t.name}`,
        value: t.id
      }))}
      placeholder="选择其他标签"
    />
  );
}
```

### 3.3 工作台页面优化

**文件位置**: `client/src/pages/Workbench/index.tsx`

**左侧菜单**：
```typescript
// 从标签 API 读取 category 标签
const { data: menuData } = useQuery(['workbench', 'menu'], () =>
  scenesApi.getWorkbenchMenu()
);

// 菜单项
const menuItems = [
  ...menuData?.menu?.map(item => ({
    key: item.id,
    icon: item.icon,
    label: item.name,
    count: item.scene_count
  })),
  { type: 'divider' },
  { key: 'settings', icon: '⚙️', label: '设置' }
];
```

**场景卡片**：
```typescript
// 从场景 API 读取场景列表
const { data: sceneData } = useQuery(
  ['workbench', 'section', selectedTag],
  () => scenesApi.getWorkbenchSection(selectedTag)
);

// 场景卡片网格
<SceneGrid scenes={sceneData?.scenes} onSceneClick={handleSceneClick} />
```

---

## 四、实施步骤

### 步骤1: 数据迁移（1小时）

```bash
# 1. 备份现有数据
docker exec coapis-server-dev cp /apps/ai/coapis/scenes.json /apps/ai/coapis/scenes.json.bak

# 2. 执行迁移脚本
docker exec coapis-server-dev python /app/coapis/scripts/migrate_scene_tags.py

# 3. 验证迁移结果
docker exec coapis-server-dev cat /apps/ai/coapis/scenes.json | python -c "
import json, sys
data = json.load(sys.stdin)
scenes = data['scenes']
has_primary_tag = all('primary_tag_id' in s for s in scenes)
print(f'场景总数: {len(scenes)}')
print(f'primary_tag_id 字段: {\"已添加\" if has_primary_tag else \"缺失\"}')" 
```

### 步骤2: 后端开发（2小时）

1. **优化数据模型**（30分钟）
   - 修改 `server/coapis/models/scene.py`
   - 添加新字段：`primary_tag_id`, `tag_ids`, `short_description`, `usage_count`

2. **实现服务层**（1小时）
   - 创建 `server/coapis/services/scene_management_service.py`
   - 实现 CRUD 方法
   - 实现工作台数据方法

3. **实现 API 路由**（30分钟）
   - 创建 `server/coapis/app/routers/scene_management.py`
   - 实现管理端 API
   - 实现工作台 API

### 步骤3: 前端开发（3小时）

1. **场景管理页面**（2小时）
   - 创建 `client/src/pages/Admin/SceneManagement.tsx`
   - 实现列表、表单、标签选择器

2. **工作台优化**（1小时）
   - 修改 `client/src/pages/Workbench/index.tsx`
   - 修改 `client/src/layouts/Sidebar.tsx`

### 步骤4: 测试验证（1小时）

1. **功能测试**
   - 场景列表显示
   - 场景创建、编辑、删除
   - 标签关联正确性
   - 工作台菜单和场景卡片

2. **数据验证**
   - 迁移数据正确性
   - 向后兼容性

---

## 五、验收标准

### 5.1 功能验收

- [ ] 管理员可以查看场景列表
- [ ] 管理员可以创建新场景
- [ ] 管理员可以编辑场景信息
- [ ] 管理员可以删除场景
- [ ] 场景可以关联主标签
- [ ] 场景可以关联其他标签
- [ ] 用户可以在工作台看到场景分类菜单
- [ ] 用户可以点击场景卡片查看详情

### 5.2 数据验收

- [ ] 所有场景都有 `primary_tag_id` 字段
- [ ] `primary_tag_id` 正确映射到 category 标签
- [ ] 旧字段（`category`、`tags`）保留，保证向后兼容

### 5.3 UI验收

- [ ] 场景管理页面布局合理
- [ ] 标签选择器显示正确
- [ ] 表单验证完整
- [ ] 错误提示友好

---

## 六、风险和应对

### 6.1 数据迁移风险

**风险**: 迁移脚本执行失败，数据丢失

**应对**:
- 迁移前备份数据
- 迁移后验证数据完整性
- 保留旧字段，支持回滚

### 6.2 向后兼容风险

**风险**: 旧代码依赖 `category` 字段，修改后出错

**应对**:
- 保留 `category` 和 `tags` 字段
- 新增字段不影响旧字段
- 逐步迁移，新旧并行

### 6.3 性能风险

**风险**: 场景列表过大，加载缓慢

**应对**:
- 使用分页加载
- 实现搜索筛选
- 优化数据查询

---

## 七、后续优化

### 7.1 功能增强

- 场景使用统计和分析
- 场景推荐算法
- 自定义场景模板
- 场景收藏功能

### 7.2 性能优化

- 场景缓存机制
- 懒加载场景详情
- 图片和图标优化

### 7.3 用户体验

- 场景预览功能
- 批量操作支持
- 快捷键支持
- 拖拽排序

---

**文档版本**: v1.0  
**最后更新**: 2026-07-20  
**预计工时**: 7小时
