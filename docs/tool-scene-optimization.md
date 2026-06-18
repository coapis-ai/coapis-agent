# 工具触发分析与场景分类优化方案

## 一、现状问题

### 1.1 所有工具都是 "general" 场景

当前 56 个 builtin 工具中，**没有一个设置了 `scene` 字段**。registry.py 虽然支持了 scene，但工具文件的 `@register_tool()` 装饰器中没有传入 scene 参数。

### 1.2 工具重叠严重

分析发现 **11 对高重叠工具**（共享 ≥2 个 tag）：

| 工具对 | 共享 tags | 建议 |
|--------|-----------|------|
| `code_formatter` + `code_docgen` + `code_review` | code, quality | 合并为 `code_quality` |
| `embedding_ops` + `rag_search` | ai, search | rag_search 内嵌 embedding_ops |
| `knowledge_base` + `rag_search` | ai, rag | 合并为 `knowledge_rag` |
| `health_check` + `perf_monitor` | monitoring, ops | 合并为 `sys_monitor` |
| `perf_monitor` + `trace_ops` | performance, ops | trace_ops 合入 perf_monitor |
| `structured_logger` + `perf_monitor` | monitoring, ops | 保留各自独立 |
| `api_mock` + `schema_validate` | dev, api | 保留各自独立（场景不同） |
| `audit_log` + `dependency_audit` | audit, security | 保留各自独立（场景不同） |

### 1.3 Token 开销

| 指标 | 值 |
|------|-----|
| 总工具数 | 56 |
| 估算总 token | ~1,634 |
| 占 128K 上下文 | ~1.3% |

> 注：实际 token 占用比估算高，因为每个工具还有 parameters schema（~100-200 tokens），实际约 **4,000-6,000 tokens**（3-5%）。

---

## 二、场景分类方案

### 2.1 七大场景定义

| 场景 ID | 名称 | 描述 | 包含工具数 |
|---------|------|------|-----------|
| `core` | 核心基础 | 每个 Agent 必备的文件/搜索/Shell/记忆/任务管理 | 15 |
| `coding` | 代码开发 | 代码编写、审查、测试、格式化、文档生成 | 10 |
| `ops` | 运维部署 | 部署、监控、健康检查、性能、日志、定时任务 | 8 |
| `data` | 数据处理 | 数据分析、数据库、缓存、队列、归档 | 7 |
| `security` | 安全审计 | 密钥扫描、依赖审计、审计日志、加密、环境变量 | 6 |
| `ai` | AI 增强 | LLM 调用、Prompt、向量化、知识库、RAG、图像生成 | 8 |
| `collaboration` | 协作通信 | 通知、共享状态、任务分发、跨用户协作 | 4 |

### 2.2 工具分配表

#### core（核心基础）— 15 个，~320 tokens
| 工具 | 说明 |
|------|------|
| `read_file` | 读文件 |
| `write_file` | 写文件 |
| `edit_file` | 编辑文件 |
| `grep_search` | 内容搜索 |
| `glob_search` | 文件搜索 |
| `execute_shell_command` | Shell 命令 |
| `browser_use` | 浏览器操作 |
| `memory_manager` | 长期记忆 |
| `todo_tool` | 任务管理 |
| `send_file_to_user` | 文件发送 |
| `get_current_time` | 时间获取 |
| `desktop_screenshot` | 截图 |
| `view_image` | 图片查看 |
| `spawn_subagent` | 子任务 |
| `chat_with_agent` | Agent 通信 |

#### coding（代码开发）— 10 个，~270 tokens
| 工具 | 说明 |
|------|------|
| `code_runner` | 代码执行 |
| `code_formatter` | 代码格式化 (black/prettier) |
| `code_review` | 代码审查 |
| `code_docgen` | 文档生成 |
| `file_diff` | 文件对比 |
| `ast_search` | AST 搜索 |
| `project_analyzer` | 项目分析 |
| `test_runner` | 测试运行 |
| `text_processor` | 文本处理 |
| `session_search` | 会话搜索 |

#### ops（运维部署）— 8 个，~210 tokens
| 工具 | 说明 |
|------|------|
| `deploy_helper` | 部署助手 (Docker) |
| `perf_monitor` | 性能监控 + 系统健康 |
| `health_check` | 服务探活 |
| `structured_logger` | 结构化日志 |
| `trace_ops` | 分布式追踪 |
| `cron_scheduler` | 定时任务 |
| `auto_heal` | 自动修复 |
| `tool_stats` | 工具统计 |

#### data（数据处理）— 7 个，~180 tokens
| 工具 | 说明 |
|------|------|
| `data_processor` | 数据分析 (CSV/JSON) |
| `db_ops` | 数据库操作 |
| `cache_ops` | 缓存管理 |
| `queue_ops` | 消息队列 |
| `archive_ops` | 压缩解压 |
| `notes` | 笔记 |
| `batch_ops` | 批量操作 |

#### security（安全审计）— 6 个，~170 tokens
| 工具 | 说明 |
|------|------|
| `secret_scan` | 密钥泄露检测 |
| `dependency_audit` | 依赖漏洞扫描 |
| `audit_log` | 操作审计日志 |
| `crypto_ops` | 加密哈希 |
| `env_manager` | 环境变量管理 |
| `resource_guard` | 资源预算守卫 |

#### ai（AI 增强）— 8 个，~280 tokens
| 工具 | 说明 |
|------|------|
| `llm_ops` | LLM 调用封装 |
| `prompt_builder` | Prompt 模板管理 |
| `embedding_ops` | 向量化存储 |
| `knowledge_base` | 知识库管理 |
| `rag_search` | RAG 语义检索 |
| `image_gen` | 图像生成 |
| `skill_manager` | 技能管理 |
| `agent_optimizer` | Agent 优化 |

#### collaboration（协作通信）— 4 个，~130 tokens
| 工具 | 说明 |
|------|------|
| `notify_ops` | 通知推送 |
| `shared_state` | 共享状态 |
| `task_delegation` | 任务分发 |
| `workflow_engine` | 工作流引擎 |

---

## 三、合并建议（减少 5 个工具 → 51 个）

| 合并方案 | 原工具 | 新工具 | 节省 |
|----------|--------|--------|------|
| code_quality | code_formatter + code_docgen + code_review | `code_quality` | 2 个 → 1 个 |
| knowledge_rag | knowledge_base + rag_search + embedding_ops | `knowledge_rag` | 3 个 → 1 个 |
| sys_monitor | perf_monitor + health_check + trace_ops | `sys_monitor` | 3 个 → 1 个 |

合并后：**56 → 51 个工具**，token 估算从 ~1,634 → ~1,450（-11%）。

---

## 四、动态注入方案（核心优化）

### 4.1 方案：按场景动态加载

```
用户发起对话
    ↓
意图识别（简单关键词匹配 或 LLM 轻量分类）
    ↓
确定场景：core + scene_X
    ↓
只注入 core（15 个）+ 相关 scene 的工具
    ↓
LLM 上下文工具列表从 56 个 → 15 + 8-10 个 ≈ 23-25 个
```

### 4.2 Token 节省

| 方案 | 注入工具数 | 估算 token | 占 128K |
|------|-----------|-----------|---------|
| 当前（全量） | 56 | ~5,000 | 3.9% |
| 场景动态注入 | 23-25 | ~2,100 | 1.6% |
| 节省 | -52% | **-58%** | -2.3% |

### 4.3 意图识别规则

```python
SCENE_KEYWORDS = {
    "coding": ["代码", "code", "函数", "类", "debug", "测试", "格式化", "review", "PR", "commit"],
    "ops": ["部署", "deploy", "Docker", "监控", "性能", "健康", "日志", "cron", "定时"],
    "data": ["数据", "CSV", "JSON", "数据库", "SQLite", "缓存", "队列", "分析"],
    "security": ["安全", "密钥", "漏洞", "审计", "加密", "环境变量", "secret"],
    "ai": ["LLM", "AI", "向量", "知识库", "RAG", "Prompt", "图像生成"],
    "collaboration": ["通知", "共享", "分发", "协作", "工作流"],
}
```

### 4.4 实现路径

1. **后端 `_create_toolkit()` 改造**：读取 `scene` 字段，按 core + scene 过滤
2. **前端工具管理 UI**：增加"默认场景"配置，用户可绑定常用场景
3. **意图分类器**：轻量规则匹配（无需 LLM），在 Agent 初始化时确定 scene
4. **fallback**：无法识别场景时注入全部工具（兼容当前行为）

---

## 五、预期收益

| 指标 | 当前 | 优化后 | 改善 |
|------|------|--------|------|
| 注入工具数 | 56 | 23-25 | -55% |
| 工具 token 占用 | ~5,000 | ~2,100 | -58% |
| 工具数（合并后） | 56 | 51 | -9% |
| LLM 推理延迟 | 基准 | -15~20% | 预估 |
| 工具选择准确率 | 基准 | +10~15% | 预估 |

---

## 六、风险与缓解

| 风险 | 缓解 |
|------|------|
| 场景识别错误导致工具缺失 | fallback 到全量注入 |
| 合并工具破坏已有调用 | 保留旧工具名作为别名 |
| 前端需要适配场景筛选 | 已在 v0.7.20 完成场景 Chips |
