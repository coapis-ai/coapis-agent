# 业务场景管理 - 技术方案（社区版）

> **核心设计**：标签系统 + 场景管理  
> **数据存储**：JSON 文件（简单直接）  
> **实施周期**：4天  
> **创建日期**：2026-07-17

---

## 一、技术架构

### 1.1 整体架构

```
┌────────────────────────────────────────────┐
│            前端层（React）                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐ │
│  │ 工作台   │  │ 管理后台 │  │ 聊天界面 │ │
│  └──────────┘  └──────────┘  └──────────┘ │
└────────────────────────────────────────────┘
                    ↓ REST API
┌────────────────────────────────────────────┐
│            服务层（FastAPI）                │
│  ┌──────────────────────────────────────┐ │
│  │    SceneService                      │ │
│  │  - 标签管理                          │ │
│  │  - 场景管理                          │ │
│  │  - 工作台数据                        │ │
│  │  - 场景代入                          │ │
│  └──────────────────────────────────────┘ │
└────────────────────────────────────────────┘
                    ↓ 文件读写
┌────────────────────────────────────────────┐
│            数据层（JSON 文件）              │
│  data/scenes/                              │
│  ├── tags.json       （标签配置）          │
│  └── scenes.json     （场景配置）          │
└────────────────────────────────────────────┘
```

### 1.2 核心技术栈

| 层级 | 技术选型 | 说明 |
|------|---------|------|
| 前端 | React 18 + TypeScript + Ant Design 5 | 响应式UI组件库 |
| 后端 | Python 3.11+ + FastAPI + Pydantic | 异步API框架 |
| 数据存储 | JSON 文件 | 简单直接，易于管理 |
| 状态管理 | Zustand | 轻量级状态管理 |
| 路由 | React Router v6 | 声明式路由 |

---

## 二、数据结构设计

### 2.1 目录结构

```
coapis-agent/
├── data/
│   └── scenes/                      # 场景配置目录
│       ├── tags.json               # 标签配置
│       └── scenes.json             # 场景配置
│
└── server/coapis/data/packs/base/scenes/  # 初始化数据包
    ├── tags.json
    └── scenes.json
```

---

### 2.2 标签数据结构

**tags.json**：

```
{
  "tags": [
    {
      "id": "office-function",           # 标签ID
      "name": "办公",                     # 标签名称
      "icon": "📁",                       # 标签图标
      "description": "日常办公相关功能",   # 标签描述
      "dimension": "function",           # 标签维度（function/industry/type/frequency）
      "keywords": ["会议", "报告", "邮件"], # 关键词（用于搜索）
      "related_skills": ["audio-transcription"], # 关联技能
      "sort_order": 100,                 # 排序权重
      "show_in_menu": true,              # 是否在工作台菜单显示
      "enabled": true                    # 是否启用
    }
  ]
}
```

**标签维度说明**：

| 维度 | 说明 | 是否显示菜单 | 示例 |
|------|------|-------------|------|
| function | 功能标签 | ✓ | 办公、数据分析、文档处理 |
| industry | 行业标签 | ✗ | 通用、政府、金融、医疗 |
| type | 场景类型 | ✗ | 基础、专业、高级 |
| frequency | 使用频率 | ✗ | 高频、中频、低频 |

---

### 2.3 场景数据结构

**scenes.json**：

```
{
  "scenes": [
    {
      "id": "meeting-minutes",           # 场景ID
      "name": "会议纪要",                 # 场景名称
      "icon": "📝",                       # 场景图标
      "description": "快速生成会议纪要...", # 详细描述
      "short_description": "支持音频转写", # 简短描述（显示在卡片）
      
      "primary_tag": "office-function",  # 主标签（决定归属分区）
      "tags": [                          # 所有标签
        "office-function",
        "general-industry",
        "high-frequency"
      ],
      
      "system_prompt": "你是一个专业的...", # 系统提示词
      "welcome_message": "我可以帮您...",   # 欢迎消息
      
      "usage_count": 0,                  # 使用次数
      "created_at": "2026-07-17T10:00:00Z",
      "updated_at": "2026-07-17T10:00:00Z",
      "enabled": true                    # 是否启用
    }
  ]
}
```

---

## 三、后端实现

### 3.1 服务层设计

**文件位置**：`server/coapis/services/scene_service.py`

#### 核心服务类

```python
class SceneService:
    """场景服务"""
    
    def __init__(self, data_dir: str = "data/scenes"):
        self.data_dir = Path(data_dir)
        self._tags = None
        self._scenes = None
```

#### 主要方法

```
┌────────────────────────────────────────────────────────┐
│                    SceneService                        │
├────────────────────────────────────────────────────────┤
│  标签管理                                              │
│  ├─ list_tags(dimension, show_in_menu, enabled_only) │
│  ├─ get_tag(tag_id)                                  │
│  ├─ create_tag(tag_data)                             │
│  ├─ update_tag(tag_id, tag_data)                     │
│  └─ delete_tag(tag_id)                               │
├────────────────────────────────────────────────────────┤
│  场景管理                                              │
│  ├─ list_scenes(primary_tag, enabled_only)           │
│  ├─ get_scene(scene_id)                              │
│  ├─ create_scene(scene_data)                         │
│  ├─ update_scene(scene_id, scene_data)               │
│  ├─ delete_scene(scene_id)                           │
│  └─ increment_usage(scene_id)                        │
├────────────────────────────────────────────────────────┤
│  工作台数据                                            │
│  ├─ get_workbench_menu()                             │
│  └─ get_workbench_scenes(tag_id)                     │
└────────────────────────────────────────────────────────┘
```

#### 关键实现逻辑

**1. 获取工作台菜单**

```python
def get_workbench_menu(self) -> List[dict]:
    """获取工作台菜单（功能标签）"""
    
    # 获取功能标签
    tags = self.list_tags(
        dimension="function",
        show_in_menu_only=True,
        enabled_only=True
    )
    
    # 计算每个标签下的场景数量
    scenes = self.list_scenes(enabled_only=True)
    
    menu_items = []
    for tag in tags:
        scene_count = sum(
            1 for s in scenes 
            if s.get("primary_tag") == tag["id"]
        )
        
        menu_items.append({
            "id": tag["id"],
            "name": tag["name"],
            "icon": tag["icon"],
            "scene_count": scene_count
        })
    
    return menu_items
```

**2. 获取工作台场景**

```python
def get_workbench_scenes(self, tag_id: str) -> dict:
    """获取工作台分区场景"""
    
    tag = self.get_tag(tag_id)
    if not tag:
        raise ValueError(f"标签不存在: {tag_id}")
    
    scenes = self.list_scenes(primary_tag=tag_id, enabled_only=True)
    
    return {
        "tag": {
            "id": tag["id"],
            "name": tag["name"],
            "icon": tag["icon"],
            "description": tag.get("description", "")
        },
        "scenes": [
            {
                "id": s["id"],
                "name": s["name"],
                "icon": s["icon"],
                "short_description": s.get("short_description", "")
            }
            for s in scenes
        ]
    }
```

---

### 3.2 API 层设计

**文件位置**：`server/coapis/app/scenes.py`

#### API 接口列表

```
┌────────────────────────────────────────────────────────┐
│                    API 接口                            │
├────────────────────────────────────────────────────────┤
│  标签管理 API（5个）                                   │
│  ├─ GET    /api/scenes/tags                          │
│  ├─ GET    /api/scenes/tags/{tag_id}                 │
│  ├─ POST   /api/scenes/tags                          │
│  ├─ PUT    /api/scenes/tags/{tag_id}                 │
│  └─ DELETE /api/scenes/tags/{tag_id}                 │
├────────────────────────────────────────────────────────┤
│  场景管理 API（5个）                                   │
│  ├─ GET    /api/scenes                               │
│  ├─ GET    /api/scenes/{scene_id}                    │
│  ├─ POST   /api/scenes                               │
│  ├─ PUT    /api/scenes/{scene_id}                    │
│  └─ DELETE /api/scenes/{scene_id}                    │
├────────────────────────────────────────────────────────┤
│  工作台数据 API（3个）                                 │
│  ├─ GET    /api/scenes/workbench/menu                │
│  ├─ GET    /api/scenes/workbench/section/{tag_id}    │
│  └─ POST   /api/scenes/{scene_id}/inject             │
└────────────────────────────────────────────────────────┘
```

#### API 详细设计

**1. 获取工作台菜单**

```
GET /api/scenes/workbench/menu

响应：
{
  "menu": [
    {
      "id": "office-function",
      "name": "办公",
      "icon": "📁",
      "scene_count": 12
    }
  ]
}
```

**2. 获取工作台分区场景**

```
GET /api/scenes/workbench/section/{tag_id}

响应：
{
  "tag": {
    "id": "office-function",
    "name": "办公",
    "icon": "📁",
    "description": "日常办公相关功能"
  },
  "scenes": [
    {
      "id": "meeting-minutes",
      "name": "会议纪要",
      "icon": "📝",
      "short_description": "支持音频转写"
    }
  ]
}
```

**3. 场景代入**

```
POST /api/scenes/{scene_id}/inject

响应：
{
  "success": true,
  "chat_id": "xxx",
  "scene": {
    "id": "meeting-minutes",
    "name": "会议纪要",
    "system_prompt": "...",
    "welcome_message": "...",
    "related_skills": ["audio-transcription"]
  }
}
```

---

## 四、前端实现

### 4.1 组件结构

```
client/src/pages/Workbench/
├── index.tsx                    # 工作台主页面
├── components/
│   ├── LeftMenu.tsx            # 左侧菜单组件
│   ├── SceneCard.tsx           # 场景卡片组件
│   └── SceneGrid.tsx           # 场景网格组件
└── hooks/
    └── useWorkbenchData.ts     # 工作台数据 Hook
```

---

### 4.2 工作台页面

**文件位置**：`client/src/pages/Workbench/index.tsx`

#### 组件设计

```
┌─────────────────────────────────────────────┐
│            Workbench 组件                   │
├─────────────────────────────────────────────┤
│  State:                                    │
│  ├─ menuItems: Tag[]                      │
│  ├─ selectedMenu: string                  │
│  ├─ scenes: Scene[]                       │
│  └─ tagInfo: Tag                          │
├─────────────────────────────────────────────┤
│  Lifecycle:                                │
│  ├─ useEffect(() => loadMenu())           │
│  └─ useEffect(() => loadScenes())         │
├─────────────────────────────────────────────┤
│  Handlers:                                 │
│  ├─ handleMenuSelect(menuId)              │
│  └─ handleSceneClick(scene)               │
└─────────────────────────────────────────────┘
```

#### 核心代码

```typescript
export default function Workbench() {
  const [menuItems, setMenuItems] = useState<Tag[]>([]);
  const [selectedMenu, setSelectedMenu] = useState<string>('');
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [tagInfo, setTagInfo] = useState<Tag | null>(null);
  
  // 加载菜单
  useEffect(() => {
    loadMenu();
  }, []);
  
  // 默认选中第一个菜单
  useEffect(() => {
    if (menuItems.length > 0 && !selectedMenu) {
      handleMenuSelect(menuItems[0].id);
    }
  }, [menuItems]);
  
  // 加载场景
  const handleMenuSelect = async (menuId: string) => {
    setSelectedMenu(menuId);
    const res = await scenesApi.getWorkbenchSection(menuId);
    setTagInfo(res.tag);
    setScenes(res.scenes);
  };
  
  // 场景代入
  const handleSceneClick = async (scene: Scene) => {
    await scenesApi.injectScene(scene.id);
    navigate(`/chat?scene=${scene.id}`);
  };
  
  return (
    <Layout>
      <LeftMenu 
        items={menuItems}
        selected={selectedMenu}
        onSelect={handleMenuSelect}
      />
      <Content>
        <SceneGrid 
          tag={tagInfo}
          scenes={scenes}
          onSceneClick={handleSceneClick}
        />
      </Content>
    </Layout>
  );
}
```

---

### 4.3 左侧菜单组件

**文件位置**：`client/src/pages/Workbench/components/LeftMenu.tsx`

#### UI 结构

```
┌────────────────┐
│  📁 办公 ✓     │  ← 场景菜单（选中）
│  📊 数据分析   │  ← 场景菜单
│  📄 文档处理   │  ← 场景菜单
│  💬 沟通协作   │  ← 场景菜单
│                │
│  ────────────  │  ← 分隔线
│                │
│  ⚙️ 设置       │  ← 管理菜单
│    ├─ 场景管理 │
│    └─ 标签管理 │
└────────────────┘
```

#### 核心代码

```typescript
interface Props {
  items: Tag[];
  selected: string;
  onSelect: (id: string) => void;
}

export default function LeftMenu({ items, selected, onSelect }: Props) {
  const menuItems = [
    // 场景菜单
    ...items.map(item => ({
      key: item.id,
      icon: item.icon,
      label: item.name,
      onClick: () => onSelect(item.id)
    })),
    // 分隔线
    { type: 'divider' },
    // 管理菜单
    {
      key: 'settings',
      icon: '⚙️',
      label: '设置',
      children: [
        { key: 'scene-manage', label: '场景管理' },
        { key: 'tag-manage', label: '标签管理' }
      ]
    }
  ];
  
  return (
    <Sider width={200}>
      <Menu
        mode="inline"
        selectedKeys={[selected]}
        items={menuItems}
      />
    </Sider>
  );
}
```

---

### 4.4 场景卡片组件

**文件位置**：`client/src/pages/Workbench/components/SceneCard.tsx`

#### UI 结构

```
┌──────────────┐
│              │
│      📝      │  ← 图标（48px）
│              │
│   会议纪要   │  ← 名称（16px, bold）
│              │
│ 支持音频转写 │  ← 简短描述（12px, gray）
│              │
└──────────────┘
```

#### 核心代码

```typescript
interface Props {
  scene: Scene;
  onClick: () => void;
}

export default function SceneCard({ scene, onClick }: Props) {
  return (
    <Card
      hoverable
      onClick={onClick}
      style={{
        textAlign: 'center',
        cursor: 'pointer'
      }}
    >
      <div style={{ fontSize: '48px', marginBottom: '8px' }}>
        {scene.icon}
      </div>
      
      <div style={{ 
        fontSize: '16px', 
        fontWeight: 'bold',
        marginBottom: '4px'
      }}>
        {scene.name}
      </div>
      
      <div style={{ 
        fontSize: '12px', 
        color: '#666' 
      }}>
        {scene.short_description}
      </div>
    </Card>
  );
}
```

---

### 4.5 场景网格组件

**文件位置**：`client/src/pages/Workbench/components/SceneGrid.tsx`

#### 响应式布局

```
桌面端（≥1200px）：一行4个
平板端（≥768px）：  一行3个
移动端（<768px）：  一行2个
```

#### 核心代码

```typescript
interface Props {
  tag: Tag | null;
  scenes: Scene[];
  onSceneClick: (scene: Scene) => void;
}

export default function SceneGrid({ tag, scenes, onSceneClick }: Props) {
  if (!tag) return null;
  
  return (
    <div>
      <h2 style={{ marginBottom: '16px' }}>
        {tag.icon} {tag.name}
      </h2>
      
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
        gap: '16px'
      }}>
        {scenes.map(scene => (
          <SceneCard
            key={scene.id}
            scene={scene}
            onClick={() => onSceneClick(scene)}
          />
        ))}
      </div>
    </div>
  );
}
```

---

## 五、场景代入实现

### 5.1 代入流程

```
┌─────────────────────────┐
│  用户点击场景卡片       │
└───────────┬─────────────┘
            ↓
┌─────────────────────────┐
│  调用 inject API        │
└───────────┬─────────────┘
            ↓
┌─────────────────────────┐
│  创建聊天会话           │
└───────────┬─────────────┘
            ↓
┌─────────────────────────┐
│  注入系统提示词         │
└───────────┬─────────────┘
            ↓
┌─────────────────────────┐
│  加载关联技能           │
└───────────┬─────────────┘
            ↓
┌─────────────────────────┐
│  增加使用次数           │
└───────────┬─────────────┘
            ↓
┌─────────────────────────┐
│  跳转到聊天界面         │
└─────────────────────────┘
```

---

### 5.2 后端实现

**文件位置**：`server/coapis/services/scene_inject_service.py`

```python
class SceneInjectService:
    """场景代入服务"""
    
    def inject_scene(self, scene_id: str, user_id: str) -> dict:
        """场景代入"""
        
        # 1. 获取场景配置
        scene = self.scene_service.get_scene(scene_id)
        if not scene:
            raise ValueError(f"场景不存在: {scene_id}")
        
        # 2. 创建聊天会话
        chat_id = self._create_chat(user_id, scene_id)
        
        # 3. 注入系统提示词
        system_prompt = scene.get("system_prompt", "")
        if system_prompt:
            self._inject_system_prompt(chat_id, system_prompt)
        
        # 4. 加载关联技能
        skills = self._get_related_skills(scene)
        if skills:
            self._load_skills(chat_id, skills)
        
        # 5. 增加使用次数
        self.scene_service.increment_usage(scene_id)
        
        # 6. 返回代入信息
        return {
            "chat_id": chat_id,
            "scene": scene,
            "skills": skills
        }
    
    def _get_related_skills(self, scene: dict) -> List[str]:
        """获取关联技能"""
        
        # 从主标签获取关联技能
        primary_tag_id = scene.get("primary_tag")
        tag = self.scene_service.get_tag(primary_tag_id)
        
        if tag:
            return tag.get("related_skills", [])
        
        return []
```

---

### 5.3 前端实现

**文件位置**：`client/src/pages/Workbench/hooks/useSceneInject.ts`

```typescript
export function useSceneInject() {
  const navigate = useNavigate();
  
  const injectScene = async (sceneId: string) => {
    try {
      // 调用代入 API
      const result = await scenesApi.injectScene(sceneId);
      
      // 跳转到聊天界面
      navigate(`/chat/${result.chat_id}`);
      
      return result;
    } catch (error) {
      message.error('场景代入失败');
      throw error;
    }
  };
  
  return { injectScene };
}
```

---

## 六、初始数据

### 6.1 功能标签

```
┌────────────┬──────┬──────────┬──────────────────────────┐
│    名称    │ 图标 │   维度   │          说明          │
├────────────┼──────┼──────────┼──────────────────────────┤
│   办公     │  📁  │ function │ 日常办公相关            │
├────────────┼──────┼──────────┼──────────────────────────┤
│ 数据分析   │  📊  │ function │ 数据处理、分析、可视化  │
├────────────┼──────┼──────────┼──────────────────────────┤
│ 文档处理   │  📄  │ function │ 文档生成、审查、转换    │
├────────────┼──────┼──────────┼──────────────────────────┤
│ 沟通协作   │  💬  │ function │ 团队协作、任务分配      │
└────────────┴──────┴──────────┴──────────────────────────┘
```

---

### 6.2 初始场景

**办公场景（5个）**：

```
┌────────────┬──────┬────────────────────┐
│    名称    │ 图标 │      简短描述      │
├────────────┼──────┼────────────────────┤
│ 会议纪要   │  📝  │ 支持音频转写       │
├────────────┼──────┼────────────────────┤
│ 工作报告   │  📊  │ 自动生成           │
├────────────┼──────┼────────────────────┤
│ 邮件撰写   │  ✉️  │ 快速撰写           │
├────────────┼──────┼────────────────────┤
│ 通知公告   │  📢  │ 一键生成           │
├────────────┼──────┼────────────────────┤
│ 工作计划   │  📅  │ 智能规划           │
└────────────┴──────┴────────────────────┘
```

**数据分析场景（3个）**：

```
┌────────────┬──────┬────────────────────┐
│    名称    │ 图标 │      简短描述      │
├────────────┼──────┼────────────────────┤
│ 数据统计   │  📈  │ 快速统计           │
├────────────┼──────┼────────────────────┤
│ 图表生成   │  📉  │ 自动生成图表       │
├────────────┼──────┼────────────────────┤
│ 报表导出   │  📄  │ 多格式导出         │
└────────────┴──────┴────────────────────┘
```

**文档处理场景（3个）**：

```
┌────────────┬──────┬────────────────────┐
│    名称    │ 图标 │      简短描述      │
├────────────┼──────┼────────────────────┤
│ 政策解读   │  📋  │ 专业解读           │
├────────────┼──────┼────────────────────┤
│ 合同审查   │  ⚖️  │ 风险识别           │
├────────────┼──────┼────────────────────┤
│ 公文起草   │  📝  │ 规范起草           │
└────────────┴──────┴────────────────────┘
```

---

## 七、实施计划

### 7.1 时间安排（4天）

```
┌──────────┬────────────────────────────────────────────────┐
│   时间   │                      任务                      │
├──────────┼────────────────────────────────────────────────┤
│  第1天   │ 【数据准备】                                   │
│          │ ├─ 创建 data/scenes/ 目录                      │
│          │ ├─ 编写 tags.json（功能标签4个 + 其他标签）   │
│          │ ├─ 编写 scenes.json（初始场景11个）           │
│          │ └─ 创建初始化脚本                              │
├──────────┼────────────────────────────────────────────────┤
│  第2天   │ 【后端开发】                                   │
│          │ ├─ SceneService 服务类                         │
│          │ ├─ 标签管理 API（5个）                         │
│          │ ├─ 场景管理 API（5个）                         │
│          │ ├─ 工作台数据 API（3个）                       │
│          │ └─ 场景代入逻辑                                │
├──────────┼────────────────────────────────────────────────┤
│  第3天   │ 【前端开发】                                   │
│          │ ├─ 工作台页面（Workbench）                     │
│          │ ├─ 左侧菜单组件（LeftMenu）                    │
│          │ ├─ 场景卡片组件（SceneCard）                   │
│          │ ├─ 场景网格组件（SceneGrid）                   │
│          │ └─ 场景代入流程                                │
├──────────┼────────────────────────────────────────────────┤
│  第4天   │ 【测试优化】                                   │
│          │ ├─ 功能测试（菜单切换、场景代入）              │
│          │ ├─ 用户体验优化（加载状态、错误提示）          │
│          │ ├─ Bug 修复                                    │
│          │ └─ 文档完善                                    │
└──────────┴────────────────────────────────────────────────┘
```

---

### 7.2 交付清单

**后端交付物**：

```
┌────────────────────────────────────────────────────────┐
│  后端文件清单                                          │
├────────────────────────────────────────────────────────┤
│  数据文件                                              │
│  ├─ data/scenes/tags.json                             │
│  └─ data/scenes/scenes.json                           │
├────────────────────────────────────────────────────────┤
│  服务层                                                │
│  ├─ server/coapis/services/scene_service.py          │
│  └─ server/coapis/services/scene_inject_service.py   │
├────────────────────────────────────────────────────────┤
│  API 层                                                │
│  └─ server/coapis/app/scenes.py                       │
└────────────────────────────────────────────────────────┘
```

**前端交付物**：

```
┌────────────────────────────────────────────────────────┐
│  前端文件清单                                          │
├────────────────────────────────────────────────────────┤
│  页面                                                  │
│  └─ client/src/pages/Workbench/index.tsx             │
├────────────────────────────────────────────────────────┤
│  组件                                                  │
│  ├─ client/src/pages/Workbench/components/LeftMenu.tsx    │
│  ├─ client/src/pages/Workbench/components/SceneCard.tsx   │
│  └─ client/src/pages/Workbench/components/SceneGrid.tsx   │
├────────────────────────────────────────────────────────┤
│  Hooks                                                 │
│  ├─ client/src/pages/Workbench/hooks/useWorkbenchData.ts  │
│  └─ client/src/pages/Workbench/hooks/useSceneInject.ts     │
├────────────────────────────────────────────────────────┤
│  API                                                   │
│  └─ client/src/api/scenes.ts                         │
└────────────────────────────────────────────────────────┘
```

---

## 八、测试方案

### 8.1 单元测试

**后端测试**：

```python
# test_scene_service.py

def test_list_tags():
    """测试获取标签列表"""
    service = SceneService()
    tags = service.list_tags(dimension="function")
    assert len(tags) > 0
    assert all(t["dimension"] == "function" for t in tags)

def test_get_workbench_menu():
    """测试获取工作台菜单"""
    service = SceneService()
    menu = service.get_workbench_menu()
    assert len(menu) > 0
    assert all("scene_count" in item for item in menu)

def test_inject_scene():
    """测试场景代入"""
    service = SceneInjectService()
    result = service.inject_scene("meeting-minutes", "user123")
    assert result["chat_id"] is not None
    assert result["scene"]["id"] == "meeting-minutes"
```

---

### 8.2 集成测试

**前端测试**：

```typescript
// Workbench.test.tsx

describe('Workbench', () => {
  it('should load menu on mount', async () => {
    render(<Workbench />);
    
    await waitFor(() => {
      expect(screen.getByText('办公')).toBeInTheDocument();
    });
  });
  
  it('should load scenes when menu selected', async () => {
    render(<Workbench />);
    
    // 点击"数据分析"菜单
    fireEvent.click(screen.getByText('数据分析'));
    
    await waitFor(() => {
      expect(screen.getByText('数据统计')).toBeInTheDocument();
    });
  });
  
  it('should inject scene when card clicked', async () => {
    render(<Workbench />);
    
    // 点击场景卡片
    fireEvent.click(screen.getByText('会议纪要'));
    
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/chat/xxx');
    });
  });
});
```

---

## 九、总结

### 核心设计要点

| 维度 | 设计 |
|------|------|
| **数据存储** | JSON 文件（简单直接） |
| **标签系统** | 功能标签作为菜单，其他标签作为场景属性 |
| **场景归属** | 场景的主标签决定归属分区 |
| **技能关联** | 标签关联技能，场景代入时自动加载 |
| **工作台** | 左侧菜单 + 右侧场景卡片 |

---

### 技术优势

- ✅ **简单直接**：JSON 文件存储，易于管理和备份
- ✅ **职责清晰**：服务层、API 层、前端层职责明确
- ✅ **易于扩展**：标签系统支持多维度，场景可灵活配置
- ✅ **响应式设计**：桌面端、平板、移动端自适应

---

### 实施建议

1. **第1天**：先完成数据文件，确保数据结构正确
2. **第2天**：实现服务层和API，用Postman测试
3. **第3天**：实现前端页面，确保交互流畅
4. **第4天**：测试优化，确保用户体验

---

**文档版本**：v2.0  
**最后更新**：2026-07-17  
**下一步**：开始实施第1天任务
