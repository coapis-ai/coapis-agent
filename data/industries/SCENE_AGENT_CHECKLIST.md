# 政府行业领域场景智能体创建清单

> **创建日期**：2026-07-17
> **总场景数**：100个
> **总领域数**：10个
> **状态**：待确认后批量创建

---

## 一、总体概览

### 1.1 统计信息

| 指标 | 数量 |
|------|------|
| **总领域数** | 10个 |
| **总场景数** | 100个 |
| **办公通用场景** | 30个 |
| **领域业务场景** | 40个 |
| **监管巡查场景** | 30个 |

---

### 1.2 数据位置

```
数据源：
├── data/industries/overview.json          # 领域概览
├── data/industries/{domain}/domain.json   # 领域信息
└── data/industries/{domain}/scenes.json   # 场景列表

智能体存储位置：
└── {WORKING_DIR}/agents/scene-{scene_id}/
    ├── agent.json      # 智能体配置
    └── MEMORY.md       # 共享进化记忆
```

---

## 二、详细清单（按领域）

### 2.1 自然资源和规划（10个场景）

| 序号 | 场景ID | 场景名称 | 类型 | 分类 | 优先级 | 智能体ID |
|------|--------|---------|------|------|--------|---------|
| 1 | nr-office-meeting | 会议纪要 | 办公 | 办公通用 | 高 | scene-nr-office-meeting |
| 2 | nr-office-document | 公文起草 | 办公 | 办公通用 | 高 | scene-nr-office-document |
| 3 | nr-office-report | 工作报告 | 办公 | 办公通用 | 高 | scene-nr-office-report |
| 4 | nr-business-planning | 规划编制 | 业务 | 国土空间规划 | 高 | scene-nr-business-planning |
| 5 | nr-business-approval | 用地审批 | 业务 | 土地利用管理 | 高 | scene-nr-business-approval |
| 6 | nr-business-survey | 资源调查 | 业务 | 调查监测 | 中 | scene-nr-business-survey |
| 7 | nr-business-registration | 不动产登记 | 业务 | 确权登记 | 中 | scene-nr-business-registration |
| 8 | nr-supervision-inspection | 用地巡查 | 监管 | 执法监察 | 高 | scene-nr-supervision-inspection |
| 9 | nr-supervision-hazard | 地灾排查 | 监管 | 地质环境 | 高 | scene-nr-supervision-hazard |
| 10 | nr-supervision-mine | 矿山监管 | 监管 | 矿产管理 | 中 | scene-nr-supervision-mine |

---

### 2.2 生态环境保护（10个场景）

| 序号 | 场景ID | 场景名称 | 类型 | 分类 | 优先级 | 智能体ID |
|------|--------|---------|------|------|--------|---------|
| 1 | ee-office-meeting | 会议纪要 | 办公 | 办公通用 | 高 | scene-ee-office-meeting |
| 2 | ee-office-document | 公文起草 | 办公 | 办公通用 | 高 | scene-ee-office-document |
| 3 | ee-office-report | 工作报告 | 办公 | 办公通用 | 高 | scene-ee-office-report |
| 4 | ee-business-eia-approval | 环评审批 | 业务 | 环境影响评价 | 高 | scene-ee-business-eia-approval |
| 5 | ee-business-pollution-control | 污染防治 | 业务 | 污染防治 | 高 | scene-ee-business-pollution-control |
| 6 | ee-business-monitoring | 环境监测 | 业务 | 环境监测 | 中 | scene-ee-business-monitoring |
| 7 | ee-business-emergency-response | 应急响应 | 业务 | 环境应急 | 高 | scene-ee-business-emergency-response |
| 8 | ee-supervision-inspection | 执法检查 | 监管 | 环境执法 | 高 | scene-ee-supervision-inspection |
| 9 | ee-supervision-complaint | 信访处理 | 监管 | 信访处理 | 中 | scene-ee-supervision-complaint |
| 10 | ee-supervision-rectification | 整改验收 | 监管 | 执法监管 | 中 | scene-ee-supervision-rectification |

---

### 2.3 农业农村（10个场景）

| 序号 | 场景ID | 场景名称 | 类型 | 分类 | 优先级 | 智能体ID |
|------|--------|---------|------|------|--------|---------|
| 1 | ar-office-meeting | 会议纪要 | 办公 | 办公通用 | 高 | scene-ar-office-meeting |
| 2 | ar-office-document | 公文起草 | 办公 | 办公通用 | 高 | scene-ar-office-document |
| 3 | ar-office-report | 工作报告 | 办公 | 办公通用 | 高 | scene-ar-office-report |
| 4 | ar-business-project-application | 项目申报 | 业务 | 农业发展 | 高 | scene-ar-business-project-application |
| 5 | ar-business-rural-planning | 振兴规划 | 业务 | 乡村振兴 | 高 | scene-ar-business-rural-planning |
| 6 | ar-business-quality-certification | 质量认证 | 业务 | 农产品质量 | 中 | scene-ar-business-quality-certification |
| 7 | ar-business-technical-extension | 技术推广 | 业务 | 农业服务 | 中 | scene-ar-business-technical-extension |
| 8 | ar-supervision-law-enforcement | 执法检查 | 监管 | 农业执法 | 高 | scene-ar-supervision-law-enforcement |
| 9 | ar-supervision-quality-monitoring | 质量监测 | 监管 | 农产品质量 | 中 | scene-ar-supervision-quality-monitoring |
| 10 | ar-supervision-rural-homestead | 宅基地管理 | 监管 | 农村治理 | 中 | scene-ar-supervision-rural-homestead |

---

### 2.4 发改（10个场景）

| 序号 | 场景ID | 场景名称 | 类型 | 分类 | 优先级 | 智能体ID |
|------|--------|---------|------|------|--------|---------|
| 1 | dr-office-meeting | 会议纪要 | 办公 | 办公通用 | 高 | scene-dr-office-meeting |
| 2 | dr-office-document | 公文起草 | 办公 | 办公通用 | 高 | scene-dr-office-document |
| 3 | dr-office-report | 工作报告 | 办公 | 办公通用 | 高 | scene-dr-office-report |
| 4 | dr-business-planning | 规划编制 | 业务 | 发展规划 | 高 | scene-dr-business-planning |
| 5 | dr-business-project-approval | 项目审批 | 业务 | 项目管理 | 高 | scene-dr-business-project-approval |
| 6 | dr-business-economic-analysis | 经济分析 | 业务 | 经济监测 | 高 | scene-dr-business-economic-analysis |
| 7 | dr-business-price-monitoring | 价格监测 | 业务 | 价格管理 | 中 | scene-dr-business-price-monitoring |
| 8 | dr-supervision-project-management | 项目调度 | 监管 | 项目管理 | 高 | scene-dr-supervision-project-management |
| 9 | dr-supervision-price-enforcement | 价格检查 | 监管 | 价格管理 | 中 | scene-dr-supervision-price-enforcement |
| 10 | dr-supervision-investment-audit | 投资审计 | 监管 | 项目管理 | 中 | scene-dr-supervision-investment-audit |

---

### 2.5 住建（10个场景）

| 序号 | 场景ID | 场景名称 | 类型 | 分类 | 优先级 | 智能体ID |
|------|--------|---------|------|------|--------|---------|
| 1 | hc-office-meeting | 会议纪要 | 办公 | 办公通用 | 高 | scene-hc-office-meeting |
| 2 | hc-office-document | 公文起草 | 办公 | 办公通用 | 高 | scene-hc-office-document |
| 3 | hc-office-report | 工作报告 | 办公 | 办公通用 | 高 | scene-hc-office-report |
| 4 | hc-business-construction-permit | 施工许可 | 业务 | 建筑管理 | 高 | scene-hc-business-construction-permit |
| 5 | hc-business-presale-approval | 预售审批 | 业务 | 房地产监管 | 高 | scene-hc-business-presale-approval |
| 6 | hc-business-housing-security | 住房保障 | 业务 | 住房保障 | 中 | scene-hc-business-housing-security |
| 7 | hc-business-bidding-management | 招投标管理 | 业务 | 建筑管理 | 中 | scene-hc-business-bidding-management |
| 8 | hc-supervision-quality-safety | 质量安全检查 | 监管 | 建筑管理 | 高 | scene-hc-supervision-quality-safety |
| 9 | hc-supervision-real-estate | 房地产监管 | 监管 | 房地产监管 | 高 | scene-hc-supervision-real-estate |
| 10 | hc-supervision-property-management | 物业监管 | 监管 | 房地产监管 | 中 | scene-hc-supervision-property-management |

---

### 2.6 教育（10个场景）

| 序号 | 场景ID | 场景名称 | 类型 | 分类 | 优先级 | 智能体ID |
|------|--------|---------|------|------|--------|---------|
| 1 | ed-office-meeting | 会议纪要 | 办公 | 办公通用 | 高 | scene-ed-office-meeting |
| 2 | ed-office-document | 公文起草 | 办公 | 办公通用 | 高 | scene-ed-office-document |
| 3 | ed-office-report | 工作报告 | 办公 | 办公通用 | 高 | scene-ed-office-report |
| 4 | ed-business-enrollment | 招生组织 | 业务 | 招生考试 | 高 | scene-ed-business-enrollment |
| 5 | ed-business-teacher-recruitment | 教师招聘 | 业务 | 教师发展 | 高 | scene-ed-business-teacher-recruitment |
| 6 | ed-business-teacher-training | 教师培训 | 业务 | 教师发展 | 中 | scene-ed-business-teacher-training |
| 7 | ed-business-school-approval | 学校审批 | 业务 | 学校管理 | 中 | scene-ed-business-school-approval |
| 8 | ed-supervision-quality-monitoring | 质量监测 | 监管 | 教育质量 | 高 | scene-ed-supervision-quality-monitoring |
| 9 | ed-supervision-safety-inspection | 安全检查 | 监管 | 学校管理 | 高 | scene-ed-supervision-safety-inspection |
| 10 | ed-supervision-teaching-evaluation | 教学评估 | 监管 | 教育质量 | 中 | scene-ed-supervision-teaching-evaluation |

---

### 2.7 林草湿荒（10个场景）

| 序号 | 场景ID | 场景名称 | 类型 | 分类 | 优先级 | 智能体ID |
|------|--------|---------|------|------|--------|---------|
| 1 | fg-office-meeting | 会议纪要 | 办公 | 办公通用 | 高 | scene-fg-office-meeting |
| 2 | fg-office-document | 公文起草 | 办公 | 办公通用 | 高 | scene-fg-office-document |
| 3 | fg-office-report | 工作报告 | 办公 | 办公通用 | 高 | scene-fg-office-report |
| 4 | fg-business-forest-approval | 采伐审批 | 业务 | 森林资源管理 | 高 | scene-fg-business-forest-approval |
| 5 | fg-business-grassland-approval | 草原审批 | 业务 | 草原资源管理 | 高 | scene-fg-business-grassland-approval |
| 6 | fg-business-wetland-protection | 湿地保护 | 业务 | 湿地保护管理 | 中 | scene-fg-business-wetland-protection |
| 7 | fg-business-wildlife-protection | 野生动物保护 | 业务 | 野生动物保护 | 中 | scene-fg-business-wildlife-protection |
| 8 | fg-supervision-forest-patrol | 森林巡查 | 监管 | 森林资源管理 | 高 | scene-fg-supervision-forest-patrol |
| 9 | fg-supervision-fire-prevention | 防火巡查 | 监管 | 森林防火 | 高 | scene-fg-supervision-fire-prevention |
| 10 | fg-supervision-law-enforcement | 执法检查 | 监管 | 林草执法 | 中 | scene-fg-supervision-law-enforcement |

---

### 2.8 文化与旅游（10个场景）

| 序号 | 场景ID | 场景名称 | 类型 | 分类 | 优先级 | 智能体ID |
|------|--------|---------|------|------|--------|---------|
| 1 | ct-office-meeting | 会议纪要 | 办公 | 办公通用 | 高 | scene-ct-office-meeting |
| 2 | ct-office-document | 公文起草 | 办公 | 办公通用 | 高 | scene-ct-office-document |
| 3 | ct-office-report | 工作报告 | 办公 | 办公通用 | 高 | scene-ct-office-report |
| 4 | ct-business-heritage-protection | 文物保护 | 业务 | 文化遗产保护 | 高 | scene-ct-business-heritage-protection |
| 5 | ct-business-tourism-planning | 旅游规划 | 业务 | 旅游发展 | 高 | scene-ct-business-tourism-planning |
| 6 | ct-business-intangible-heritage | 非遗保护 | 业务 | 文化遗产保护 | 中 | scene-ct-business-intangible-heritage |
| 7 | ct-business-tourism-promotion | 旅游推广 | 业务 | 旅游发展 | 中 | scene-ct-business-tourism-promotion |
| 8 | ct-supervision-market-inspection | 市场检查 | 监管 | 市场监管 | 高 | scene-ct-supervision-market-inspection |
| 9 | ct-supervision-safety-inspection | 安全检查 | 监管 | 安全监管 | 高 | scene-ct-supervision-safety-inspection |
| 10 | ct-supervision-complaint-handling | 投诉处理 | 监管 | 市场监管 | 中 | scene-ct-supervision-complaint-handling |

---

### 2.9 卫生健康（10个场景）

| 序号 | 场景ID | 场景名称 | 类型 | 分类 | 优先级 | 智能体ID |
|------|--------|---------|------|------|--------|---------|
| 1 | he-office-meeting | 会议纪要 | 办公 | 办公通用 | 高 | scene-he-office-meeting |
| 2 | he-office-document | 公文起草 | 办公 | 办公通用 | 高 | scene-he-office-document |
| 3 | he-office-report | 工作报告 | 办公 | 办公通用 | 高 | scene-he-office-report |
| 4 | he-business-medical-approval | 医疗机构审批 | 业务 | 医疗服务 | 高 | scene-he-business-medical-approval |
| 5 | he-business-disease-prevention | 疾病预防 | 业务 | 公共卫生 | 高 | scene-he-business-disease-prevention |
| 6 | he-business-emergency-response | 应急响应 | 业务 | 公共卫生 | 高 | scene-he-business-emergency-response |
| 7 | he-business-health-promotion | 健康促进 | 业务 | 公共卫生 | 中 | scene-he-business-health-promotion |
| 8 | he-supervision-medical-inspection | 医疗检查 | 监管 | 卫生监督 | 高 | scene-he-supervision-medical-inspection |
| 9 | he-supervision-public-health-inspection | 公共卫生检查 | 监管 | 卫生监督 | 高 | scene-he-supervision-public-health-inspection |
| 10 | he-supervision-complaint-handling | 投诉处理 | 监管 | 卫生监督 | 中 | scene-he-supervision-complaint-handling |

---

### 2.10 综合执法（10个场景）

| 序号 | 场景ID | 场景名称 | 类型 | 分类 | 优先级 | 智能体ID |
|------|--------|---------|------|------|--------|---------|
| 1 | ce-office-meeting | 会议纪要 | 办公 | 办公通用 | 高 | scene-ce-office-meeting |
| 2 | ce-office-document | 公文起草 | 办公 | 办公通用 | 高 | scene-ce-office-document |
| 3 | ce-office-report | 工作报告 | 办公 | 办公通用 | 高 | scene-ce-office-report |
| 4 | ce-business-case-handling | 案件办理 | 业务 | 执法业务 | 高 | scene-ce-business-case-handling |
| 5 | ce-business-urban-management | 城市管理 | 业务 | 城市管理执法 | 高 | scene-ce-business-urban-management |
| 6 | ce-business-market-supervision | 市场监管 | 业务 | 市场监管执法 | 高 | scene-ce-business-market-supervision |
| 7 | ce-business-joint-enforcement | 联合执法 | 业务 | 执法协调 | 中 | scene-ce-business-joint-enforcement |
| 8 | ce-supervision-inspection | 执法检查 | 监管 | 执法监督 | 高 | scene-ce-supervision-inspection |
| 9 | ce-supervision-complaint-handling | 投诉处理 | 监管 | 投诉处理 | 高 | scene-ce-supervision-complaint-handling |
| 10 | ce-supervision-enforcement-supervision | 执法监督 | 监管 | 执法监督 | 中 | scene-ce-supervision-enforcement-supervision |

---

## 三、场景类型统计

### 3.1 按类型统计

| 场景类型 | 数量 | 占比 |
|---------|------|------|
| **办公通用** | 30个 | 30% |
| **领域业务** | 40个 | 40% |
| **监管巡查** | 30个 | 30% |

### 3.2 按优先级统计

| 优先级 | 数量 | 占比 |
|--------|------|------|
| **高优先级** | 60个 | 60% |
| **中优先级** | 40个 | 40% |

---

## 四、智能体配置说明

### 4.1 配置结构

每个场景智能体包含以下配置：

```json
{
  "id": "scene-{scene_id}",
  "name": "场景名称",
  "description": "场景描述",
  "model": "gpt-4",
  "system_prompt": "系统提示词",
  "welcome_message": "欢迎消息",
  
  "scene_info": {
    "scene_id": "场景ID",
    "scene_type": "场景类型",
    "category": "场景分类",
    "domain_code": "领域代码",
    "domain_name": "领域名称",
    "tags": ["标签数组"],
    "priority": "优先级"
  },
  
  "skills": ["技能数组"],
  "knowledge_requirements": ["知识要求数组"],
  
  "evolution": {
    "enabled": true,
    "memory_file": "MEMORY.md",
    "max_memory_size": 100,
    "auto_evolve": true
  },
  
  "tools": {
    "enabled": true,
    "whitelist": [],
    "blacklist": []
  }
}
```

---

### 4.2 存储位置

```
{WORKING_DIR}/agents/
├── scene-nr-office-meeting/
│   ├── agent.json
│   └── MEMORY.md
├── scene-nr-office-document/
│   ├── agent.json
│   └── MEMORY.md
├── ...（100个场景智能体）
```

---

## 五、创建流程

### 5.1 批量创建步骤

**步骤1：执行生成脚本**
```bash
cd /apps/ai/tool-dev/dev-coapis/coapis-agent/server/scripts
python generate_scene_agents.py
```

**步骤2：验证创建结果**
```bash
# 检查智能体目录数量
ls -la /apps/ai/coapis/agents/ | grep scene- | wc -l

# 检查某个智能体配置
cat /apps/ai/coapis/agents/scene-nr-office-meeting/agent.json
```

**步骤3：部署到开发环境**
```bash
# 复制到开发环境数据目录
cp -r /apps/ai/coapis/agents/scene-* /apps/ai/coapis-dev/agents/

# 重启服务
cd /apps/ai/tool-dev/dev-coapis/coapis-agent/docker
docker compose -f docker-compose.dev.yaml restart
```

---

## 六、确认清单

### ✅ 待确认事项

请确认以下事项后，即可开始批量创建：

- [ ] **场景数据完整性**：10个领域、100个场景数据已收集完成
- [ ] **场景名称规范性**：所有场景名称简洁，无"助手"二字
- [ ] **系统提示词专业性**：包含专业术语和工作要求
- [ ] **技能关联合理性**：关联实际存在的技能ID
- [ ] **知识要求明确性**：列出关键法规和标准
- [ ] **存储位置正确性**：`/apps/ai/coapis/agents/`
- [ ] **智能体命名规范**：`scene-{scene_id}`
- [ ] **进化配置启用**：共享进化记忆机制

---

## 七、下一步操作

**确认后，我将执行：**

1. ✅ 执行 `generate_scene_agents.py` 批量创建智能体
2. ✅ 验证创建结果（100个智能体）
3. ✅ 部署到开发环境测试
4. ✅ 生成最终部署报告

---

**文档版本**：v1.0
**最后更新**：2026-07-17
**状态**：待用户确认后执行
