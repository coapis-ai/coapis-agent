# CoApis 产品演进战略规划

## 📊 三大核心方案

### 方案概览

| 方案 | 名称 | 核心价值 | 优先级 | 开发周期 |
|------|------|---------|--------|---------|
| **方案3** | 聊天界面优化 | 提升核心体验，增强AI能力 | ⭐⭐⭐ 最高 | 2-3周 |
| **方案1** | UI嵌入其他系统 | 扩展使用场景，降低接入门槛 | ⭐⭐ 中等 | 1-2周 |
| **方案2** | 业务工作台整合 | 深度业务集成，企业级应用 | ⭐ 最低 | 4-6周 |

### 战略定位

```
┌─────────────────────────────────────────────────┐
│  CoApis 产品演进路线图                           │
├─────────────────────────────────────────────────┤
│                                                 │
│  阶段1：核心能力增强（方案3）                     │
│  ┌────────────────────────────────────────┐    │
│  │ 聊天界面优化 + 知识库整合 + 空间引用    │    │
│  │ 目标：让AI更智能，对话更有价值          │    │
│  └────────────────────────────────────────┘    │
│            ↓                                   │
│  阶段2：场景扩展（方案1）                       │
│  ┌────────────────────────────────────────┐    │
│  │ UI嵌入第三方系统（OA/ERP/CRM）          │    │
│  │ 目标：让AI能力触达更多业务场景          │    │
│  └────────────────────────────────────────┘    │
│            ↓                                   │
│  阶段3：深度集成（方案2）                       │
│  ┌────────────────────────────────────────┐    │
│  │ 业务工作台整合 + 系统互联               │    │
│  │ 目标：成为企业AI中枢                    │    │
│  └────────────────────────────────────────┘    │
│                                                 │
└─────────────────────────────────────────────────┘
```

---

## 🎯 方案3：聊天界面优化（最高优先级）

### 核心价值

**解决痛点**：
- ❌ 聊天时无法快速访问我的空间文件
- ❌ 知识库内容难以引用
- ❌ AI回答缺乏上下文支持
- ❌ 多轮对话信息分散

**提升体验**：
- ✅ AI可以引用我的空间文件内容
- ✅ AI可以查询知识库提供精准回答
- ✅ 对话更智能、更有价值
- ✅ 提升用户粘性和活跃度

---

### 详细设计

#### 1. 聊天界面布局优化

```
┌──────────────────────────────────────────────────────────┐
│  聊天界面（三栏布局）                                      │
├──────────────┬─────────────────────────┬─────────────────┤
│              │                         │                 │
│  左侧面板    │      中间对话区         │   右侧面板      │
│  (可折叠)    │                         │   (可折叠)      │
│              │                         │                 │
│  📁我的空间  │  💬 对话消息            │  📚 知识库      │
│  ├─ 文件     │  ┌────────────────┐    │  ├─ 技术文档    │
│  ├─ 文件夹   │  │ 用户: ...      │    │  ├─ 产品文档    │
│  └─ 搜索     │  │ AI: ...        │    │  └─ 搜索        │
│              │  └────────────────┘    │                 │
│  📝 最近使用 │                         │  🔍 AI建议      │
│  ├─ 文档1   │  🔍 输入框               │  ├─ 相关文档    │
│  └─ 文档2   │  [📎] [📚] [🔍] [发送]  │  └─ 推荐内容    │
│              │                         │                 │
└──────────────┴─────────────────────────┴─────────────────┘
```

**布局特性**：
- 左右面板默认折叠，不占用空间
- 需要时展开，提供快速访问
- 支持拖拽调整宽度
- 移动端自动适配

#### 2. 我的空间集成

##### 2.1 文件快速引用

**场景1：直接引用文件**

```
用户: "帮我分析一下这个文档"
操作: 从左侧面板拖拽文件到输入框
      或点击文件 → "引用到对话"

AI: 自动读取文件内容并分析
    "我已读取文档《产品规划.pdf》，以下是分析：
     1. 核心功能：...
     2. 时间规划：...
     3. 建议优化点：..."
```

**场景2：搜索后引用**

```
用户: 点击左侧面板的搜索图标
输入: "产品规划"
结果: 显示相关文件列表
操作: 点击文件 → "引用" → 文件内容发送给AI
```

##### 2.2 文件上下文感知

```typescript
// AI自动检测对话中提到的文件
用户: "根据上次的方案修改一下"

AI后台处理:
  1. 检索最近使用的文件
  2. 搜索匹配"方案"关键词的文件
  3. 找到《技术方案v2.docx》
  4. 自动读取内容

AI回复: "我找到了《技术方案v2.docx》，您想修改哪个部分？"
```

##### 2.3 文件预览与引用

```typescript
// 点击文件显示预览
┌────────────────────────────────┐
│ 📄 产品规划.pdf                 │
├────────────────────────────────┤
│ [预览] [引用] [下载]            │
├────────────────────────────────┤
│                                │
│ 文档预览内容...                │
│ (支持Markdown/PDF/Word等)      │
│                                │
└────────────────────────────────┘
```

#### 3. 知识库集成

##### 3.1 知识库快速查询

```
┌────────────────────────────────┐
│ 📚 知识库面板                   │
├────────────────────────────────┤
│ 🔍 搜索知识库...                │
├────────────────────────────────┤
│ 📁 技术文档 (12)                │
│   ├─ API文档                   │
│   ├─ 架构设计                  │
│   └─ 部署指南                  │
│                                │
│ 📁 产品文档 (8)                 │
│   ├─ 产品手册                  │
│   └─ 用户指南                  │
│                                │
│ 🤖 AI建议                       │
│ ├─ 💡 相关：API文档            │
│ └─ 💡 推荐：架构设计           │
└────────────────────────────────┘
```

##### 3.2 知识库内容引用

**场景1：直接引用知识库文档**

```
用户: "公司的API接口规范是什么？"
操作: 点击知识库 → API文档 → "引用"

AI: "根据知识库《API文档》，接口规范如下：
     1. RESTful风格
     2. 认证方式：Bearer Token
     3. 响应格式：JSON
     ..."
```

**场景2：AI自动查询知识库**

```
用户: "这个功能怎么使用？"

AI后台处理:
  1. 识别用户意图（询问使用方法）
  2. 自动检索知识库
  3. 找到相关文档《用户指南》
  4. 提取相关章节

AI回复: "根据《用户指南》，该功能的使用步骤如下：
         1. ...
         2. ...
         [查看完整文档]"
```

##### 3.3 知识库上下文提示

```typescript
// AI根据对话上下文主动提示
用户: "我想了解一下系统架构"

AI检测到关键词"系统架构"
→ 自动搜索知识库
→ 找到《架构设计》文档
→ 主动提示

AI: "我找到了知识库中的《架构设计》文档，需要我为您讲解吗？"
```

#### 4. 智能引用系统

##### 4.1 引用管理

```
┌────────────────────────────────┐
│ 📎 当前对话引用                 │
├────────────────────────────────┤
│ ✅ 产品规划.pdf (我的空间)      │
│ ✅ API文档.md (知识库)          │
│ ❌ 移除引用                     │
├────────────────────────────────┤
│ [管理引用] [清空]               │
└────────────────────────────────┘
```

##### 4.2 引用追踪

```typescript
// AI记录引用来源
AI回复: "根据《产品规划.pdf》第3章的内容，
         核心功能包括：
         1. 智能对话
         2. 知识库管理
         3. 文件协作

         [来源：产品规划.pdf, p.3]"

用户点击 [来源] → 自动跳转到原文
```

##### 4.3 多文件综合分析

```
用户: "对比一下这两个方案的优劣"
操作: 同时引用《方案A.docx》和《方案B.docx》

AI: 综合分析两个文件后生成对比报告：
    | 维度 | 方案A | 方案B |
    |------|-------|-------|
    | 成本 | 低    | 中    |
    | 周期 | 2周   | 4周   |
    | 风险 | 中    | 低    |

    建议：如果时间紧迫，选择方案A...
```

---

### 技术实现方案

#### 架构设计

```
┌─────────────────────────────────────────────────┐
│  前端架构                                        │
├─────────────────────────────────────────────────┤
│                                                 │
│  ChatPage (聊天主页面)                          │
│  ├─ ChatPanel (中间对话区)                      │
│  ├─ SpacePanel (左侧：我的空间)                 │
│  ├─ KnowledgePanel (右侧：知识库)               │
│  └─ ReferenceManager (引用管理器)               │
│                                                 │
│  状态管理 (Zustand)                             │
│  ├─ chatStore (对话状态)                        │
│  ├─ spaceStore (我的空间状态)                   │
│  ├─ knowledgeStore (知识库状态)                 │
│  └─ referenceStore (引用状态)                   │
│                                                 │
└─────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────┐
│  后端架构                                        │
├─────────────────────────────────────────────────┤
│                                                 │
│  /api/chat (对话接口)                           │
│  ├─ 支持 file_ids 参数（引用文件）              │
│  ├─ 支持 knowledge_ids 参数（引用知识库）       │
│  └─ 自动注入上下文                              │
│                                                 │
│  /api/files (文件管理)                          │
│  ├─ 文件搜索                                    │
│  ├─ 文件预览                                    │
│  └─ 文件内容提取                                │
│                                                 │
│  /api/knowledge (知识库管理)                    │
│  ├─ 知识库搜索                                  │
│  ├─ 向量检索                                    │
│  └─ 内容提取                                    │
│                                                 │
│  ContextInjector (上下文注入器)                 │
│  ├─ 自动检测引用                                │
│  ├─ 读取文件/知识库内容                         │
│  └─ 注入到AI上下文                              │
│                                                 │
└─────────────────────────────────────────────────┘
```

#### 核心代码设计

**前端：引用管理器**

```typescript
// client/src/stores/referenceStore.ts
import { create } from 'zustand';

interface Reference {
  id: string;
  type: 'file' | 'knowledge';
  name: string;
  path: string;
  content?: string;
}

interface ReferenceStore {
  references: Reference[];

  // 添加引用
  addReference: (ref: Reference) => void;

  // 移除引用
  removeReference: (id: string) => void;

  // 清空引用
  clearReferences: () => void;

  // 获取引用内容
  fetchReferenceContent: (id: string) => Promise<string>;
}

export const useReferenceStore = create<ReferenceStore>((set, get) => ({
  references: [],

  addReference: (ref) =>
    set((state) => ({
      references: [...state.references, ref],
    })),

  removeReference: (id) =>
    set((state) => ({
      references: state.references.filter((r) => r.id !== id),
    })),

  clearReferences: () => set({ references: [] }),

  fetchReferenceContent: async (id) => {
    const ref = get().references.find((r) => r.id === id);
    if (!ref) return '';

    const response = await fetch(`/api/${ref.type === 'file' ? 'files' : 'knowledge'}/${id}/content`);
    const data = await response.json();

    return data.content;
  },
}));
```

**前端：聊天输入框增强**

```typescript
// client/src/components/ChatInput.tsx
import { useReferenceStore } from '../stores/referenceStore';

export function ChatInput() {
  const { references } = useReferenceStore();
  const [message, setMessage] = useState('');

  const handleSend = async () => {
    const payload = {
      message,
      file_ids: references.filter((r) => r.type === 'file').map((r) => r.id),
      knowledge_ids: references.filter((r) => r.type === 'knowledge').map((r) => r.id),
    };

    await api.chat.send(payload);
    setMessage('');
  };

  return (
    <div className="chat-input">
      {/* 引用提示 */}
      {references.length > 0 && (
        <div className="reference-hints">
          {references.map((ref) => (
            <Tag key={ref.id} closable onClose={() => removeReference(ref.id)}>
              {ref.name}
            </Tag>
          ))}
        </div>
      )}

      {/* 输入框 */}
      <Input
        value={message}
        onChange={(e) => setMessage(e.target.value)}
        placeholder="输入消息..."
      />

      {/* 工具栏 */}
      <div className="toolbar">
        <Button icon={<FileOutlined />} onClick={openSpacePanel}>
          文件
        </Button>
        <Button icon={<BookOutlined />} onClick={openKnowledgePanel}>
          知识库
        </Button>
        <Button type="primary" onClick={handleSend}>
          发送
        </Button>
      </div>
    </div>
  );
}
```

**后端：上下文注入器**

```python
# server/coapis/app/services/context_injector.py
from typing import List, Dict, Any
from ..files.manager import FileManager
from ..knowledge.manager import KnowledgeManager

class ContextInjector:
    """上下文注入器：将引用内容注入到AI上下文"""

    def __init__(self):
        self.file_manager = FileManager()
        self.knowledge_manager = KnowledgeManager()

    async def inject_context(
        self,
        message: str,
        file_ids: List[str] = None,
        knowledge_ids: List[str] = None,
    ) -> str:
        """注入上下文到消息中"""

        context_parts = []

        # 注入文件内容
        if file_ids:
            for file_id in file_ids:
                content = await self.file_manager.get_file_content(file_id)
                if content:
                    context_parts.append(f"[文件内容]\n{content}\n")

        # 注入知识库内容
        if knowledge_ids:
            for knowledge_id in knowledge_ids:
                content = await self.knowledge_manager.get_knowledge_content(knowledge_id)
                if content:
                    context_parts.append(f"[知识库内容]\n{content}\n")

        # 组合上下文
        if context_parts:
            full_context = "\n".join(context_parts)
            return f"{full_context}\n[用户问题]\n{message}"

        return message

    async def auto_suggest_references(
        self,
        message: str,
        max_suggestions: int = 3,
    ) -> List[Dict[str, Any]]:
        """根据消息内容自动推荐引用"""

        suggestions = []

        # 检测文件关键词
        file_keywords = self._extract_keywords(message)
        if file_keywords:
            # 搜索我的空间
            files = await self.file_manager.search_files(file_keywords, limit=max_suggestions)
            suggestions.extend([
                {
                    'type': 'file',
                    'id': f['id'],
                    'name': f['name'],
                    'relevance': f['score'],
                }
                for f in files
            ])

        # 检测知识库关键词
        knowledge_keywords = self._extract_knowledge_keywords(message)
        if knowledge_keywords:
            # 搜索知识库
            knowledge = await self.knowledge_manager.search_knowledge(
                knowledge_keywords,
                limit=max_suggestions
            )
            suggestions.extend([
                {
                    'type': 'knowledge',
                    'id': k['id'],
                    'name': k['name'],
                    'relevance': k['score'],
                }
                for k in knowledge
            ])

        # 按相关性排序
        suggestions.sort(key=lambda x: x['relevance'], reverse=True)
        return suggestions[:max_suggestions]
```

**后端：聊天接口增强**

```python
# server/coapis/app/routers/chat.py
from fastapi import APIRouter, Request
from pydantic import BaseModel
from typing import List, Optional
from ..services.context_injector import ContextInjector

router = APIRouter()
context_injector = ContextInjector()

class ChatRequest(BaseModel):
    message: str
    file_ids: Optional[List[str]] = None
    knowledge_ids: Optional[List[str]] = None

@router.post("/chat")
async def chat(
    request: Request,
    body: ChatRequest,
):
    """聊天接口（支持引用）"""

    # 注入上下文
    enhanced_message = await context_injector.inject_context(
        message=body.message,
        file_ids=body.file_ids,
        knowledge_ids=body.knowledge_ids,
    )

    # 调用AI
    response = await ai_client.chat(enhanced_message)

    return {
        'message': response,
        'references': {
            'files': body.file_ids or [],
            'knowledge': body.knowledge_ids or [],
        }
    }

@router.post("/chat/suggest-references")
async def suggest_references(
    request: Request,
    body: ChatRequest,
):
    """根据消息内容推荐引用"""

    suggestions = await context_injector.auto_suggest_references(
        message=body.message,
        max_suggestions=3,
    )

    return {
        'suggestions': suggestions
    }
```

---

### 开发计划

#### 阶段1：基础设施（3天）

- [ ] 设计引用管理数据结构
- [ ] 实现前端状态管理（referenceStore）
- [ ] 实现后端上下文注入器
- [ ] 文件内容提取服务

#### 阶段2：UI组件（5天）

- [ ] 聊天界面三栏布局
- [ ] 左侧面板（我的空间）
- [ ] 右侧面板（知识库）
- [ ] 引用管理组件
- [ ] 文件预览组件

#### 阶段3：核心功能（7天）

- [ ] 文件引用功能
- [ ] 知识库引用功能
- [ ] 引用追踪功能
- [ ] 智能推荐功能
- [ ] 多文件综合分析

#### 阶段4：优化与测试（5天）

- [ ] 性能优化
- [ ] 移动端适配
- [ ] 用户体验优化
- [ ] 测试与修复

**总计：约20天（3周）**

---

## 🔗 方案1：UI嵌入其他系统（中等优先级）

### 核心价值

**解决痛点**：
- ❌ 企业已有成熟系统（OA/ERP/CRM）
- ❌ 员工需要在多个系统间切换
- ❌ AI能力无法触达业务场景

**提升体验**：
- ✅ 无缝集成到现有系统
- ✅ 用户无需切换，在原系统使用AI
- ✅ 降低使用门槛
- ✅ 提升AI覆盖范围

---

### 详细设计

#### 设计原则

**界面极简，能力完整**

- **界面**：只有对话窗口，无管理UI
- **能力**：完整业务赋能，深度集成
- **集成**：自动上下文感知，业务API调用

#### 嵌入方式

##### 方式1：浮动窗口（推荐）

```
┌──────────────────────────────────────┐
│  OA 系统 - 待审批列表                 │
│  ┌────────────────┬─────────────────┐│
│  │ 申请人: 张三    │ 🤖 AI 助手      ││
│  │ 类型: 请假      │                 ││
│  │ 天数: 3天       │ 💬 检测到3条    ││
│  │                │    待审批        ││
│  │ [详情] [审批]   │                 ││
│  ├────────────────┤ ✅ 张三：符合    ││
│  │ 申请人: 李四    │    规定，建议    ││
│  │ 类型: 出差      │    批准         ││
│  │ 天数: 5天      │                 ││
│  │                │ ⚠️ 李四：上月   ││
│  │ [详情] [审批]   │    请假较多     ││
│  └────────────────┴─────────────────┘│
└──────────────────────────────────────┘
```

**特性**：
- 浮动在页面右下角
- 可拖拽移动
- 可调整大小
- 可最小化

#### 集成代码

```html
<!-- 最简集成 -->
<script src="https://cdn.coapis.com/embed/v1/coapis.min.js"></script>
<script>
CoApis.init({
  token: 'your-token',
  agent: 'oa-assistant',

  // 注册业务API
  apis: {
    'approval.getPending': async () => {
      const res = await fetch('/api/approval/pending');
      return res.json();
    },
    'approval.approve': async (ids) => {
      const res = await fetch('/api/approval/approve', {
        method: 'POST',
        body: JSON.stringify({ ids }),
      });
      return res.json();
    },
  },

  // 提供上下文
  contextProvider: () => ({
    currentPage: window.location.pathname,
    pageData: extractPageData(),
  }),
});
</script>
```

#### 核心功能

##### 1. 自动上下文感知

```typescript
// AI自动感知当前页面和业务数据
用户进入: /approval/pending
AI 自动分析:
  - 读取页面数据：15条待审批
  - 识别业务场景：审批流程
  - 智能提示："发现15条待审批，需要帮忙吗？"
  - 可执行操作：批量审批、生成意见、风险分析
```

##### 2. 业务数据读取

```typescript
用户: "分析本月销售数据"
AI:
  1. 自动调用主系统API（ERP）
  2. 获取销售数据
  3. AI分析洞察
  4. 返回分析结果
```

##### 3. 业务操作执行

```typescript
用户: "帮我审批所有请假申请"
AI:
  1. 读取待审批列表（从主系统）
  2. 分析每条申请的合规性
  3. 调用主系统审批API
  4. 返回执行结果
```

---

### 开发计划

#### 阶段1：SDK开发（5天）

- [ ] SDK核心框架
- [ ] 浮动窗口UI组件
- [ ] 上下文自动采集
- [ ] 业务API注册机制

#### 阶段2：集成能力（5天）

- [ ] 自动上下文感知
- [ ] 业务API调用
- [ ] 双向数据交互
- [ ] 智能分析功能

#### 阶段3：文档与示例（2天）

- [ ] 集成文档
- [ ] OA集成示例
- [ ] ERP集成示例
- [ ] CRM集成示例

**总计：约12天（2周）**

---

## 🏢 方案2：业务工作台整合（最低优先级）

### 核心价值

**解决痛点**：
- ❌ 企业系统分散，员工需要频繁切换
- ❌ 缺乏统一入口
- ❌ 各系统数据孤岛

**提升体验**：
- ✅ CoApis成为统一工作台
- ✅ 卡片化整合各系统
- ✅ AI辅助跨系统协作
- ✅ 提升工作效率

---

### 详细设计

#### 界面布局

```
┌──────────────────────────────────────────────────┐
│  CoApis 工作台                                    │
├──────────────────────────────────────────────────┤
│  📋 我的待办    💬 AI助手    📊 数据分析    ⚙️ 设置│
├──────────────────────────────────────────────────┤
│                                                  │
│  ┌─────────────┐  ┌─────────────┐              │
│  │ 📋 待审批   │  │ 📅 日程     │              │
│  │             │  │             │              │
│  │ 12条待处理  │  │ 今天有3个会 │              │
│  │             │  │             │              │
│  │ [查看]      │  │ [查看]      │              │
│  └─────────────┘  └─────────────┘              │
│                                                  │
│  ┌─────────────┐  ┌─────────────┐              │
│  │ 📊 销售数据 │  │ 👥 客户管理 │              │
│  │             │  │             │              │
│  │ 本月目标    │  │ 5个重点客户 │              │
│  │ 完成85%     │  │ 需跟进      │              │
│  │             │  │             │              │
│  │ [查看]      │  │ [查看]      │              │
│  └─────────────┘  └─────────────┘              │
│                                                  │
└──────────────────────────────────────────────────┘
```

#### 卡片类型

##### 1. 系统卡片（外部系统）

```typescript
{
  type: 'system',
  name: 'OA待审批',
  icon: '📋',
  source: 'oa',
  data_endpoint: '/api/oa/approval/pending',
  actions: ['approve', 'reject', 'detail'],
  refresh_interval: 300,
}
```

##### 2. 数据卡片（数据分析）

```typescript
{
  type: 'data',
  name: '销售数据',
  icon: '📊',
  source: 'erp',
  data_endpoint: '/api/erp/sales/summary',
  visualization: 'chart',
  refresh_interval: 3600,
}
```

##### 3. AI卡片（智能助手）

```typescript
{
  type: 'ai',
  name: 'AI助手',
  icon: '🤖',
  capabilities: ['chat', 'analyze', 'suggest'],
  context: 'global',
}
```

#### 核心功能

##### 1. 卡片管理

- 拖拽排序
- 自定义布局
- 快捷操作
- 数据刷新

##### 2. 系统集成

- OAuth认证
- API代理
- 数据同步
- 权限控制

##### 3. AI增强

- 智能推荐
- 自动分析
- 跨系统联动
- 主动提醒

---

### 开发计划

#### 阶段1：基础架构（10天）

- [ ] 工作台框架
- [ ] 卡片组件系统
- [ ] 布局引擎
- [ ] 拖拽排序

#### 阶段2：系统集成（15天）

- [ ] OAuth认证
- [ ] API代理
- [ ] 数据同步
- [ ] 权限管理

#### 阶段3：AI增强（10天）

- [ ] 智能推荐
- [ ] 自动分析
- [ ] 跨系统联动
- [ ] 主动提醒

**总计：约35天（5周）**

---

## 📈 方案协同关系

### 数据流

```
┌─────────────────────────────────────────────────┐
│  方案协同关系                                    │
├─────────────────────────────────────────────────┤
│                                                 │
│  方案3（聊天优化）                               │
│  ├─ 提供核心AI能力                              │
│  ├─ 知识库管理                                  │
│  └─ 文件管理                                    │
│         ↓ 提供能力支撑                          │
│                                                 │
│  方案1（UI嵌入）                                │
│  ├─ 使用方案3的AI能力                           │
│  ├─ 使用方案3的知识库                           │
│  └─ 复用对话组件                                │
│         ↓ 扩展使用场景                          │
│                                                 │
│  方案2（工作台整合）                            │
│  ├─ 整合方案1的嵌入式能力                       │
│  ├─ 使用方案3的AI能力                           │
│  └─ 提供统一工作台                              │
│                                                 │
└─────────────────────────────────────────────────┘
```

### 依赖关系

```
方案3 → 方案1 → 方案2

说明：
- 方案1依赖方案3的AI能力和知识库
- 方案2依赖方案1的嵌入式能力和方案3的AI能力
- 优先完成方案3，为后续方案提供基础
```

---

## 🎯 总结

### 三大方案价值定位

| 方案 | 价值定位 | 目标用户 | 核心场景 |
|------|---------|---------|---------|
| 方案3 | **提升核心体验** | 所有用户 | 聊天时快速访问文件和知识库 |
| 方案1 | **扩展使用场景** | 企业用户 | 在现有系统中使用AI能力 |
| 方案2 | **统一工作平台** | 大型企业 | 一站式工作台，整合所有系统 |

### 实施建议

**第一阶段**（当前）：
- ✅ 优先实施方案3
- ✅ 提升核心聊天体验
- ✅ 增强AI能力
- ✅ 提高用户粘性

**第二阶段**（3个月后）：
- 🚀 实施方案1
- 🚀 提供嵌入式SDK
- 🚀 扩展使用场景
- 🚀 吸引更多企业用户

**第三阶段**（6个月后）：
- 🎯 实施方案2
- 🎯 打造企业工作台
- 🎯 深度业务集成
- 🎯 成为AI中枢平台

---

**三个方案相辅相成，循序渐进，共同构建完整的CoApis生态！** 🚀
