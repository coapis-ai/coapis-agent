# 知识库功能说明

## 状态变更

**社区版知识库已废弃**（2026-07-19）

社区版知识库功能已迁移到 **CoApis Enterprise 企业版**。

---

## 企业版知识库

### 获取方式

企业版知识库包含在 CoApis Enterprise 中：
- 项目路径：`/apps/ai/tool-dev/dev-coapis/coapis-pro/`
- 文档路径：`coapis-pro/docs/KNOWLEDGE_BASE_FINAL_DESIGN.md`

### 核心特性

企业版知识库提供完整的知识管理能力：

- ✅ **多租户隔离**：全局/部门/个人三级知识库
- ✅ **权限管理**：RBAC + ABAC 权限控制
- ✅ **向量检索**：基于 Weaviate 的语义搜索
- ✅ **文档处理**：自动解析、分块、向量化
- ✅ **共享机制**：公开/私有/授权多种共享方式
- ✅ **企业级部署**：PostgreSQL + Weaviate 架构

### 技术架构

```
前端：React 18 + Ant Design 5.x
后端：FastAPI + LangChain
数据库：PostgreSQL（权限） + Weaviate（向量）
向量化：OpenAI text2vec-openai
```

### 快速开始

详见企业版文档：
- 设计文档：`coapis-pro/docs/KNOWLEDGE_BASE_FINAL_DESIGN.md`
- 详细设计：`coapis-pro/docs/KNOWLEDGE_BASE_DETAILED_DESIGN.md`
- 开发任务：`coapis-pro/docs/KNOWLEDGE_BASE_DEVELOPMENT_TASKS.md`

---

## 社区版历史

### 原实现

社区版知识库最初是一个试验性实现：
- 数据存储：JSON 文件
- 功能范围：基础文件管理
- 状态：已废弃

### 迁移原因

社区版知识库功能极简，不适合生产环境使用：
- ❌ 无向量检索能力
- ❌ 无权限管理
- ❌ 无多租户隔离
- ❌ 数据存储在JSON文件（不可扩展）

企业版提供了完整的知识管理解决方案。

---

**更新日期**: 2026-07-19  
**维护者**: CoApis Team
