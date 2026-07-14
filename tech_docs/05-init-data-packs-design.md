# 初始化数据包统一路径设计

## 设计原则

1. **数据与代码分离** — 所有初始化数据从文件加载，Python 代码只负责加载逻辑
2. **按语言分包** — `zh/`、`en/` 独立目录，互不干扰
3. **语言继承机制** — `en` 继承 `zh` 的结构，只覆盖需要翻译的部分
4. **运行时可达** — 打包进镜像，不依赖外部挂载

## 目录结构

```
data/packs/
├── base/                        # 语言无关的基础数据（所有语言共享）
│   ├── system/
│   │   ├── config.json          # DEFAULT_CONFIG → 提取为文件
│   │   ├── directories.json     # DEFAULT_DIRECTORIES → 提取为文件
│   │   ├── env_vars.json        # DEFAULT_ENV_VARS → 提取为文件
│   │   └── schema_version       # INIT_SCHEMA_VERSION
│   ├── auth/
│   │   ├── admin.json           # DEFAULT_ADMIN_USER
│   │   ├── roles.json           # DEFAULT_ROLES（无语言文本部分）
│   │   └── permissions.json     # DEFAULT_PERMISSIONS
│   └── workspace/
│       ├── json_defaults.json   # _WORKSPACE_JSON_DEFAULTS
│       └── file_list.json       # DEFAULT_WORKSPACE_FILES
│
├── zh/                          # 中文数据包
│   ├── roles.json               # 角色中文名称/描述覆盖
│   ├── templates/
│   │   ├── user_level/          # 用户级模板
│   │   │   ├── SOUL.md
│   │   │   ├── AGENTS.md
│   │   │   ├── PROFILE.md
│   │   │   ├── MEMORY.md
│   │   │   ├── BOOTSTRAP.md
│   │   │   └── HEARTBEAT.md
│   │   └── agent_level/         # 智能体级模板
│   │       ├── SOUL.md
│   │       ├── AGENTS.md
│   │       ├── PROFILE.md
│   │       └── MEMORY.md
│   └── workspace/
│       ├── welcome.md           # 新用户欢迎内容
│       └── memory_init.md       # MEMORY.md 初始内容
│
└── en/                          # 英文数据包（仅覆盖差异）
    ├── roles.json               # 角色英文名称/描述
    ├── templates/
    │   ├── user_level/
    │   │   ├── SOUL.md
    │   │   ├── AGENTS.md
    │   │   ├── PROFILE.md
    │   │   ├── MEMORY.md
    │   │   ├── BOOTSTRAP.md
    │   │   └── HEARTBEAT.md
    │   └── agent_level/
    │       ├── SOUL.md
    │       ├── AGENTS.md
    │       ├── PROFILE.md
    │       └── MEMORY.md
    └── workspace/
        ├── welcome.md
        └── memory_init.md
```

## 数据源提取映射

| 原位置 | 提取到 | 格式 |
|--------|--------|------|
| `defaults.py::DEFAULT_CONFIG` | `base/system/config.json` | JSON |
| `defaults.py::DEFAULT_DIRECTORIES` | `base/system/directories.json` | JSON array |
| `defaults.py::DEFAULT_ENV_VARS` | `base/system/env_vars.json` | JSON dict |
| `defaults.py::DEFAULT_ADMIN_USER` | `base/auth/admin.json` | JSON |
| `defaults.py::DEFAULT_ROLES` | `base/auth/roles.json`（纯结构）+ `{lang}/roles.json`（文本） | JSON |
| `defaults.py::DEFAULT_PERMISSIONS` | `base/auth/permissions.json` | JSON |
| `defaults.py::DEFAULT_WORKSPACE_FILES` | `base/workspace/file_list.json` | JSON array |
| `user_provisioning.py::_WORKSPACE_JSON_DEFAULTS` | `base/workspace/json_defaults.json` | JSON |
| `system/templates/*.md` | `zh/templates/user_level/*.md` | Markdown |
| `system/templates/agent_level/*.md` | `zh/templates/agent_level/*.md` | Markdown |

## 加载机制

### 文件查找优先级

```
1. {WORKING_DIR}/data/packs/{lang}/{path}     ← 用户自定义（最高优先级）
2. {PACKAGE_DIR}/data/packs/{lang}/{path}      ← 内置语言包
3. {PACKAGE_DIR}/data/packs/zh/{path}           ← 中文回退
4. {PACKAGE_DIR}/data/packs/base/{path}         ← 基础数据
5. 代码硬编码兜底                                ← 最后防线
```

### 加载函数签名

```python
def load_pack_file(relative_path: str, language: str = "zh") -> dict | list | str:
    """按语言优先级加载数据包文件。"""

def load_system_config(language: str = "zh") -> dict:
    """加载系统配置（合并 base + lang）。"""

def load_roles(language: str = "zh") -> dict:
    """加载角色定义（base结构 + lang文本覆盖）。"""

def load_template(filename: str, level: str = "user", language: str = "zh") -> str:
    """加载模板文件（按 level + language 查找）。"""
```

## 共享 vs 翻译的边界

### `base/`（语言无关，所有语言共享）
- 目录结构列表
- 系统配置（版本、心跳间隔、认证开关）
- 权限矩阵（模块名+CRUD布尔值）
- admin 默认账号
- JSON 文件默认值（skill.json 等结构）

### `{lang}/`（需要翻译）
- 角色名称/描述（"管理员" → "Admin"）
- 模板 Markdown 内容（SOUL.md、AGENTS.md 等）
- 欢迎文案、记忆初始内容
- 引导文本（BOOTSTRAP.md）

## 代码修改范围

| 文件 | 修改内容 |
|------|---------|
| `server/coapis/system/defaults.py` | 改为从文件加载，保留硬编码兜底 |
| `server/coapis/system/initializer.py` | 初始化时传入 language 参数 |
| `server/coapis/app/user_provisioning.py` | `_copy_base_templates` 感知语言 |
| `server/coapis/agents/templates.py` | `build_agent_template` 模板按语言选择 |
| `server/coapis/constant.py` | 新增 `DATA_PACKS_DIR` 常量 |

## 迁移策略

1. 先在 `data/packs/` 创建完整的中文数据包（从现有代码提取）
2. 修改代码从 `data/packs/` 加载，保留硬编码兜底
3. 创建英文数据包
4. 清理 `system/templates/`（运行时已不再需要预置模板）
