# 专业技能规格模板

> **模板版本**：v1.0
> **适用范围**：所有专业领域技能定义

---

## 📋 技能规格结构

每个专业技能必须包含以下完整定义：

---

## 一、基础信息

```yaml
# 唯一标识
skill_id: "[领域代码]_[功能]_[序号]"
# 示例：gov_policy_draft_001

# 技能名称
skill_name: "[技能名称]"
# 示例：政策文件起草

# 所属领域
skill_category: "[领域名称]"
# 可选：通用办公、政府业务、金融业务、医疗业务、法律业务、工程业务、教育业务

# 技能等级
skill_level: "[等级]"
# 可选：基础、专业、高级

# 技能版本
skill_version: "1.0"

# 创建日期
created_date: "YYYY-MM-DD"

# 最后更新
updated_date: "YYYY-MM-DD"
```

---

## 二、技能描述

```yaml
# 简要描述
description: |
  [一句话描述技能的核心功能]
  示例：根据用户需求和上下文，起草符合规范的政策文件

# 详细说明
detailed_description: |
  [详细描述技能的功能、适用场景、使用方法]
  
# 适用场景
applicable_scenarios:
  - scenario_1: "[场景描述]"
  - scenario_2: "[场景描述]"
  - scenario_3: "[场景描述]"

# 不适用场景
inapplicable_scenarios:
  - scenario_1: "[场景描述]"
  - scenario_2: "[场景描述]"
```

---

## 三、能力要求

### 3.1 知识要求

```yaml
knowledge_requirements:
  # 必备知识
  required_knowledge:
    - knowledge_1: "[知识名称]"
      level: "[深度要求]"  # 了解/熟悉/精通
      source: "[知识来源]"  # 内置/知识库/外部接口
    - knowledge_2: "[知识名称]"
      level: "[深度要求]"
      source: "[知识来源]"
  
  # 推荐知识
  recommended_knowledge:
    - knowledge_1: "[知识名称]"
      level: "[深度要求]"
      source: "[知识来源]"
```

### 3.2 能力要求

```yaml
capability_requirements:
  # 核心能力
  core_capabilities:
    - capability_1:
        name: "[能力名称]"
        level: "[能力等级]"  # 基础/中等/高级
        description: "[能力描述]"
    - capability_2:
        name: "[能力名称]"
        level: "[能力等级]"
        description: "[能力描述]"
  
  # 辅助能力
  auxiliary_capabilities:
    - capability_1:
        name: "[能力名称]"
        level: "[能力等级]"
        description: "[能力描述]"
```

### 3.3 工具要求

```yaml
tool_requirements:
  # 必备工具
  required_tools:
    - tool_1:
        name: "[工具名称]"
        type: "[工具类型]"  # 知识库/模型/外部接口
        purpose: "[用途说明]"
    - tool_2:
        name: "[工具名称]"
        type: "[工具类型]"
        purpose: "[用途说明]"
  
  # 可选工具
  optional_tools:
    - tool_1:
        name: "[工具名称]"
        type: "[工具类型]"
        purpose: "[用途说明]"
```

---

## 四、触发机制

### 4.1 关键词触发

```yaml
trigger_keywords:
  # 精确匹配（完全匹配这些词组）
  exact_match:
    - "关键词1"
    - "关键词2"
    - "关键词3"
  
  # 模糊匹配（正则表达式）
  fuzzy_match:
    - pattern_1: "正则表达式1"
      confidence: 0.9  # 置信度阈值
    - pattern_2: "正则表达式2"
      confidence: 0.8
  
  # 语义匹配（语义相似的词）
  semantic_match:
    - keyword: "核心词"
      synonyms:  # 同义词
        - "同义词1"
        - "同义词2"
      related_terms:  # 相关词
        - "相关词1"
        - "相关词2"
```

### 4.2 上下文触发

```yaml
trigger_contexts:
  # 用户身份触发
  user_identity:
    - identity_1: "[身份类型]"
      weight: 1.0  # 权重
    - identity_2: "[身份类型]"
      weight: 0.8
  
  # 场景触发
  scenarios:
    - scenario_1: "[场景名称]"
      indicators:
        - "[指示器1]"
        - "[指示器2]"
      weight: 0.9
  
  # 任务类型触发
  task_types:
    - task_1: "[任务类型]"
      weight: 1.0
    - task_2: "[任务类型]"
      weight: 0.8
```

### 4.3 触发优先级

```yaml
trigger_priority:
  # 高优先级触发条件
  high_priority:
    - condition: "[触发条件]"
      action: "[执行动作]"
  
  # 中优先级触发条件
  medium_priority:
    - condition: "[触发条件]"
      action: "[执行动作]"
  
  # 低优先级触发条件
  low_priority:
    - condition: "[触发条件]"
      action: "[执行动作]"
```

---

## 五、执行流程

```yaml
execution_flow:
  # 步骤1
  step_1:
    name: "[步骤名称]"
    description: "[步骤描述]"
    input: "[输入内容]"
    output: "[输出内容]"
    tools: "[使用的工具]"
  
  # 步骤2
  step_2:
    name: "[步骤名称]"
    description: "[步骤描述]"
    input: "[输入内容]"
    output: "[输出内容]"
    tools: "[使用的工具]"
  
  # ... 更多步骤
```

---

## 六、输出标准

### 6.1 格式标准

```yaml
output_standards:
  format:
    # 必须遵循的格式
    required_format:
      - "[格式要求1]"
      - "[格式要求2]"
      - "[格式要求3]"
    
    # 推荐的格式
    recommended_format:
      - "[格式建议1]"
      - "[格式建议2]"
```

### 6.2 内容标准

```yaml
output_standards:
  content:
    # 必须包含的内容
    required_content:
      - content_1: "[内容项]"
        description: "[说明]"
      - content_2: "[内容项]"
        description: "[说明]"
    
    # 推荐包含的内容
    recommended_content:
      - content_1: "[内容项]"
        description: "[说明]"
```

### 6.3 质量标准

```yaml
output_standards:
  quality:
    # 准确率要求
    accuracy:
      threshold: 0.90  # 90%
      measurement: "[测量方法]"
    
    # 完整性要求
    completeness:
      threshold: 0.95  # 95%
      measurement: "[测量方法]"
    
    # 规范性要求
    compliance:
      threshold: 1.00  # 100%
      measurement: "[测量方法]"
```

---

## 七、验证机制

### 7.1 自动检查

```yaml
validation:
  auto_check:
    # 格式检查
    format_check:
      enabled: true
      rules:
        - rule_1: "[检查规则]"
        - rule_2: "[检查规则]"
    
    # 内容检查
    content_check:
      enabled: true
      rules:
        - rule_1: "[检查规则]"
        - rule_2: "[检查规则]"
    
    # 逻辑检查
    logic_check:
      enabled: true
      rules:
        - rule_1: "[检查规则]"
        - rule_2: "[检查规则]"
```

### 7.2 人工审核

```yaml
validation:
  human_review:
    # 是否必须人工审核
    required: true/false
    
    # 审核人员要求
    reviewer_requirements:
      role: "[角色要求]"
      expertise: "[专业要求]"
      experience: "[经验要求]"
    
    # 审核要点
    check_points:
      - point_1: "[审核要点]"
        importance: "[重要性]"  # 高/中/低
      - point_2: "[审核要点]"
        importance: "[重要性]"
```

---

## 八、异常处理

```yaml
exception_handling:
  # 无法完成任务时的处理
  unable_to_complete:
    action: "[处理动作]"
    fallback: "[降级方案]"
    message: "[提示信息]"
  
  # 质量不达标时的处理
  quality_not_met:
    action: "[处理动作]"
    retry: true/false
    max_retries: 3
  
  # 工具不可用时的处理
  tool_unavailable:
    action: "[处理动作]"
    alternative_tools: "[替代工具]"
```

---

## 九、示例

### 9.1 输入示例

```yaml
input_example:
  user_input: "帮我起草一份关于加强环境保护的政策文件"
  context:
    user_identity: "政府工作人员"
    department: "生态环境局"
    task_type: "政策起草"
```

### 9.2 输出示例

```yaml
output_example:
  content: |
    [完整的输出内容示例]
  
  metadata:
    skill_used: "gov_policy_draft_001"
    execution_time: "5.2s"
    quality_score: 0.92
```

---

## 十、元数据

```yaml
metadata:
  # 技能作者
  author: "[作者]"
  
  # 审核状态
  review_status: "[状态]"  # 草稿/审核中/已发布/已废弃
  
  # 使用统计
  usage_statistics:
    total_invocations: 0
    success_rate: 0.00
    average_rating: 0.00
  
  # 关联技能
  related_skills:
    - skill_id_1: "[技能ID]"
      relation_type: "[关系类型]"  # 前置/后置/并行/替代
    - skill_id_2: "[技能ID]"
      relation_type: "[关系类型]"
```

---

## 📝 使用说明

### 如何使用此模板

1. **复制模板**：将此模板复制到对应的领域文档中
2. **填写信息**：按照结构填写所有必填项
3. **验证完整性**：确保所有必填项都已填写
4. **提交审核**：提交给专业人员审核
5. **发布使用**：审核通过后发布使用

### 必填项标记

- ✅ **必填**：必须填写，否则技能定义不完整
- ⚠️ **推荐**：建议填写，提升技能质量
- ℹ️ **可选**：可选填写，补充说明

---

**模板维护者**：CoApis AI团队
**模板版本**：v1.0
**更新日期**：2026-07-15
