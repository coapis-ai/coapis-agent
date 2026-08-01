# 场景智能体批量生成报告

> **生成时间**：2026-07-17 20:20:56
> **生成版本**：v2.0（优化版）

---

## 一、生成统计

| 指标 | 数量 |
|------|------|
| **通用场景智能体** | 11 |
| **领域上下文配置** | 10 |
| **错误数量** | 0 |

---

## 二、通用场景列表

1. **会议纪要**（meeting-minutes）
   - 类型：office
   - 支持领域：1个

2. **公文起草**（document-drafting）
   - 类型：office
   - 支持领域：1个

3. **工作报告**（work-report）
   - 类型：office
   - 支持领域：1个

4. **项目审批**（project-approval）
   - 类型：business
   - 支持领域：4个

5. **规划编制**（planning-compilation）
   - 类型：business
   - 支持领域：4个

6. **执法检查**（law-enforcement-inspection）
   - 类型：supervision
   - 支持领域：8个

7. **投诉处理**（complaint-handling）
   - 类型：supervision
   - 支持领域：6个

8. **安全检查**（safety-inspection）
   - 类型：supervision
   - 支持领域：4个

9. **整改验收**（rectification-acceptance）
   - 类型：supervision
   - 支持领域：4个

10. **应急响应**（emergency-response）
   - 类型：business
   - 支持领域：3个

11. **监测分析**（monitoring-analysis）
   - 类型：business
   - 支持领域：4个


---

## 三、智能体存储位置

```
/apps/ai/coapis/agents/
├── scene-meeting-minutes/
├── scene-document-drafting/
├── scene-work-report/
├── ...（共11个智能体）
```

---

## 四、领域上下文配置

存储位置：`/apps/ai/coapis/domain_contexts.json`

包含领域：
- 自然资源和规划（natural-resources）
- 生态环境保护（ecological-environment）
- 农业农村（agriculture-rural）
- 发改（development-reform）
- 住建（housing-construction）
- 教育（education）
- 林草湿荒（forestry-grassland）
- 文化与旅游（culture-tourism）
- 卫生健康（health）
- 综合执法（comprehensive-enforcement）


---

## 五、后续步骤

1. ✅ 验证智能体配置
2. ✅ 测试通用场景的领域适配性
3. ✅ 部署到开发环境
4. ✅ 创建领域独特场景（26个）

---

**报告生成完成**
