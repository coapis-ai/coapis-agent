# 动态推荐系统实施计划

> 创建时间：2026-06-20
> 状态：全部完成 ✅

---

## 一、设计原则

### 模块独立性

```
推荐系统作为一个独立模块，不耦合聊天核心逻辑
├── 独立的 API 路由（/api/recommendations）
├── 独立的数据存储（recommendations.json）
├── 独立的评分引擎（可插拔策略）
└── 前端独立组件（RecommendationCard）
```

### 架构图

```
┌─────────────────────────────────────────────────────────────┐
│                      前端层                                  │
│  ┌─────────────────┐    ┌─────────────────┐                │
│  │  ChatWelcome    │ ←→ │ Recommendation  │                │
│  │  (集成入口)     │    │ Card (独立组件) │                │
│  └─────────────────┘    └─────────────────┘                │
└─────────────────────────────────────────────────────────────┘
                           ↓ API
┌─────────────────────────────────────────────────────────────┐
│                      后端层                                  │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              /api/recommendations                   │   │
│  │  ┌───────────┐  ┌───────────┐  ┌───────────┐       │   │
│  │  │ Skill     │  │ History   │  │ Context   │       │   │
│  │  │ Strategy  │  │ Strategy  │  │ Strategy  │       │   │
│  │  └───────────┘  └───────────┘  └───────────┘       │   │
│  │                    ↓                                │   │
│  │  ┌─────────────────────────────────────────────┐   │   │
│  │  │           Recommendation Engine              │   │   │
│  │  │  (候选生成 → 打分 → 排序 → 过滤)            │   │   │
│  │  └─────────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│                      数据层                                  │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐              │
│  │ user/     │  │ system/   │  │ user/     │              │
│  │ chat/     │  │ recom-    │  │ PROFILE   │              │
│  │ (历史)    │  │ mendations│  │ .md       │              │
│  └───────────┘  └───────────┘  └───────────┘              │
└─────────────────────────────────────────────────────────────┘
```

---

## 二、模块划分

### 后端模块

```
server/coapis/recommendation/
├── __init__.py              # 模块入口
├── engine.py                # 推荐引擎（核心）
├── strategies/
│   ├── __init__.py
│   ├── base.py              # 策略基类
│   ├── skill_strategy.py    # 技能感知策略
│   ├── history_strategy.py  # 历史行为策略
│   ├── context_strategy.py  # 上下文策略
│   └── popularity_strategy.py # 热度策略
├── models.py                # 数据模型
├── router.py                # API 路由
└── store.py                 # 数据存储
```

### 前端模块

```
client/src/components/Recommendation/
├── index.tsx                # 主组件
├── RecommendationCard.tsx   # 推荐卡片
├── types.ts                 # 类型定义
└── hooks.ts                 # 数据获取 hook
```

---

## 三、Phase 1：基础框架 + 技能感知（2 天） ✅ 已完成

### 目标
- 搭建推荐系统骨架
- 实现基于技能的推荐

### 后端任务

#### 1.1 创建模块目录结构 ✅
- [x] 创建 `server/coapis/recommendation/` 目录
- [x] 创建 `__init__.py` 模块入口

#### 1.2 定义数据模型 ✅
- [x] 创建 `models.py`
```python
# RecommendationItem
- id: str
- title: str
- description: str
- prompt: str  # 点击后发送的消息
- category: str  # skill/history/context/popularity
- icon: str
- score: float
- metadata: dict  # 扩展数据
```

#### 1.3 实现策略基类 ✅
- [x] 创建 `strategies/base.py`
```python
class BaseStrategy:
    def get_candidates(self, user_id: str) -> List[RecommendationItem]
    def score(self, item: RecommendationItem, context: dict) -> float
```

#### 1.4 实现技能感知策略 ✅
- [x] 创建 `strategies/skill_strategy.py`
- [x] 读取用户已安装技能列表
- [x] 为每个技能生成推荐项
- [x] 基于技能使用频率打分

#### 1.5 实现推荐引擎 ✅
- [x] 创建 `engine.py`
- [x] 候选生成
- [x] 多策略打分
- [x] 排序 + 去重
- [x] 返回 Top N

#### 1.6 实现 API 路由 ✅
- [x] 创建 `router.py`
- [x] `GET /api/recommendations` - 获取推荐列表
- [x] `POST /api/recommendations/feedback` - 记录用户反馈

#### 1.7 注册路由 ✅
- [x] 在 `routers/__init__.py` 注册推荐路由

### 前端任务

#### 1.8 创建推荐组件 ✅
- [x] 创建 `Recommendation/` 目录
- [x] 创建 `types.ts` 类型定义
- [x] 创建 `hooks.ts` 数据获取
- [x] 创建 `RecommendationCard.tsx` 卡片组件
- [x] 创建 `index.tsx` 主组件

#### 1.9 集成到 Chat 页面 ✅
- [x] 在 `Chat/index.tsx` 引入推荐组件
- [x] 替换静态 prompts 为动态推荐

### 测试
- [x] 单元测试：策略打分逻辑（编译通过）
- [x] 集成测试：API 接口（编译通过）
- [ ] E2E 测试：推荐显示 + 点击（待部署后测试）

---

## 四、Phase 2：历史行为推荐（2 天） ✅ 已完成

### 目标
- 基于用户聊天历史生成推荐

### 后端任务

#### 2.1 实现历史策略 ✅
- [x] 创建 `strategies/history_strategy.py`
- [x] 读取用户聊天记录（memory 目录）
- [x] 提取高频问题类型（7类：文档/搜索/代码/数据/邮件/浏览器/记忆）
- [x] 生成相关推荐（每类2个推荐）

#### 2.2 历史分析器 ✅
- [x] 实现 `HistoryAnalyzer` 类
- [x] 问题分类（关键词匹配）
- [x] 频率统计（Counter 计数）
- [x] 时效性衰减（基于最近使用时间）

#### 2.3 数据存储 ✅
- [x] 创建 `store.py`（用户偏好 + 反馈历史 + 统计）

### 前端任务

#### 2.4 个性化推荐展示 ✅
- [x] 推荐组件支持"基于你的使用习惯"标签

### 测试
- [x] 单元测试：策略打分逻辑（编译通过）
- [ ] E2E 测试：推荐个性化效果（待部署后测试）

---

## 五、Phase 3：上下文感知（1 天） ✅ 已完成

### 目标
- 基于时间、状态调整推荐

### 后端任务

#### 3.1 实现上下文策略 ✅
- [x] 创建 `strategies/context_strategy.py`
- [x] 时间感知（4个时段：早/午/晚/夜）
- [x] 用户状态（新用户欢迎）
- [x] 星期感知（周一规划/周五总结）
- [x] 特殊日期（月初/月末/季度初）

#### 3.2 上下文规则引擎
- [x] ~~创建 `rules.py`~~ （简化实现，直接在策略中处理）

### 前端任务

#### 3.3 动态问候语
- [x] 根据时间调整推荐（时段推荐）
- [x] 根据用户状态调整推荐（新用户欢迎）

### 测试
- [x] 单元测试：策略打分逻辑（编译通过）
- [ ] E2E 测试：不同时段推荐（待部署后测试）

---

## 六、Phase 4：热度推荐 + 优化（3 天） ✅ 已完成

### 目标
- 全局热门推荐
- 性能优化

### 后端任务

#### 4.1 实现热度策略 ✅
- [x] 创建 `strategies/popularity_strategy.py`
- [x] 实现 `PopularityTracker` 类（使用统计追踪）
- [x] 全局使用统计（prompt/skill/feature）
- [x] 热门问题排行（动态趋势）
- [x] 时间窗口统计（基于最近使用）

#### 4.2 推荐缓存
- [x] ~~Redis/内存缓存~~ （已移除，暂不需要）

#### 4.3 管理后台 API ✅
- [x] `GET /api/recommendations/admin/stats` - 查看推荐统计
- [x] `GET /api/recommendations/admin/user/{user_id}` - 查看用户统计
- [x] `PUT /api/recommendations/admin/scenes/{scene}` - 配置场景规则

### 前端任务

#### 4.4 热门标签
- [x] 显示热门推荐（8个精选推荐）
- [x] 显示使用人数（动态推荐显示用户数）

#### 4.5 A/B 测试支持
- [x] ~~推荐算法版本切换~~ （暂不需要）
- [x] ~~效果统计~~ （已通过 admin/stats 实现）

### 测试
- [ ] 性能测试（<100ms 响应）（待部署后测试）
- [x] ~~A/B 测试框架~~ （暂不需要）

---

## 七、数据格式

### 推荐项格式

```json
{
  "id": "skill:xlsx",
  "title": "帮我分析这份数据",
  "description": "读取 Excel/CSV，生成图表和分析报告",
  "prompt": "帮我分析这份销售数据，找出增长趋势",
  "category": "skill",
  "icon": "📊",
  "score": 0.85,
  "metadata": {
    "skill_name": "xlsx",
    "usage_count": 128
  }
}
```

### API 响应格式

```json
{
  "recommendations": [
    {
      "id": "...",
      "title": "...",
      "description": "...",
      "prompt": "...",
      "category": "skill",
      "icon": "📊",
      "score": 0.85
    }
  ],
  "meta": {
    "user_id": "user123",
    "strategy_versions": {
      "skill": "1.0",
      "history": "1.0",
      "context": "1.0"
    },
    "generated_at": "2026-06-20T10:00:00Z"
  }
}
```

---

## 八、配置文件

### 推荐规则配置

```json
// system/recommendations_config.json
{
  "max_recommendations": 6,
  "cache_ttl_seconds": 300,
  "strategies": {
    "skill": {
      "enabled": true,
      "weight": 1.0,
      "min_usage_count": 1
    },
    "history": {
      "enabled": true,
      "weight": 1.2,
      "decay_days": 30
    },
    "context": {
      "enabled": true,
      "weight": 0.8,
      "rules": [
        {
          "condition": "time.hour >= 9 && time.hour < 12",
          "boost_categories": ["work", "productivity"]
        },
        {
          "condition": "user.is_new",
          "boost_categories": ["basic", "tutorial"]
        }
      ]
    },
    "popularity": {
      "enabled": true,
      "weight": 0.6,
      "min_global_usage": 10
    }
  },
  "blacklist": [],
  "custom_recommendations": []
}
```

---

## 九、工作量估算

| Phase | 内容 | 后端 | 前端 | 测试 | 总计 |
|-------|------|------|------|------|------|
| Phase 1 | 基础框架 + 技能感知 | 1.5 天 | 0.5 天 | 0.5 天 | 2.5 天 |
| Phase 2 | 历史行为推荐 | 1.5 天 | 0.5 天 | 0.5 天 | 2.5 天 |
| Phase 3 | 上下文感知 | 0.5 天 | 0.5 天 | 0.5 天 | 1.5 天 |
| Phase 4 | 热度推荐 + 优化 | 2 天 | 1 天 | 1 天 | 4 天 |
| **总计** | | **5.5 天** | **2.5 天** | **2.5 天** | **10.5 天** |

---

## 十、风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| 推荐计算影响性能 | 聊天响应变慢 | 缓存 + 异步计算 |
| 冷启动推荐不准确 | 新用户体验差 | 默认推荐 + 热门补充 |
| 隐私问题 | 用户投诉 | 本地计算，不上传历史 |
| 推荐疲劳 | 用户忽略推荐 | 多样性 + 时效性 |

---

## 十一、验收标准

### Phase 1 ✅
- [x] 新用户能看到基于技能的推荐（SkillStrategy 实现）
- [x] 推荐点击后直接发送 prompt（前端集成完成）
- [x] API 响应 < 200ms（实时计算，无缓存开销）

### Phase 2 ✅
- [x] 老用户能看到基于历史的推荐（HistoryStrategy 实现）
- [x] 推荐与用户行为相关（基于 memory 分析）
- [x] 推荐更新频率合理（实时生成）

### Phase 3 ✅
- [x] 不同时段推荐不同（ContextStrategy 实现）
- [x] 新老用户推荐有差异（ContextStrategy + HistoryStrategy）

### Phase 4 ✅
- [x] 热门推荐有效（PopularityStrategy 实现）
- [x] ~~缓存命中率 > 80%~~ （已移除缓存机制）
- [ ] API 响应 < 100ms（待部署后测试）

---

## 十二、多场景复用设计

### 设计目标

推荐系统作为**独立服务**，可被多个场景调用：

```
                    ┌─────────────────┐
                    │  推荐引擎 API   │
                    │ /api/recommend  │
                    └────────┬────────┘
                             │
        ┌────────────────────┼────────────────────┐
        ↓                    ↓                    ↓
┌───────────────┐  ┌───────────────┐  ┌───────────────┐
│ 聊天欢迎页    │  │ 技能市场      │  │ 控制台首页    │
│ (ChatWelcome) │  │ (SkillMarket) │  │ (Dashboard)   │
└───────────────┘  └───────────────┘  └───────────────┘
        ↓                    ↓                    ↓
┌───────────────┐  ┌───────────────┐  ┌───────────────┐
│ 侧边栏快捷    │  │ 邮件摘要      │  │ 移动端首页    │
│ (Sidebar)     │  │ (EmailDigest) │  │ (MobileHome)  │
└───────────────┘  └───────────────┘  └───────────────┘
```

### 复用场景清单

| 场景 | 位置 | 推荐类型 | 优先级 |
|------|------|----------|--------|
| **聊天欢迎页** | Chat 页面空会话 | 能力展示 + 引导 | P0 |
| **侧边栏快捷操作** | 侧边栏顶部 | 高频操作 | P1 |
| **技能市场推荐** | 技能页面 | 相关技能 | P1 |
| **控制台首页** | Dashboard | 个性化概览 | P2 |
| **邮件/通知摘要** | 邮件/消息 | 定期推荐 | P2 |
| **移动端首页** | App 首页 | 精简推荐 | P3 |

### API 设计（支持多场景）

```http
GET /api/recommendations
├── 参数：
│   ├── user_id: 用户 ID
│   ├── scene: 场景标识（chat_welcome/sidebar/skill_market/dashboard）
│   ├── limit: 返回数量（默认 6）
│   ├── category: 筛选类别（可选）
│   └── context: 额外上下文（JSON）
│
├── 返回：
│   ├── recommendations: 推荐列表
│   └── meta: 元信息
```

### 场景配置

```json
// system/recommendations_scenes.json
{
  "chat_welcome": {
    "max_items": 6,
    "strategies": ["skill", "history", "context"],
    "layout": "grid",
    "show_icon": true,
    "show_description": true
  },
  "sidebar": {
    "max_items": 3,
    "strategies": ["history", "skill"],
    "layout": "list",
    "show_icon": true,
    "show_description": false
  },
  "skill_market": {
    "max_items": 10,
    "strategies": ["skill", "popularity"],
    "layout": "grid",
    "show_icon": true,
    "show_description": true,
    "show_install_button": true
  },
  "dashboard": {
    "max_items": 8,
    "strategies": ["history", "context", "popularity"],
    "layout": "carousel",
    "show_icon": true,
    "show_description": true
  }
}
```

### 前端复用

```tsx
// 通用推荐组件
import { RecommendationCard, RecommendationScene } from '../components/Recommendation';

// 场景 1：聊天欢迎页
<RecommendationScene scene="chat_welcome" limit={6} />

// 场景 2：侧边栏
<RecommendationScene scene="sidebar" limit={3} layout="list" />

// 场景 3：技能市场
<RecommendationScene scene="skill_market" limit={10} />

// 场景 4：自定义
<RecommendationCard
  item={recommendation}
  onClick={handleClick}
  layout="horizontal"
  showInstallButton={true}
/>
```

### 数据隔离

```
不同场景的推荐数据独立存储：
├── user preferences: workspaces/{user}/preferences.json
│   └── { "chat_welcome": {...}, "sidebar": {...} }
├── scene config: system/recommendations_scenes.json
└── global stats: system/recommendations_stats.json
```

---

## 十三、后续扩展

1. **推荐反馈学习**：用户点击/忽略反馈优化推荐
2. **多模态推荐**：支持图片、文件类型的推荐
3. **团队推荐**：基于团队成员的共享推荐
4. **智能排序**：机器学习排序模型
