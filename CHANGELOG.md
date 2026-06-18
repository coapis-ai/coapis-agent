# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [v0.7.18] - 2026-06-12

### 新增工具
- **结构化日志** — structured_logger，JSON 格式 + 级别过滤 + 字段搜索 + 自动轮转压缩
- **分布式追踪** — trace_ops，创建/结束追踪 + span 耗时 + 瀑布图 + 性能分析
- **健康检查** — health_check，HTTP/TCP/自定义脚本探活 + 历史记录 + 自动触发 auto_heal

## [v0.7.17] - 2026-06-12

### 新增工具
- **SQLite 数据库操作** — db_ops，CRUD + 索引 + 迁移 + 统计，支持多数据库
- **缓存管理** — cache_ops，TTL 过期 + LRU 淘汰 + 批量操作 + 命名空间
- **消息队列** — queue_ops，生产/消费/延迟队列/死信队列 + 优先级 + 重试机制

## [v0.7.16] - 2026-06-12

### 新增工具
- **多渠道通知推送** — notify_ops，console/webhook/email 通知 + 模板变量注入 + 历史记录 + audit_log 联动
- **跨用户状态共享** — shared_state，键值存储 + 乐观锁/悲观锁 + TTL 过期 + 变更追踪
- **任务分发** — task_delegation，任务 CRUD + 分配 + 优先级 + 依赖关系图 + 状态流转

## [v0.7.15] - 2026-06-11

### 新增工具
- **快速 Mock API** — api_mock，基于 JSON 定义生成 Mock 端点，支持动态响应 + 延迟模拟 + FastAPI 脚本生成
- **Schema 校验** — schema_validate，JSON Schema 数据校验 + OpenAPI 定义检查 + 路由完整性检测
- **CHANGELOG 生成** — changelog_gen，基于 git log 自动分类整理（Features/Bug Fixes/Performance...）+ 标签对比

## [v0.7.14] - 2026-06-11

### 新增工具
- **知识库** — knowledge_base，文档入库（分块、向量化、索引），支持文件/URL/直接输入，与 embedding_ops 联动存储
- **RAG 语义检索** — rag_search，从知识库语义检索相关片段并注入上下文，与 knowledge_base + context_manager 联动
- **多格式文档解析** — doc_reader，PDF/DOCX/PPTX/XLSX/图片OCR → 结构化文本，支持自动格式检测 + 直接入库

## [v0.7.13] - 2026-06-11

### 新增工具
- **LLM 调用封装** — llm_ops，summarize/translate/classify/extract/rewrite/analyze + token 成本追踪，与 resource_guard 联动预算控制
- **Prompt 模板管理** — prompt_builder，模板 CRUD + 变量渲染 + 版本管理 + A/B 测试
- **向量化存储** — embedding_ops，文本嵌入 + 存储 + 语义搜索 + 命名空间管理，为 knowledge_base/rag_search 提供底层支撑

## [v0.7.12] - 2026-06-11

### 新增工具
- **密钥泄露检测** — secret_scan，40+ 正则模式 + entropy 检测 + 20+ 种密钥格式（AWS/GitHub/Slack/OpenAI/Stripe 等）
- **依赖漏洞扫描** — dependency_audit，npm/pip/go 依赖扫描 + error_recovery 修复建议 + memory_manager 历史记录
- **操作审计日志** — audit_log，SHA-256 链式哈希不可篡改 + tool_stats 联动统计

## [v0.7.11] - 2026-06-11

### 新增工具
- **性能监控** — perf_monitor，CPU/内存/磁盘/进程监控 + 阈值告警，与 tool_stats 联动检测工具延迟飙升和错误率异常
- **自动修复** — auto_heal，检测磁盘满/内存不足/僵尸进程等问题，结合 error_recovery + checkpoint_tool + memory_manager 实现修复前快照和经验记录
- **资源守卫** — resource_guard，Agent 自身资源预算管理（token 限额/调用频率/内存上限），结合 context_manager 持久化 + tool_stats 统计，超限自动拦截

## [v0.7.10] - 2026-06-11

### 新增工具
- **压缩解压** — archive_ops，zip/tar/tar.gz/tar.bz2/tar.xz 压缩解压，支持 list 查看归档内容、flatten 扁平化解压
- **加密工具** — crypto_ops，MD5/SHA 哈希计算、文件多算法哈希、HMAC 签名/验证、base64 编解码
- **环境变量管理** — env_manager，读取/设置/列出环境变量 + .env 文件读写管理，敏感变量自动检测隐藏
- **剪贴板** — clipboard_ops，读取/写入系统剪贴板（Linux xclip/xsel + Mac pbcopy/pbpaste）

## [v0.7.9] - 2026-06-11

### 新增工具
- **Git 操作** — git_ops，封装 status/diff/log/commit/branch/merge/stash/add/push/pull/fetch 十一种操作，替代手动执行 git shell 命令
- **定时任务** — cron_scheduler，基于系统 crontab 管理定时任务，支持 list/add/remove/enable/disable/show
- **文本处理** — text_processor，编码解码（base64/url/html/hex）+ 文本统计 + 正则替换/提取 + 大小写转换

## [v0.7.8] - 2026-06-11

### 新增工具
- **代码执行器** — code_runner，安全执行 Python/Node 代码片段，子进程隔离 + 超时控制 + 输出捕获
- **代码格式化** — code_formatter，black 格式化 Python，prettier 格式化 JS/TS/JSON/CSS/HTML，支持文件回写
- **代码文档生成** — code_docgen，基于 ast 解析 Python 源码，提取函数签名/参数/类型注解/docstring，输出 markdown/json

## [v0.7.7] - 2026-06-11

### 新增工具
- **数据处理** — data_processor，CSV/JSON 读取/过滤/转换/统计，7 种过滤操作符（eq/neq/gt/lt/gte/lte/contains），自动识别数值列计算 min/max/mean/sum
- **测试运行器** — test_runner，封装 pytest/unittest/npm/maven/go，自动检测框架，解析输出摘要
- **部署助手** — deploy_helper，Docker 构建/运行/停止/状态 + docker-compose up/down/ps/logs，支持 v2 自动检测

## [v0.7.6] - 2026-06-11

### 新增工具
- **上下文管理** — context_manager，跟踪当前任务/打开文件/待办事项/关键决策，帮助 Agent 在多轮对话中保持连贯
- **错误恢复** — error_recovery，17 种常见错误模式库（Python/Network/Docker/Git/Node），自动分析并建议修复方案
- **批量操作** — batch_ops，安全的批量文件操作（find/replace/move/copy/stats），替代 sed/awk/shell，支持 dry_run 预览

## [v0.7.5] - 2026-06-11

### 新增工具
- **HTTP 客户端** — http_client，支持 GET/POST/PUT/DELETE/PATCH 七种方法，带超时重试、JSON 解析、安全防护（阻止内网端点）
- **工具使用追踪** — tool_stats，记录调用次数/成功率/耗时，JSON 存储，提供 record_tool_call() API 供框架集成

### 提示词优化
- **工具链使用指南** — 三语 AGENTS.md 新增「工具链使用指南」section，教 Agent 组合使用工具完成复杂任务（代码修改/问题排查/外部集成/学习积累四种流程）

## [v0.7.4] - 2026-06-11

### 新增工具
- **会话笔记** — notes，轻量级会话级笔记，支持 add/list/search/delete/clear + tag 标签过滤，与 memory_manager（长期记忆）互补
- **代码审查** — code_review，Python/JS/TS 轻量级静态分析，4类规则共13条（安全/复杂度/最佳实践/代码异味），质量评分机制

### 优化
- **工具标签补全** — 全部 30 个 builtin 工具补全 tags 标签，提升工具可发现性

## [v0.7.3] - 2026-06-11

### 新增工具
- **文件差异对比** — file_diff，支持 unified 和 side_by_side 两种 diff 模式，补全 edit_file 只能替换不能对比的短板
- **项目结构分析** — project_analyzer，扫描目录结构、统计语言分布（35+ 种）、识别项目类型（Python/Node/Go/Rust/Docker/FastAPI/React 等）

### 提示词优化
- **代码修改规范** — 三语 AGENTS.md 新增「代码修改规范」section，指导 Agent 用 edit_file + checkpoint_tool + file_diff 组合安全修改代码

## [v0.7.2] - 2026-06-11

### 新增工具
- **检查点管理** — checkpoint_tool，封装 git commit/checkout/diff/log，支持创建快照、恢复、差异比较、查看历史
- **图像生成** — image_gen，FAL API（AI 文生图）+ 本地占位 SVG 双后端，支持 prompt/size/style 参数
- **会话搜索** — session_search，搜索 JSONL 历史、workspace 聊天记录、memory markdown 三种来源

## [v0.7.1] - 2026-06-11

### 新增工具
- **内置网络搜索** — web_search 工具，支持 Tavily（AI 搜索）+ DDGS（免费）双后端自动 fallback，10 分钟内存缓存
- **AST 代码搜索** — ast_search 工具，封装 ast-grep CLI，支持 Python/JS/Go/Rust 等 18 种语言的语法级精准搜索，与 grep_search 互补
- **结构化记忆管理** — memory_manager 工具，JSON 索引存储在 memory/ 目录，支持 add/search/remove/list 操作和模糊搜索

## [v0.7.0] - 2026-06-11

### 新增工具
- **TODO 工具** — 会话级任务清单管理，支持 add/update/remove/complete/list 五种操作，存储在 `files/.todo.json`，适用于 3+ 步骤复杂任务的执行追踪

### 安全增强
- **敏感文件名拦截** — file_guardian 新增 28 个敏感文件名模式（.env、config.yaml、docker-compose.yml、id_rsa、*.pem、*.db 等），自动拦截敏感配置和密钥文件的读写
- **危险命令规则扩展** — YAML 规则从 20 条增至 24 条，新增 SQL 注入（DROP TABLE/DATABASE）、rm -rf 强制删除、环境变量 dump、chmod 递归危险权限 检测

### 提示词优化
- **主动澄清指引** — 三语 AGENTS.md（zh/en/ru）新增「主动澄清」section，引导 Agent 在任务目标不明确、多路径选择、关键参数缺失、不可逆操作、表述模糊矛盾 5 种场景下主动向用户提问

## [v0.6.2] - 2026-06-11

### Bug 修复
- **发送按钮状态修复** — 流式输出期间正确显示停止按钮，SSE 完成后及时重置 loading 状态，解决停止按钮卡住问题
- **停止按钮样式优化** — 流式输出时停止按钮改为红色，视觉上更明确区分发送与停止操作
- **备份页容错加载** — 备份列表页 agents API 调用失败时优雅降级，不阻塞备份列表正常加载

## [v0.5.2] - 2026-06-11

### 安全加固
- **CronManager owner_user_id 约束** — 所有定时任务的 target_user_id 在加载和执行时强制校验，不匹配自动修正+日志告警，防止越权执行
- **Executor 执行层断言** — CronExecutor 执行时二次校验 target_user_id == owner_user_id，不匹配直接 abort

### 心跳 Session 路径修复
- **心跳存储路由** — 有 user_id 时写入 `workspaces/{user}/chat/`（标准路径），无 user_id 时写入 `tmp/heartbeat/{agent_id}/`，不再写入 `agents/{agent_id}/sessions/`
- **心跳清理简化** — `_cleanup_heartbeat_sessions` 只清理 `tmp/heartbeat/`，标准路径由 ChatManager 负责

### 测试
- 新增 11 个单元测试：owner 校验(2)、Executor 断言(2)、心跳路径路由(3)、Registry 传入(1)、清理逻辑(3)

## [v0.5.1] - 2026-06-10

### 记忆系统重构
- **简化用户级目录结构** — 移除 `workspaces/{user}/evolution/`，用户目录仅保留 `MEMORY.md` + `memory/` + `agents/`，逻辑更清晰
- **进化数据集中化** — 用户级进化数据统一存储在 `system/evolution/`，不再每个用户重复存放
- **临时数据独立目录** — 新增根目录 `tmp/`，存放对话轨迹、经验缓冲等临时数据，与系统配置 `system/` 分离
- **BackendReview 路径修复** — Review 文件从 `user/evolution/reviews/` 迁移到 `system/reviews/`，全局共享

### Bug 修复
- **EvolutionEngine 路径错误** — 新增 `workspace_dir` 参数，替代隐式的 `data_dir.parent` 推断，修复智能体记忆文件定位错误
- **用户级进化路径** — `workspace.py`（旧版/新版）中用户智能体的进化数据不再错误写入用户目录

### 运维增强
- **CleanupManager** — 新增系统过程数据自动清理管理器，支持按规则删除/归档过期文件（默认：轨迹1天、经验7天、Review 30天、审计90天）
- **DiskMonitor** — 新增磁盘空间监控器，实时监控各目录使用情况，空间不足时告警
- **数据迁移脚本** — 新增 `migrate_memory.py`，支持 `--dry-run` 预览模式，自动备份旧数据，一键迁移到新结构
- **MemoryManager 简化** — 仅管理 `USER.md` 和 `MEMORY.md`，移除 `AGENTS.md`/`SOUL.md` 的重复读写逻辑

### 测试
- 新增 15 个单元测试 + 3 个集成测试，覆盖路径常量、MemoryManager、EvolutionEngine、CleanupManager、DiskMonitor、迁移脚本

## [v0.5.0] - 2026-06-09

### 技能进化系统
- **触发因果链追踪** — 从用户提问到技能选择到执行效果，完整记录每次技能使用的因果关系
- **五维效能评估** — 量化评估每个技能的触发率、成功率、用户满意度等指标
- **版本管理与回滚** — 技能每次变更自动归档，支持一键回滚到任意历史版本
- **自进化机制** — 技能根据使用数据自动优化触发词和内容，所有改进草稿需人工审批
- **晋升与退役** — 高效技能自动晋升到更高级别，长期低效技能标记退役
- **跨 Agent 传播** — 一个 Agent 验证有效的技能改进，可安全地推广给其他 Agent
- **三级技能体系** — 全局 → 用户 → 智能体级技能，逐层覆盖，灵活定制

### 权限体系
- **细粒度权限管控** — 后端统一管控，前端只读/写入模式自适应
- **魔法命令分级** — 高危命令（模型切换、跨会话停止、守护进程管理）按角色分级控制
- **前端只读模式** — 普通用户隐藏管理类写操作，界面自动适配

### 多用户与安全
- **聊天历史缓存修复** — 三层防御确保每次查看历史都拉取最新数据
- **ACP 跨 Agent 通信** — 统一配置路由，支持 Agent 间协作
- **用户数据隔离加固** — 9 层防护确保用户间数据零泄露

## [v0.3.7] - 2026-06-09

### Added
- 技能列表按分类分组展示，支持来源标记（全局/用户/智能体）
- 全局技能可被智能体级禁用
- 技能分类管理界面

## [v0.3.6] - 2026-06-09

### Added
- 技能按需加载优化，减少 prompt 膨胀
- 工具使用统计埋点
- 幂等工具调用缓存
- 技能描述分层加载（摘要 → 详情按需展开）
- 插件式工具注册机制

## [v0.3.5] - 2026-06-09

### Added
- 权限管理架构改造：后端统一管控菜单和功能访问
- 前端移除硬编码权限判断，改用服务端驱动的访问控制

## [v0.3.0] - 2026-06-08

### Added
- 多模块存储架构改造：消息按智能体隔离存储
- JSONL 轮转策略（10MB 阈值，保留历史备份）
- 心跳 session 过期清理与执行结果持久化
- 统一 Cron 定时任务 API

## [v0.2.2] - 2026-06-08

### Added
- Admin/用户权限隔离与越权测试验证

## [v0.1.0] - 2026-05-06

### Initial Release
- 多用户服务端 AI 智能体平台
- Docker 一键部署
- 聊天、文件管理、进化仪表盘
- 企业级功能：多租户隔离、审计日志、用户管理
- 分层记忆与智能进化系统
- 37+ 内置技能，按需加载
