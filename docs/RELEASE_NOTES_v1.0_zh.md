# CoApis v1.0 发布说明

**发布日期**: 2026-05-29
**版本类型**: Initial Release

---

## 概述

v1.0 是一次重大架构重构版本，核心目标是实现**严格的多用户隔离**、**统一的路径架构**和**全局配置管理**。本次发布彻底解决了多用户环境下的数据污染、越权访问和路径混乱问题，并新增了全局模板、全局智能体和系统工具的管理功能。

---

## 主要变更

### 1. 统一路径架构

**旧架构（已废弃）**:
- 系统级文件分散在 `data/`, `config/`, `~/.coapis/`
- 用户数据在 `data/{username}/` 和 `workspaces/{username}/` 双路径并存
- 全局智能体混入 `workspaces/` 目录

**新架构**:
```
/apps/ai/coapis/
├── system/              ← 系统级文件（全局共享）
│   ├── config.json
│   ├── users.json
│   ├── auth.json
│   ├── permissions.json
│   ├── providers.json
│   └── .secret/
│
├── workspaces/{username}/  ← 用户级数据（严格隔离）
│   ├── agents/          ← 用户智能体
│   ├── skills/
│   ├── files/
│   ├── chats/
│   ├── crons/
│   ├── mcp/
│   └── workflows/
│
└── agents/              ← 全局智能体（系统级）
```

### 2. 严格的多用户隔离

| 模块 | 隔离策略 | 存储路径 |
|------|----------|----------|
| 智能体 | 非 Admin 仅可见自身智能体 | `workspaces/{username}/agents/` |
| 聊天历史 | 强制基于 `username` 过滤 | `workspaces/{username}/chats/` |
| 定时任务 | 按用户隔离存储 | `workspaces/{username}/crons/` |
| MCP 客户端 | 按用户隔离存储 | `workspaces/{username}/mcp/` |
| 工作流 | 按用户隔离存储 | `workspaces/{username}/workflows/` |
| 记忆系统 | 按用户隔离存储 | `workspaces/{username}/memory/` |
| 文件管理 | 按用户隔离存储 | `workspaces/{username}/files/` |

### 3. 智能体路径修复（本次新增）

**问题**: 创建新智能体时，工作区路径显示为 `~/.coapis/workspaces/<id>`，这是错误的。

**修复**:
- 用户智能体路径强制为 `workspaces/{username}/agents/<id>`
- `workspaces/{username}/` 前缀不可修改
- 后端验证路径前缀，防止越权创建

### 4. 模型选择权限修复（本次新增）

**问题**: 普通用户无法访问 `/api/models/available`（403 错误），模型选择器为空。

**修复**:
- 将 `/api/models/available` 权限从 `@require_role("admin")` 改为 `@require_permission("models:read")`
- 为 `user` 和 `advanced` 角色添加 `models:read` 权限
- 只返回真正可用的模型（已配置 API Key 或不需要 Key 的 Provider）
- 前端下拉菜单打开时重新获取可用模型列表

---

## Bug 修复

| 问题 | 修复方案 |
|------|----------|
| `/api/users/me` 返回 null | 显式添加 `/users/me` 端点，直接读取中间件状态 |
| 聊天无响应 403 错误 | 移除硬编码 LLM fallback，强制通过 `ProviderManager` 解析 |
| 聊天显示信息丢失 | 修复 `Message.completed` 事件覆盖问题 |
| 智能体下拉菜单隐藏 | 条件从 `agents.length > 1` 改为 `agents.length >= 1` |
| 智能体默认名称显示用户名 | 默认名称统一为 `"Default"` |
| 新用户越权查看他人聊天历史 | 重写 `chats.py`，强制基于 `username` 过滤 |
| MySpace 路由双重注册 | 剥离 `__init__.py` 引用，`_app.py` 显式注册 |
| Provider 配置被空 JSON 覆盖 | 增加空值保护，防止无效配置覆盖默认值 |
| vLLM 字段映射错误 | 兼容 `reasoning` 与 `reasoning_content` 差异 |
| Pydantic 验证错误 | 统一使用 `type="text"` 传输 |

---

## 安全加固

1. **路径遍历防护**: 内置防护，禁止 `..` 和绝对路径
2. **智能体路径隔离**: 用户智能体强制存储在 `workspaces/{username}/agents/` 下
3. **聊天历史隔离**: 所有聊天 CRUD 端点强制基于 `username` 过滤
4. **权限验证**: 所有 API 端点增加权限检查
5. **敏感文件权限**: `auth.json` 和 `users.json` 设置为 `600`

---

## 部署说明

### 系统要求

- Docker 20.10+
- Docker Compose 2.0+
- 4GB+ RAM
- 20GB+ 磁盘空间

### 快速部署

```bash
cd /apps/ai/tool-dev/devs/eater-claw/docker

# 1. 配置环境变量
cp .env.example .env
# 编辑 .env 文件，设置必要参数

# 2. 启动服务
docker compose up -d

# 3. 访问控制台
# 后端: http://localhost:4103
# 前端: http://localhost:4200/console
```

### 首次启动

首次启动时，系统会自动执行初始化脚本：
1. 创建 `system/` 目录
2. 创建 `workspaces/` 目录
3. 生成默认配置文件
4. 创建默认管理员账户（admin/admin123）

---

## 已知问题

1. 旧版数据迁移需要手动执行（提供迁移脚本）
2. 部分第三方技能可能不兼容新路径架构
3. 前端模型选择器首次加载可能需要 2-3 秒

---

## 升级指南

### 从 v1.1.4 升级

1. **备份数据**:
```bash
tar -czf coapis-backup-$(date +%Y%m%d).tar.gz /apps/ai/coapis/
```

2. **停止服务**:
```bash
docker compose down
```

3. **更新代码**:
```bash
git pull origin main
```

4. **迁移数据**（如需要）:
```bash
# 运行迁移脚本（如需要）
python3 scripts/migrate_data.py
```

5. **重启服务**:
```bash
docker compose up -d
```

---

## 测试基线

| 测试项 | 结果 |
|--------|------|
| 认证与用户系统 | ✅ 通过 |
| 模型选择权限 | ✅ 通过 |
| 智能体系统 | ✅ 通过 |
| 聊天系统 | ✅ 通过 |
| 文件管理 | ✅ 通过 |
| 技能系统 | ✅ 通过 |
| 定时任务 | ✅ 通过 |
| 用户隔离验证 | ✅ 通过 |
| 全局模板管理 | ✅ 通过 |
| 全局智能体管理 | ✅ 通过 |
| 系统工具（清理/诊断） | ✅ 通过 |
| CLI 管理命令 | ✅ 通过 |
| Nginx 代理 | ✅ 通过 |
| 权限隔离（Admin vs User） | ✅ 通过 |

**回归测试**: 61/61 通过 ✅（5 个账号 × 全链路交叉验证）

---

## 贡献者

- 以太吃虾（项目发起人）
- CoApis Contributors

---

## 许可证

Apache License 2.0

---

**最后更新**: 2026-05-29
