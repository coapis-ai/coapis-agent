# 政府行业领域场景智能体基础数据归档

> **归档日期**：2026-07-17
> **归档目的**：保存完整的基础数据，供后续优化和使用

---

## 一、归档目录结构

```
industries-archive/
├── README.md                          # 本文档
│
├── base-data/                         # 原始领域数据（10个领域）
│   ├── natural-resources/
│   │   ├── domain.json                # 领域信息
│   │   └── scenes.json                # 场景列表（10个）
│   │
│   ├── ecological-environment/
│   │   ├── domain.json
│   │   └── scenes.json
│   │
│   ├── agriculture-rural/
│   ├── development-reform/
│   ├── housing-construction/
│   ├── education/
│   ├── forestry-grassland/
│   ├── culture-tourism/
│   ├── health/
│   └── comprehensive-enforcement/
│
├── optimization-records/              # 优化记录
│   ├── SCENE_UNIVERSALITY_ANALYSIS.md  # 通用性深度分析
│   ├── OPTIMIZED_CHECKLIST.md          # 优化方案清单
│   └── SCENE_AGENT_CHECKLIST.md        # 原方案清单（对比用）
│
├── overview.json                       # 行业领域概览
├── optimized_scenes.json               # 优化后场景配置
│
└── scripts/                            # 生成脚本
    ├── generate_scene_agents.py        # 原生成脚本
    └── generate_optimized_agents.py    # 优化后生成脚本（待创建）
```

---

## 二、数据统计

### 2.1 原始数据统计

| 领域 | 场景数量 | 文件大小 |
|------|---------|---------|
| 自然资源和规划 | 10个 | 22KB |
| 生态环境保护 | 10个 | 8.5KB |
| 农业农村 | 10个 | 8.3KB |
| 发改 | 10个 | 8KB |
| 住建 | 10个 | 8KB |
| 教育 | 10个 | 7.5KB |
| 林草湿荒 | 10个 | 2.7KB |
| 文化与旅游 | 10个 | 2.3KB |
| 卫生健康 | 10个 | 2.4KB |
| 综合执法 | 10个 | 2.4KB |
| **总计** | **100个** | **~72KB** |

---

### 2.2 优化后数据统计

| 指标 | 数量 |
|------|------|
| **通用场景** | 11个 |
| **独特场景** | 26个 |
| **总计** | 37个 |
| **减少** | 63个（63%） |

---

## 三、数据用途

### 3.1 基础数据（base-data/）

**用途**：
1. ✅ 原始数据备份，保留完整的领域场景设计
2. ✅ 作为后续优化的参考基础
3. ✅ 如果需要恢复某个领域的场景，可以从这里获取

**使用方法**：
```python
# 加载某个领域的原始场景数据
import json

with open('base-data/natural-resources/scenes.json', 'r', encoding='utf-8') as f:
    scenes = json.load(f)
    
# 获取该领域的所有场景
for scene in scenes['scenes']:
    print(f"场景ID: {scene['id']}, 名称: {scene['name']}")
```

---

### 3.2 优化记录（optimization-records/）

**用途**：
1. ✅ 记录优化分析的完整过程
2. ✅ 说明为什么要这样优化
3. ✅ 提供优化决策依据

**关键文档**：
- `SCENE_UNIVERSALITY_ANALYSIS.md`：通用性深度分析，说明哪些场景可以合并
- `OPTIMIZED_CHECKLIST.md`：优化方案最终清单，说明优化后的智能体列表

---

### 3.3 优化后配置（optimized_scenes.json）

**用途**：
1. ✅ 11个通用场景的完整配置
2. ✅ 领域上下文配置
3. ✅ 智能体生成脚本的数据源

**使用方法**：
```python
# 加载优化后的场景配置
import json

with open('optimized_scenes.json', 'r', encoding='utf-8') as f:
    config = json.load(f)
    
# 获取通用场景
generic_scenes = config['generic_scenes']
for scene in generic_scenes:
    print(f"场景ID: {scene['id']}, 名称: {scene['name']}")
    
# 获取领域上下文
domain_contexts = config['domain_contexts']
for code, context in domain_contexts.items():
    print(f"领域: {context['name']}, 关键词: {context['keywords']}")
```

---

### 3.4 生成脚本（scripts/）

**用途**：
1. ✅ 批量生成智能体的工具脚本
2. ✅ 可重复执行，自动化创建智能体
3. ✅ 支持参数调整和定制化

---

## 四、后续优化方向

### 4.1 短期优化（1-2周）

1. ✅ 创建37个优化后的智能体
2. ✅ 实现领域上下文注入机制
3. ✅ 测试通用场景在不同领域的适配性

---

### 4.2 中期优化（1-2月）

1. 🔄 根据用户反馈，调整场景配置
2. 🔄 增加更多通用场景（如数据分析、报告生成等）
3. 🔄 优化系统提示词，提高专业性

---

### 4.3 长期优化（3-6月）

1. 📅 引入知识图谱，增强专业知识库
2. 📅 实现场景智能体之间的协作机制
3. 📅 建立场景智能体的评价和优化体系

---

## 五、数据维护

### 5.1 数据更新机制

**何时更新**：
- 法律法规变化时
- 业务流程调整时
- 用户反馈需要优化时

**如何更新**：
1. 修改 `optimized_scenes.json` 中的配置
2. 重新执行生成脚本
3. 测试验证后部署

---

### 5.2 数据版本管理

**版本号规则**：
- 主版本号（X.0）：重大结构调整
- 次版本号（0.X）：场景增减或优化
- 修订号（0.0.X）：小幅修改和bug修复

**当前版本**：v2.0（优化后的版本）

---

## 六、使用指南

### 6.1 如何使用基础数据

**场景1：查看某个领域的完整场景**
```bash
cd base-data/natural-resources
cat scenes.json
```

**场景2：查看优化分析过程**
```bash
cd optimization-records
cat SCENE_UNIVERSALITY_ANALYSIS.md
```

**场景3：使用优化后的配置**
```bash
cd ..
cat optimized_scenes.json
```

---

### 6.2 如何重新生成智能体

**步骤1：调整配置**
```bash
vim optimized_scenes.json  # 修改场景配置
```

**步骤2：执行生成脚本**
```bash
cd scripts
python generate_optimized_agents.py
```

**步骤3：验证结果**
```bash
ls /apps/ai/coapis/agents/scene-*
```

---

## 七、归档说明

### 7.1 归档范围

| 类型 | 归档位置 | 说明 |
|------|---------|------|
| **原始领域数据** | base-data/ | 10个领域的完整数据 |
| **优化分析文档** | optimization-records/ | 优化分析过程记录 |
| **优化后配置** | optimized_scenes.json | 11个通用场景配置 |
| **领域概览** | overview.json | 10个领域概览信息 |
| **生成脚本** | scripts/ | 自动化生成工具 |

---

### 7.2 归档目的

1. ✅ **数据备份**：保留完整的基础数据，防止丢失
2. ✅ **可追溯性**：记录优化过程，便于理解和追溯
3. ✅ **可复用性**：提供完整数据和工具，便于后续使用
4. ✅ **可维护性**：建立数据维护机制，支持持续优化

---

## 八、联系和支持

**文档维护**：AI智能体自动维护
**更新日期**：2026-07-17
**版本**：v2.0
**状态**：已归档，可供使用

---

**归档完成！所有基础数据已保存到 `industries-archive/` 目录。**
