# CoApis 智能体模板体系优化方案

> 创建时间: 2026-07-01
> 状态: 待评审
> 作者: Paw

---

## 一、现状问题

| # | 问题 | 影响 |
|---|------|------|
| 1 | `_FALLBACK_TEMPLATES` 硬编码在 `migration.py` | 改模板需改代码+重新部署，无法独立管理 |
| 2 | `md_files` 目录不存在但代码引用 | `copy_md_files()` 静默失败，依赖 fallback |
| 3 | `_initialize_agent_workspace` 全局/用户共用 | 无法区分模板策略 |
| 4 | `ensure_global_templates_exist` 创建全局模板 | 全局智能体应手动优化，不该用模板生成 |
| 5 | 7 个全局智能体手动创建但未版本控制 | 无法通过代码复现 |
| 6 | `admin_templates.py` 只管理 2 种文件 | `AGENTS.md`/`MEMORY.md`/`HEARTBEAT.md` 无法管理 |

### 当前数据流（混乱）

```
migration.py 硬编码
    ↓ ensure_global_templates_exist()
system/templates/ (运行时全局模板)
    ↓ copy_workspace_md_files() → copy_md_files()
agents/md_files/{language}/  ← ❌ 不存在，静默失败
    ↓ fallback
各智能体工作区
```

---

## 二、设计原则

### 核心原则

```
┌─────────────────────────────────────────────────────────┐
│                   模板体系分层                            │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  全局智能体 (agents/)                                   │
│  ├── 手动精心优化，每个独立打磨                           │
│  ├── 不依赖模板生成                                      │
│  └── 代码仓库版本控制                                    │
│                                                         │
│  用户智能体 (workspaces/{user}/)                        │
│  ├── 创建时使用简化模板                                   │
│  ├── 模板尽量精简，快速可用                               │
│  └── 用户后续自定义调整                                  │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 关键区别

| 维度 | 全局智能体 | 用户智能体 |
|------|-----------|-----------|
| **用途** | 系统内置角色（QA、Coder 等） | 用户自定义智能体 |
| **位置** | `agents/{id}/` | `workspaces/{user}/{id}/` |
| **来源** | 手动优化，代码仓库版本控制 | 运行时从简化模板生成 |
| **管理权** | 管理员/开发者 | 用户自己 |
| **模板复杂度** | 完整、专业、角色驱动 | 精简、通用、可定制 |
| **更新方式** | 代码提交+版本发布 | Admin 页面/用户自助 |

---

## 三、目标架构

### 目标数据流（清晰）

```
┌─────────────────────────┐         ┌─────────────────────────┐
│   全局智能体             │         │   用户智能体             │
│                         │         │                         │
│  agents/global/         │         │  user_templates.py      │
│  (代码仓库版本控制)      │         │  (简化模板定义)          │
│                         │         │                         │
│  global_default/        │         │  get_user_template()    │
│  global_coder/          │         │       ↓                 │
│  global_analyst/        │         │  copy_user_templates()  │
│  global_writer/         │         │       ↓                 │
│  global_planner/        │         │  workspaces/{user}/     │
│  global_qa_agent/       │         │                         │
│  ai_to_human/           │         │  (运行时生成)            │
└─────────────────────────┘         └─────────────────────────┘
```

---

## 四、完整方案

### Phase 1: 分离模板定义（核心）

#### 1.1 新建用户智能体模板模块

**文件**: `server/coapis/agents/user_templates.py`

```python
# -*- coding: utf-8 -*-
"""用户智能体简化模板 - 创建时使用

模板原则：
- 尽量精简，只保留必要内容
- 中文优先（国内用户为主）
- 预留用户自定义空间
"""

from __future__ import annotations

from typing import Dict

# 用户智能体模板（简化版）
USER_TEMPLATES: Dict[str, Dict[str, str]] = {
    "zh": {
        "SOUL.md": """# 智能体灵魂

_你是一个AI助手，正在成为独特的自己。_

## 核心原则

- **真心帮忙**：直接解决问题，不废话
- **有自己的想法**：可以表达观点和偏好
- **先自己想办法**：读文件、查上下文、用工具

## 边界

- 私密信息绝不泄露
- 不确定时先问再操作
""",
        "AGENTS.md": """# 行为规范

## 核心规则

- 不重复执行相同操作
- 卡住时及时报告
- 先思考再行动

## 安全

- 不泄露私密数据
- 破坏性操作先确认
""",
        "PROFILE.md": """## 身份

- **名字：** 
- **定位：** AI助手
- **风格：** 

## 用户资料

- **名字：** 
- **偏好：** 
""",
        "MEMORY.md": """# 记忆

## 重要决策

(暂无)

## 经验教训

(暂无)
""",
        "HEARTBEAT.md": """# 心跳配置

- **频率：** 每6小时
- **任务：** 检查待办、收件箱、日历
""",
    },
    "en": {
        "SOUL.md": """# Agent Soul

_Become who you want to be._

## Core Principles

- **Help genuinely**: Solve problems directly
- **Have opinions**: Express views and preferences
- **Try first**: Read files, check context, use tools
""",
        "AGENTS.md": """# Rules

- No duplicate execution
- Report when stuck
- Think before acting
""",
        "PROFILE.md": """## Identity

- **Name:** 
- **Role:** AI Assistant
""",
        "MEMORY.md": """# Memory

(Empty)
""",
        "HEARTBEAT.md": """# Heartbeat

- **Frequency:** Every 6h
""",
    },
}


def get_user_template(filename: str, language: str = "zh") -> str | None:
    """获取用户智能体模板内容"""
    lang_templates = USER_TEMPLATES.get(language, USER_TEMPLATES["zh"])
    return lang_templates.get(filename)
```

#### 1.2 修改 `setup_utils.py` - 移除 `md_files` 依赖

**文件**: `server/coapis/agents/utils/setup_utils.py`

变更：
- 删除 `copy_md_files()` 函数中依赖 `md_files` 目录的逻辑
- 新增 `copy_user_templates()` 函数

```python
def copy_user_templates(
    language: str,
    workspace_dir: Path,
    skip_existing: bool = True,
) -> list[str]:
    """为用户智能体工作区复制简化模板"""
    from ..user_templates import get_user_template

    workspace_dir.mkdir(parents=True, exist_ok=True)
    copied = []

    for filename in ["SOUL.md", "AGENTS.md", "PROFILE.md", "MEMORY.md", "HEARTBEAT.md"]:
        content = get_user_template(filename, language)
        if content is None:
            continue

        target = workspace_dir / filename
        if skip_existing and target.exists():
            continue

        target.write_text(content, encoding="utf-8")
        copied.append(filename)

    return copied
```

#### 1.3 修改 `agents.py` - 区分全局/用户初始化

**文件**: `server/coapis/app/routers/agents.py`

变更：
- 拆分 `_initialize_agent_workspace` 为两个函数
- 全局智能体仅创建目录结构，不复制模板
- 用户智能体使用简化模板

```python
def _initialize_user_workspace(
    workspace_dir: Path,
    language: str = "zh",
) -> None:
    """初始化用户智能体工作区 - 使用简化模板"""
    from ..agents.utils import copy_user_templates

    # 创建必要目录
    (workspace_dir / "sessions").mkdir(exist_ok=True)
    (workspace_dir / "memory").mkdir(exist_ok=True)
    (workspace_dir / "skills").mkdir(exist_ok=True)

    # 复制用户模板
    copy_user_templates(language, workspace_dir)

    # 创建 chats.json
    chats_file = workspace_dir / "chats.json"
    if not chats_file.exists():
        chats_file.write_text('{"version": 1, "chats": []}', encoding="utf-8")


def _initialize_global_workspace(
    workspace_dir: Path,
) -> None:
    """初始化全局智能体工作区 - 仅创建目录结构

    全局智能体的 SOUL.md 等文件是手动优化的，不依赖模板
    """
    # 仅创建必要目录，不复制模板
    (workspace_dir / "sessions").mkdir(exist_ok=True)
    (workspace_dir / "memory").mkdir(exist_ok=True)
    (workspace_dir / "skills").mkdir(exist_ok=True)

    # 创建 chats.json
    chats_file = workspace_dir / "chats.json"
    if not chats_file.exists():
        chats_file.write_text('{"version": 1, "chats": []}', encoding="utf-8")
```

---

### Phase 2: 全局智能体版本控制

#### 2.1 创建全局智能体模板目录

**目录**: `server/coapis/agents/global/`

```
server/coapis/agents/global/
├── global_default/
│   ├── SOUL.md
│   ├── AGENTS.md
│   ├── PROFILE.md
│   ├── MEMORY.md
│   ├── HEARTBEAT.md
│   └── agent.json
├── global_coder/
│   ├── SOUL.md
│   ├── AGENTS.md
│   ├── PROFILE.md
│   ├── MEMORY.md
│   ├── HEARTBEAT.md
│   └── agent.json
├── global_analyst/
│   ├── SOUL.md
│   ├── AGENTS.md
│   ├── PROFILE.md
│   ├── MEMORY.md
│   ├── HEARTBEAT.md
│   └── agent.json
├── global_writer/
│   ├── SOUL.md
│   ├── AGENTS.md
│   ├── PROFILE.md
│   ├── MEMORY.md
│   ├── HEARTBEAT.md
│   └── agent.json
├── global_planner/
│   ├── SOUL.md
│   ├── AGENTS.md
│   ├── PROFILE.md
│   ├── MEMORY.md
│   ├── HEARTBEAT.md
│   └── agent.json
├── global_qa_agent/
│   ├── SOUL.md
│   ├── AGENTS.md
│   ├── PROFILE.md
│   ├── MEMORY.md
│   ├── HEARTBEAT.md
│   └── agent.json
└── ai_to_human/
    ├── SOUL.md
    ├── AGENTS.md
    ├── PROFILE.md
    ├── MEMORY.md
    ├── HEARTBEAT.md
    └── agent.json
```

#### 2.2 导出当前全局智能体配置

```bash
# 从现有运行目录导出到代码仓库
cd /apps/ai/tool-dev/dev-coapis/coapis-agent

# 创建目录
mkdir -p server/coapis/agents/global

# 导出 7 个全局智能体
for agent in global_default global_coder global_analyst global_writer global_planner global_qa_agent ai_to_human; do
    cp -r /apps/ai/coapis/agents/$agent server/coapis/agents/global/
done
```

#### 2.3 更新 `.gitignore`

```gitignore
# 排除运行时生成的文件
agents/*/sessions/
agents/*/memory/*.md
agents/*.bak

# 但保留全局智能体模板
!agents/global/
```

#### 2.4 全局智能体加载逻辑

**文件**: `server/coapis/app/migration.py`

变更：`ensure_default_agent_exists` 从 `agents/global/` 复制

```python
def _do_ensure_default_agent() -> None:
    """Internal implementation of default agent initialization."""
    from ..constant import AGENTS_DIR
    from pathlib import Path
    import shutil

    config = load_config()

    # 全局智能体从代码仓库模板加载
    global_template_dir = Path(__file__).parent.parent / "agents" / "global" / "global_default"
    default_workspace = AGENTS_DIR / "global_default"

    # 如果工作区不存在，从模板复制
    if not default_workspace.exists():
        if global_template_dir.exists():
            shutil.copytree(global_template_dir, default_workspace)
            logger.info(f"Created global_default from template: {global_template_dir}")
        else:
            default_workspace.mkdir(parents=True, exist_ok=True)
            logger.warning("global_default template not found, created empty workspace")
    else:
        # 工作区已存在，仅确保目录结构
        (default_workspace / "sessions").mkdir(exist_ok=True)
        (default_workspace / "memory").mkdir(exist_ok=True)

    # ... 其余配置逻辑保持不变
```

---

### Phase 3: 清理死代码

#### 3.1 删除 `md_files` 相关代码

**文件**: `server/coapis/agents/utils/setup_utils.py`

删除以下函数：
- `copy_md_files()` - 依赖不存在的 `md_files` 目录
- `_resolve_md_lang_dir()` - 同上
- `_copy_template_md_files()` - 同上
- `copy_template_md_files()` - 同上
- `copy_workspace_md_files()` - 替换为 `copy_user_templates`
- `copy_builtin_qa_md_files()` - 替换为 `copy_user_templates`

#### 3.2 删除 `ensure_global_templates_exist`

**文件**: `server/coapis/app/migration.py`

删除：
- `_FALLBACK_TEMPLATES` 字典（~60 行硬编码模板）
- `ensure_global_templates_exist()` 函数
- `_TEMPLATE_FILES` 变量

#### 3.3 修改启动流程

**文件**: `server/coapis/app/_app.py`

```python
# 修改前
ensure_default_agent_exists()
ensure_qa_agent_exists()
ensure_global_templates_exist()  # ❌ 删除
ensure_global_agent_roles()
ensure_layered_templates()

# 修改后
ensure_default_agent_exists()
ensure_qa_agent_exists()
ensure_global_agent_roles()
ensure_layered_templates()
```

#### 3.4 修改 `init_cmd.py`

**文件**: `server/coapis/cli/init_cmd.py`

```python
# 删除 import
# from ..app.migration import ensure_global_templates_exist

# 删除调用
# ensure_global_templates_exist()
```

---

### Phase 4: Admin 模板管理（可选）

#### 4.1 扩展 Admin 模板管理

**文件**: `server/coapis/app/routers/admin/admin_templates.py`

```python
# 修改前
TEMPLATE_FILES = ["SOUL.md", "PROFILE.md"]

# 修改后 - 管理全部用户模板文件
TEMPLATE_FILES = [
    "SOUL.md",
    "AGENTS.md",
    "PROFILE.md",
    "MEMORY.md",
    "HEARTBEAT.md",
]
```

#### 4.2 模板来源区分

```python
@router.get("/admin/templates")
async def list_templates(request: Request) -> Dict[str, Any]:
    """获取用户模板列表及内容"""
    from ..agents.user_templates import USER_TEMPLATES

    language = "zh"  # 或从配置读取
    result = {}
    for filename in TEMPLATE_FILES:
        content = USER_TEMPLATES.get(language, {}).get(filename, "")
        result[filename] = {
            "exists": True,
            "size": len(content),
            "content": content,
        }

    return {"templates": result}
```

---

## 五、实施计划

| Phase | 任务 | 时间 | 风险 | 依赖 |
|-------|------|------|------|------|
| 1 | 分离模板定义 | 1-2天 | 低 | 无 |
| 2 | 全局智能体版本控制 | 1天 | 低 | Phase 1 |
| 3 | 清理死代码 | 1-2天 | 中 | Phase 1+2 |
| 4 | Admin 模板管理 | 3-5天 | 低 | Phase 1 |

---

## 六、关键变更点

| 文件 | 变更类型 | 变更内容 |
|------|---------|---------|
| `server/coapis/agents/user_templates.py` | **新建** | 用户简化模板定义 |
| `server/coapis/agents/utils/setup_utils.py` | 修改 | 删除 `md_files` 依赖，新增 `copy_user_templates` |
| `server/coapis/app/routers/agents.py` | 修改 | 区分全局/用户初始化逻辑 |
| `server/coapis/app/migration.py` | 修改 | 删除 `_FALLBACK_TEMPLATES`，从 `agents/global/` 加载 |
| `server/coapis/agents/global/` | **新建** | 7 个全局智能体模板 |
| `server/coapis/app/_app.py` | 修改 | 删除 `ensure_global_templates_exist` 调用 |
| `server/coapis/cli/init_cmd.py` | 修改 | 删除 `ensure_global_templates_exist` 调用 |
| `.gitignore` | 修改 | 允许追踪 `agents/global/` |

---

## 七、验收标准

- [ ] 用户创建新智能体时，使用简化模板生成
- [ ] 全局智能体从 `agents/global/` 加载，不依赖模板生成
- [ ] `md_files` 相关代码全部清理
- [ ] `copy_md_files()` 函数删除或废弃
- [ ] 启动流程不再调用 `ensure_global_templates_exist`
- [ ] 7 个全局智能体配置提交到代码仓库
- [ ] `_FALLBACK_TEMPLATES` 字典删除
- [ ] 用户模板支持中英文
- [ ] Admin 可管理用户模板（Phase 4）

---

## 八、回滚计划

如果优化后出现问题：

1. **恢复 `md_files` 逻辑**: 从 Git 恢复 `setup_utils.py` 旧版本
2. **恢复 `_FALLBACK_TEMPLATES`**: 从 Git 恢复 `migration.py` 旧版本
3. **恢复启动流程**: 重新添加 `ensure_global_templates_exist()` 调用

所有变更通过 Git 管理，可随时回滚到优化前状态。

---

## 九、后续优化方向

1. **模板市场**: 支持用户分享/下载自定义模板
2. **模板版本**: 模板文件支持版本号，便于升级
3. **模板继承**: 用户模板可基于角色模板继承
4. **多语言完善**: 支持更多语言（ru、ja、ko 等）
5. **模板预览**: Admin 页面增加模板预览功能

---

*基于 CoApis 项目实战经验整理*
